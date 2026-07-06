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

#[async_trait]
pub trait FileStorage: Send + Sync {
    async fn put(&self, key: &str, bytes: &[u8]) -> anyhow::Result<()>;
    async fn get(&self, key: &str) -> anyhow::Result<Vec<u8>>;
    async fn delete(&self, key: &str) -> anyhow::Result<()>;
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
    async fn put(&self, key: &str, bytes: &[u8]) -> anyhow::Result<()> {
        let path = self.resolve(key)?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).await?;
        }
        fs::write(path, bytes).await?;
        Ok(())
    }

    async fn get(&self, key: &str) -> anyhow::Result<Vec<u8>> {
        let path = self.resolve(key)?;
        Ok(fs::read(path).await?)
    }

    async fn delete(&self, key: &str) -> anyhow::Result<()> {
        let path = self.resolve(key)?;
        match fs::remove_file(path).await {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
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

    async fn delete(&self, key: &str) -> anyhow::Result<()> {
        let (status, body) = self.request("DELETE", key, None).await?;
        if (200..300).contains(&status) {
            Ok(())
        } else {
            anyhow::bail!(
                "remote DELETE {key} failed: HTTP {status} {}",
                String::from_utf8_lossy(&body)
            )
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
        storage.delete("a.txt").await.unwrap();
        storage.delete("a.txt").await.unwrap();
        assert!(!storage.exists("a.txt").await.unwrap());
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
}
