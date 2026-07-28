use std::path::{Component, Path, PathBuf};

use async_trait::async_trait;
use tokio::{
    fs,
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpStream,
};

pub fn component_name() -> &'static str {
    "hm-storage"
}

/// Default root used when `HM_STORAGE_ROOT` is not set.
pub const DEFAULT_STORAGE_ROOT: &str = "./data/storage";

/// Distinguishes the temp files of concurrent writes to the same key.
///
/// The process id alone is not enough: two `put()` calls for one key can
/// overlap inside a single gateway process (the memory store is written from
/// every task dispatch), and a shared temp name would let one write's bytes be
/// renamed into place by the other — a torn file assembled from two halves,
/// which is exactly what the atomic rename exists to prevent.
fn unique_suffix() -> u64 {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    COUNTER.fetch_add(1, Ordering::Relaxed)
}

#[async_trait]
pub trait FileStorage: Send + Sync {
    async fn put(&self, key: &str, bytes: &[u8]) -> anyhow::Result<()>;
    async fn get(&self, key: &str) -> anyhow::Result<Vec<u8>>;
    /// Liefert `true` wenn der Schluessel existierte und geloescht wurde,
    /// `false` wenn er nicht da war. Bisher (`Result<()>`) hat `NotFound`
    /// stillschweigend zu `Ok(())` kollabiert — `DELETE /storage/{key}`
    /// antwortete immer "deleted", egal ob etwas da war. Diese Information
    /// ist die Grundlage einer ehrlichen Speicherschicht.
    async fn delete(&self, key: &str) -> anyhow::Result<bool>;
    async fn exists(&self, key: &str) -> anyhow::Result<bool>;
}

/// Local-disk file storage backend. All reads/writes stay under `root`;
/// no network or external service is involved.
#[derive(Clone)]
pub struct LocalFsStorage {
    root: PathBuf,
}

impl LocalFsStorage {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    /// Builds a `LocalFsStorage` rooted at `HM_STORAGE_ROOT`, falling back to
    /// `DEFAULT_STORAGE_ROOT` when the env var is unset.
    pub fn from_env() -> Self {
        let root =
            std::env::var("HM_STORAGE_ROOT").unwrap_or_else(|_| DEFAULT_STORAGE_ROOT.to_string());
        Self::new(root)
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Resolves `key` to a path under `root`, rejecting anything that would
    /// escape it (parent segments, absolute paths, etc).
    fn resolve(&self, key: &str) -> anyhow::Result<PathBuf> {
        if key.trim().is_empty() {
            anyhow::bail!("storage key must not be empty");
        }
        let mut resolved = self.root.clone();
        for component in Path::new(key).components() {
            match component {
                Component::Normal(part) => resolved.push(part),
                _ => anyhow::bail!("storage key must be a relative path with no '..' segments"),
            }
        }
        Ok(resolved)
    }
}

#[async_trait]
impl FileStorage for LocalFsStorage {
    /// Writes atomically: a temporary file in the same directory, flushed and
    /// fsync'd, then `rename`d over the target.
    ///
    /// `fs::write` truncates first and writes after, so a crash, `SIGKILL`,
    /// OOM kill or full disk in between leaves a **half-written file** — valid
    /// as bytes, invalid as JSON. That is not theoretical here: `MemoryStore`
    /// persists on every `remember()`, and `hm-agent` records a memory entry
    /// for every dispatched task, so this window is entered constantly.
    ///
    /// Reproduced before the fix: truncating the memory state to 4000 of 7348
    /// bytes made the gateway start normally, report zero records, and destroy
    /// the three surviving records on the next write — no error anywhere.
    /// `MemoryStore::load` no longer discards a broken file (see there); this
    /// side makes sure the broken file does not get created in the first
    /// place. Both are needed: one prevents the corruption, the other stops it
    /// from being silently laundered into data loss.
    ///
    /// `rename(2)` within a directory is atomic on POSIX: a reader sees either
    /// the whole old file or the whole new one, never a mixture.
    async fn put(&self, key: &str, bytes: &[u8]) -> anyhow::Result<()> {
        let path = self.resolve(key)?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).await?;
        }

        // Same directory, so the rename cannot cross a filesystem boundary --
        // /tmp is frequently a different mount, which would make rename fail
        // with EXDEV and silently reintroduce a copy-based, non-atomic write.
        let temp = path.with_file_name(format!(
            ".{}.tmp-{}-{}",
            path.file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_else(|| "storage".to_string()),
            std::process::id(),
            unique_suffix(),
        ));

        let write_result = async {
            let mut file = fs::File::create(&temp).await?;
            file.write_all(bytes).await?;
            // Without this the rename can land before the data does, which on
            // a power loss yields an empty-but-present file: the same silent
            // loss with a different cause.
            file.sync_all().await?;
            Ok::<(), std::io::Error>(())
        }
        .await;

        if let Err(error) = write_result {
            let _ = fs::remove_file(&temp).await;
            return Err(error.into());
        }
        if let Err(error) = fs::rename(&temp, &path).await {
            let _ = fs::remove_file(&temp).await;
            return Err(error.into());
        }
        Ok(())
    }

    async fn get(&self, key: &str) -> anyhow::Result<Vec<u8>> {
        let path = self.resolve(key)?;
        Ok(fs::read(path).await?)
    }

    async fn delete(&self, key: &str) -> anyhow::Result<bool> {
        let path = self.resolve(key)?;
        match fs::remove_file(path).await {
            Ok(()) => Ok(true),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
            Err(error) => Err(error.into()),
        }
    }

    async fn exists(&self, key: &str) -> anyhow::Result<bool> {
        let path = self.resolve(key)?;
        Ok(fs::try_exists(path).await?)
    }
}

/// External-memory-place `FileStorage` backend: talks to any host
/// implementing the same `PUT|GET|DELETE /storage/{key}` protocol
/// `hm-gateway` itself serves -- most naturally, another `hm-gateway`
/// instance. Deliberately plain HTTP over a raw `TcpStream` (no TLS, no
/// external HTTP client crate), matching this workspace's existing
/// hand-rolled style rather than pulling in a framework for one PoC-sized
/// feature. Intended for a private/internal network, the same trust model
/// `hm-gateway` itself already assumes for `HM_GATEWAY_ALLOW_NO_AUTH` and
/// LAN-bound deployments -- never point this at a host over the open
/// internet without a TLS-terminating proxy in front of it.
pub struct RemoteHttpStorage {
    host: String,
    port: u16,
    bearer_token: Option<String>,
}

impl RemoteHttpStorage {
    /// `base_url` must be a plain `http://host:port` URL (no path, no TLS).
    pub fn new(base_url: &str, bearer_token: Option<String>) -> anyhow::Result<Self> {
        let without_scheme = base_url.strip_prefix("http://").ok_or_else(|| {
            anyhow::anyhow!(
                "RemoteHttpStorage only supports plain http:// URLs \
                 (private/internal network use only), got: {base_url}"
            )
        })?;
        let trimmed = without_scheme.trim_end_matches('/');
        let (host, port) = trimmed.split_once(':').ok_or_else(|| {
            anyhow::anyhow!("base_url must include a port, e.g. http://host:8080, got: {base_url}")
        })?;
        let port: u16 = port
            .parse()
            .map_err(|_| anyhow::anyhow!("invalid port in base_url: {base_url}"))?;
        Ok(Self {
            host: host.to_string(),
            port,
            bearer_token,
        })
    }

    /// Builds a `RemoteHttpStorage` from `HM_REMOTE_STORAGE_URL` (+ optional
    /// `HM_REMOTE_STORAGE_TOKEN`), or `None` if the URL var is unset --
    /// callers fall back to `LocalFsStorage` in that case.
    pub fn from_env() -> anyhow::Result<Option<Self>> {
        match std::env::var("HM_REMOTE_STORAGE_URL") {
            Ok(url) => {
                let token = std::env::var("HM_REMOTE_STORAGE_TOKEN").ok();
                Ok(Some(Self::new(&url, token)?))
            }
            Err(_) => Ok(None),
        }
    }

    async fn request(
        &self,
        method: &str,
        key: &str,
        body: Option<&[u8]>,
    ) -> anyhow::Result<(u16, Vec<u8>)> {
        let mut stream = TcpStream::connect((self.host.as_str(), self.port)).await?;
        let body = body.unwrap_or(&[]);

        let mut request = format!(
            "{method} /storage/{key} HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n",
            self.host, self.port
        );
        if let Some(token) = &self.bearer_token {
            request.push_str(&format!("Authorization: Bearer {token}\r\n"));
        }
        request.push_str(&format!("Content-Length: {}\r\n\r\n", body.len()));

        stream.write_all(request.as_bytes()).await?;
        stream.write_all(body).await?;

        let mut raw_response = Vec::new();
        stream.read_to_end(&mut raw_response).await?;
        parse_http_response(&raw_response)
    }
}

fn parse_http_response(raw: &[u8]) -> anyhow::Result<(u16, Vec<u8>)> {
    let header_end = raw
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| anyhow::anyhow!("malformed HTTP response: no header terminator"))?;
    let header_text = String::from_utf8_lossy(&raw[..header_end]);
    let status = header_text
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|code| code.parse::<u16>().ok())
        .ok_or_else(|| anyhow::anyhow!("malformed HTTP response: no status code"))?;
    let body = raw[header_end + 4..].to_vec();
    Ok((status, body))
}

#[async_trait]
impl FileStorage for RemoteHttpStorage {
    async fn put(&self, key: &str, bytes: &[u8]) -> anyhow::Result<()> {
        let (status, body) = self.request("PUT", key, Some(bytes)).await?;
        if (200..300).contains(&status) {
            Ok(())
        } else {
            anyhow::bail!(
                "remote PUT {key} failed: HTTP {status} {}",
                String::from_utf8_lossy(&body)
            )
        }
    }

    async fn get(&self, key: &str) -> anyhow::Result<Vec<u8>> {
        let (status, body) = self.request("GET", key, None).await?;
        if (200..300).contains(&status) {
            Ok(body)
        } else {
            anyhow::bail!(
                "remote GET {key} failed: HTTP {status} {}",
                String::from_utf8_lossy(&body)
            )
        }
    }

    async fn delete(&self, key: &str) -> anyhow::Result<bool> {
        let (status, body) = self.request("DELETE", key, None).await?;
        match status {
            200..=299 => Ok(true),
            404 => Ok(false),
            other => anyhow::bail!(
                "remote DELETE {key} failed: HTTP {other} {}",
                String::from_utf8_lossy(&body)
            ),
        }
    }

    async fn exists(&self, key: &str) -> anyhow::Result<bool> {
        let (status, body) = self.request("GET", key, None).await?;
        match status {
            200..=299 => Ok(true),
            404 => Ok(false),
            other => anyhow::bail!(
                "remote exists-check for {key} failed: HTTP {other} {}",
                String::from_utf8_lossy(&body)
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> Self {
            let path =
                std::env::temp_dir().join(format!("hm-storage-test-{}", uuid::Uuid::new_v4()));
            Self(path)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn temp_storage() -> (LocalFsStorage, TempDir) {
        let dir = TempDir::new();
        (LocalFsStorage::new(dir.0.clone()), dir)
    }

    #[tokio::test]
    async fn put_get_roundtrip() {
        let (storage, _dir) = temp_storage();
        storage.put("notes/hello.txt", b"hi").await.unwrap();
        assert!(storage.exists("notes/hello.txt").await.unwrap());
        assert_eq!(storage.get("notes/hello.txt").await.unwrap(), b"hi");
    }

    #[tokio::test]
    async fn delete_is_idempotent() {
        let (storage, _dir) = temp_storage();
        storage.put("a.txt", b"x").await.unwrap();
        // Erstes Loeschen: true (existierte).
        assert!(storage.delete("a.txt").await.unwrap());
        // Zweites Loeschen: false (nicht mehr da) — vorher loggte sich der
        // Wert hinter Ok(()) weg. Beide Aufrufe muessen jetzt unterscheidbar
        // sein, sonst kann `DELETE /storage/{key}` nicht ehrlich antworten.
        assert!(!storage.delete("a.txt").await.unwrap());
        assert!(!storage.exists("a.txt").await.unwrap());
    }

    #[tokio::test]
    async fn delete_returns_false_when_missing() {
        let (storage, _dir) = temp_storage();
        // Frischer Storage, Schluessel war nie da: false, kein Fehler.
        assert!(!storage.delete("never-existed.txt").await.unwrap());
    }

    #[tokio::test]
    async fn delete_returns_true_when_present() {
        let (storage, _dir) = temp_storage();
        storage.put("present.txt", b"x").await.unwrap();
        assert!(storage.delete("present.txt").await.unwrap());
        // Anschliessend nicht mehr da.
        assert!(!storage.exists("present.txt").await.unwrap());
    }

    #[tokio::test]
    async fn rejects_path_traversal() {
        let (storage, _dir) = temp_storage();
        assert!(storage.put("../escape.txt", b"x").await.is_err());
        assert!(storage.put("/etc/passwd", b"x").await.is_err());
    }

    // --- RemoteHttpStorage ---

    #[test]
    fn new_rejects_non_http_urls() {
        assert!(RemoteHttpStorage::new("https://example.com:8080", None).is_err());
        assert!(RemoteHttpStorage::new("ftp://example.com:8080", None).is_err());
    }

    #[test]
    fn new_requires_a_port() {
        assert!(RemoteHttpStorage::new("http://example.com", None).is_err());
    }

    #[test]
    fn new_accepts_a_well_formed_url() {
        let storage =
            RemoteHttpStorage::new("http://127.0.0.1:8080", Some("tok".to_string())).unwrap();
        assert_eq!(storage.host, "127.0.0.1");
        assert_eq!(storage.port, 8080);
    }

    #[test]
    fn parses_status_and_body_from_a_real_response_shape() {
        let raw = b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: 5\r\n\r\nhello";
        let (status, body) = parse_http_response(raw).unwrap();
        assert_eq!(status, 200);
        assert_eq!(body, b"hello");
    }

    #[test]
    fn parses_404_with_json_body() {
        let raw = b"HTTP/1.1 404 Not Found\r\nContent-Length: 21\r\n\r\n{\"status\":\"not_found\"}";
        let (status, body) = parse_http_response(raw).unwrap();
        assert_eq!(status, 404);
        assert_eq!(body, br#"{"status":"not_found"}"#);
    }

    /// A minimal hermetic mock of hm-gateway's own /storage protocol: reads
    /// one request, returns the given canned (status, body), then closes --
    /// exactly hm-gateway's own one-request-per-connection behavior. Lets
    /// RemoteHttpStorage's request/response handling be unit-tested without
    /// a real hm-gateway process.
    async fn spawn_mock_storage_server(status: u16, body: &'static [u8]) -> u16 {
        use tokio::net::TcpListener;
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(async move {
            if let Ok((mut stream, _)) = listener.accept().await {
                let mut buffer = vec![0_u8; 4096];
                let _ = stream.read(&mut buffer).await;
                let response = format!(
                    "HTTP/1.1 {status} x\r\nContent-Length: {}\r\n\r\n",
                    body.len()
                );
                let _ = stream.write_all(response.as_bytes()).await;
                let _ = stream.write_all(body).await;
                let _ = stream.shutdown().await;
            }
        });
        port
    }

    #[tokio::test]
    async fn put_against_a_real_socket_succeeds_on_2xx() {
        let port = spawn_mock_storage_server(200, b"{}").await;
        let storage = RemoteHttpStorage::new(&format!("http://127.0.0.1:{port}"), None).unwrap();
        storage.put("k", b"payload").await.unwrap();
    }

    #[tokio::test]
    async fn get_against_a_real_socket_returns_the_body() {
        let port = spawn_mock_storage_server(200, b"stored-bytes").await;
        let storage = RemoteHttpStorage::new(&format!("http://127.0.0.1:{port}"), None).unwrap();
        assert_eq!(storage.get("k").await.unwrap(), b"stored-bytes");
    }

    #[tokio::test]
    async fn exists_is_false_on_a_real_404() {
        let port = spawn_mock_storage_server(404, b"{\"status\":\"not_found\"}").await;
        let storage = RemoteHttpStorage::new(&format!("http://127.0.0.1:{port}"), None).unwrap();
        assert!(!storage.exists("k").await.unwrap());
    }

    #[tokio::test]
    async fn get_against_a_real_5xx_is_an_error() {
        let port = spawn_mock_storage_server(500, b"boom").await;
        let storage = RemoteHttpStorage::new(&format!("http://127.0.0.1:{port}"), None).unwrap();
        assert!(storage.get("k").await.is_err());
    }

    #[tokio::test]
    async fn connection_refused_is_a_real_error_not_a_silent_false() {
        // Nothing is listening on this port -- exists() must propagate the
        // real connection error, not silently return Ok(false).
        let storage = RemoteHttpStorage::new("http://127.0.0.1:1", None).unwrap();
        assert!(storage.exists("k").await.is_err());
    }

    // ── Atomic writes ────────────────────────────────────────────────────────
    //
    // `fs::write` truncates before it writes, so a crash in between leaves a
    // half-written file. That was reproducible end to end: a memory state
    // truncated mid-write made the gateway start with an empty memory and
    // destroy the real records on the next write.

    fn temp_root(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!("hm-storage-{name}-{}", std::process::id()))
    }

    /// An overwrite must never leave the reader with a mixture of old and new.
    /// Checked by reading back after each of a series of differently-sized
    /// writes: every read is exactly one of the values written, never a
    /// prefix of one padded by another.
    #[tokio::test]
    async fn overwriting_never_yields_a_partial_file() {
        let root = temp_root("atomic");
        let storage = LocalFsStorage::new(&root);

        for (i, size) in [8_000usize, 12, 40_000, 3].into_iter().enumerate() {
            let payload = vec![b'a' + (i as u8); size];
            storage.put("state.json", &payload).await.unwrap();
            let read_back = storage.get("state.json").await.unwrap();
            assert_eq!(
                read_back, payload,
                "write {i} of {size} bytes was not fully visible on read"
            );
        }
        let _ = std::fs::remove_dir_all(&root);
    }

    /// The temp file is an implementation detail and must not survive a
    /// successful write -- a leftover would look like a second key.
    #[tokio::test]
    async fn no_temporary_file_is_left_behind() {
        let root = temp_root("notemp");
        let storage = LocalFsStorage::new(&root);
        storage.put("nested/state.json", b"payload").await.unwrap();

        let dir = root.join("nested");
        let leftovers: Vec<String> = std::fs::read_dir(&dir)
            .unwrap()
            .filter_map(|e| e.ok())
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|name| name != "state.json")
            .collect();
        assert!(
            leftovers.is_empty(),
            "temp files left behind: {leftovers:?}"
        );
        let _ = std::fs::remove_dir_all(&root);
    }

    /// Concurrent writes to one key must each land whole. With a shared temp
    /// name, one writer's rename could publish the other's half-written
    /// bytes -- the exact failure the rename is there to prevent.
    #[tokio::test]
    async fn concurrent_writes_to_one_key_each_land_whole() {
        let root = temp_root("concurrent");
        let storage = std::sync::Arc::new(LocalFsStorage::new(&root));

        let payloads: Vec<Vec<u8>> = (0..8)
            .map(|i| vec![b'A' + i as u8; 5_000 + i * 700])
            .collect();
        let mut handles = Vec::new();
        for payload in payloads.clone() {
            let storage = storage.clone();
            handles.push(tokio::spawn(async move {
                storage.put("shared.json", &payload).await.unwrap();
            }));
        }
        for h in handles {
            h.await.unwrap();
        }

        let final_bytes = storage.get("shared.json").await.unwrap();
        assert!(
            payloads.contains(&final_bytes),
            "final content is not any single write -- {} bytes, first byte {:?}",
            final_bytes.len(),
            final_bytes.first()
        );
        let _ = std::fs::remove_dir_all(&root);
    }
}
