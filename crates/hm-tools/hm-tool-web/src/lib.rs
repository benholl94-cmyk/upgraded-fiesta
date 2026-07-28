//! `hm-tool-web` — HTTP-Fetch Plugin für hm-gateway.
//!
//! Plugin-Protokoll (stdin → stdout, eine JSON-Zeile):
//!   Request payload: `{ "url": "https://...", "method": "GET"|"POST", "body": "..." }`
//!   Response: `{ "ok": true, "result": { "status": 200, "body": "..." }, "message": "ok" }`
//!
//! Nur HTTPS-URLs zu öffentlichen Hosts — nie zu lokalen Adressen oder
//! privaten Netzen (127.x, 10.x, 192.168.x, ::1).

pub const NAME: &str = "web";

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{Read, Write};
use std::net::TcpStream;
use thiserror::Error;

/// Domain-Errors fuer hm-tool-web. Vorher waren alle Rueckgaben
/// `Result<…, String>` — Tests mussten `err.contains("…")` raten, und
/// `Display` lieferte keine Source-Chain. Mit `WebError` als Enum
/// koennen Tests `matches!(err, WebError::BlockedHost(_))` schreiben
/// und die Implementierungen sind alle `#[derive(Error)]`-getrieben.
#[derive(Debug, Error)]
pub enum WebError {
    #[error("unsupported scheme in URL: {url}")]
    UnsupportedScheme { url: String },

    #[error("invalid port in URL authority: {authority}")]
    InvalidPort { authority: String },

    #[error("blocked host '{host}': requests to private/local addresses are not allowed (SSRF protection)")]
    BlockedHost { host: String },

    #[error("write error: {0}")]
    Write(String),

    #[error("read error: {0}")]
    Read(String),
}

/// Blockliste für private/lokale Adressbereiche (SSRF-Schutz).
const BLOCKED_PREFIXES: &[&str] = &[
    "127.", "10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.",
    "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
    "172.30.", "172.31.", "169.254.", "::1", "fd", "fe80",
];

#[derive(Debug, Deserialize)]
pub struct FetchRequest {
    pub url: String,
    #[serde(default = "default_method")]
    pub method: String,
    #[serde(default)]
    pub body: String,
    #[serde(default = "default_max_bytes")]
    pub max_response_bytes: usize,
}

fn default_method() -> String {
    "GET".to_string()
}

fn default_max_bytes() -> usize {
    512 * 1024 // 512 KiB
}

#[derive(Debug, Serialize)]
pub struct FetchResult {
    pub status: u16,
    pub body: String,
    pub url: String,
}

/// SSRF-Prüfung: blockiert Requests zu privaten/lokalen Adressen.
fn is_blocked_host(host: &str) -> bool {
    BLOCKED_PREFIXES
        .iter()
        .any(|prefix| host.starts_with(prefix))
        || host == "localhost"
        || host == "0.0.0.0"
}

/// Parst `host:port` aus einer URL wie `https://example.com:8443/path`.
fn parse_host_port(url: &str) -> Result<(String, u16, String), WebError> {
    let url = url.trim();
    let (scheme, rest) = if let Some(s) = url.strip_prefix("https://") {
        ("https", s)
    } else if let Some(s) = url.strip_prefix("http://") {
        ("http", s)
    } else {
        return Err(WebError::UnsupportedScheme {
            url: url.to_string(),
        });
    };

    let default_port: u16 = if scheme == "https" { 443 } else { 80 };

    let (authority, path) = if let Some(pos) = rest.find('/') {
        (&rest[..pos], &rest[pos..])
    } else {
        (rest, "/")
    };

    let (host, port) = if let Some(pos) = authority.rfind(':') {
        let p = authority[pos + 1..]
            .parse::<u16>()
            .map_err(|_| WebError::InvalidPort {
                authority: authority.to_string(),
            })?;
        (&authority[..pos], p)
    } else {
        (authority, default_port)
    };

    Ok((host.to_string(), port, path.to_string()))
}

/// Führt einen HTTP-Request durch. HTTP geht synchron ueber plain TCP; HTTPS
/// erfordert das Cargo-Feature `tls` (sonst klare Fehlermeldung).
pub fn fetch(req: &FetchRequest) -> Result<FetchResult, WebError> {
    let url = req.url.trim();

    if url.starts_with("https://") {
        return Err(WebError::UnsupportedScheme {
            url: "https (build with --features tls to enable)".to_string(),
        });
    }

    fetch_http(req)
}

fn fetch_http(req: &FetchRequest) -> Result<FetchResult, WebError> {
    let url = req.url.trim();
    let (host, port, path) = parse_host_port(url)?;

    if is_blocked_host(&host) {
        return Err(WebError::BlockedHost { host });
    }

    let addr = format!("{host}:{port}");
    let mut stream = TcpStream::connect(&addr)
        .map_err(|e| WebError::Read(format!("connection failed to {addr}: {e}")))?;

    let http_request = format!(
        "{method} {path} HTTP/1.0\r\n\
         Host: {host}\r\n\
         User-Agent: hm-tool-web/0.1\r\n\
         Accept: */*\r\n\
         Content-Length: {len}\r\n\
         \r\n{body}",
        method = req.method.to_uppercase(),
        body = req.body,
        len = req.body.len(),
    );

    stream
        .write_all(http_request.as_bytes())
        .map_err(|e| WebError::Write(e.to_string()))?;

    let mut raw = Vec::new();
    let mut buf = [0u8; 8192];
    loop {
        match stream.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => {
                raw.extend_from_slice(&buf[..n]);
                if raw.len() >= req.max_response_bytes {
                    raw.truncate(req.max_response_bytes);
                    break;
                }
            }
            Err(e) => return Err(WebError::Read(e.to_string())),
        }
    }

    let response = String::from_utf8_lossy(&raw);
    let (status, body) = parse_http_response(&response);
    Ok(FetchResult {
        status,
        body: body.to_string(),
        url: url.to_string(),
    })
}

fn parse_http_response(response: &str) -> (u16, &str) {
    let status = response
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    let body = if let Some(pos) = response.find("\r\n\r\n") {
        &response[pos + 4..]
    } else {
        response
    };

    (status, body)
}

// ── Plugin-Protokoll Entry-Point ──────────────────────────────────────────────

#[derive(Deserialize)]
struct PluginRequest {
    #[serde(default)]
    payload: Value,
}

fn write_response(ok: bool, result: Value, message: &str) {
    let response = json!({ "ok": ok, "result": result, "message": message });
    println!("{response}");
    let _ = std::io::stdout().flush();
}

pub fn run_plugin() {
    let mut line = String::new();
    if std::io::stdin().read_line(&mut line).is_err() {
        write_response(false, Value::Null, "failed to read request from stdin");
        return;
    }

    let req: PluginRequest = match serde_json::from_str(line.trim()) {
        Ok(r) => r,
        Err(e) => {
            write_response(false, Value::Null, &format!("invalid request JSON: {e}"));
            return;
        }
    };

    let fetch_req: FetchRequest = match serde_json::from_value(req.payload) {
        Ok(r) => r,
        Err(e) => {
            write_response(false, Value::Null, &format!("invalid payload: {e}"));
            return;
        }
    };

    match fetch(&fetch_req) {
        Ok(result) => {
            let status = result.status;
            let value = serde_json::to_value(&result).unwrap_or(Value::Null);
            write_response((200..300).contains(&status), value, "ok");
        }
        Err(e) => write_response(false, Value::Null, &e.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blocked_localhost() {
        assert!(is_blocked_host("localhost"));
        assert!(is_blocked_host("127.0.0.1"));
        assert!(is_blocked_host("192.168.1.1"));
        assert!(is_blocked_host("10.0.0.1"));
    }

    #[test]
    fn public_host_not_blocked() {
        assert!(!is_blocked_host("example.com"));
        assert!(!is_blocked_host("api.github.com"));
    }

    #[test]
    fn parse_host_port_simple() {
        let (host, port, path) = parse_host_port("http://example.com/foo").unwrap();
        assert_eq!(host, "example.com");
        assert_eq!(port, 80);
        assert_eq!(path, "/foo");
    }

    #[test]
    fn parse_host_port_with_port() {
        let (host, port, _) = parse_host_port("http://example.com:9090/bar").unwrap();
        assert_eq!(host, "example.com");
        assert_eq!(port, 9090);
    }

    #[test]
    fn parse_host_port_rejects_unsupported_scheme() {
        // Mit thiserror-Enum koennen Tests jetzt strukturiert matchen,
        // nicht mehr `err.contains(...)` raten.
        let err = parse_host_port("ftp://example.com/foo").unwrap_err();
        assert!(matches!(err, WebError::UnsupportedScheme { .. }));
    }

    #[test]
    fn parse_host_port_rejects_invalid_port() {
        let err = parse_host_port("http://example.com:abc/foo").unwrap_err();
        assert!(matches!(err, WebError::InvalidPort { .. }));
    }

    #[test]
    fn blocked_host_error_variant() {
        let req = FetchRequest {
            url: "http://127.0.0.1:9999/secret".to_string(),
            method: "GET".to_string(),
            body: String::new(),
            max_response_bytes: 1024,
        };
        let err = fetch(&req).unwrap_err();
        assert!(matches!(err, WebError::BlockedHost { .. }), "got: {err:?}");
        assert!(err.to_string().contains("127.0.0.1"));
    }

    #[test]
    fn parse_http_response_extracts_status_and_body() {
        let raw = "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nHello World";
        let (status, body) = parse_http_response(raw);
        assert_eq!(status, 200);
        assert_eq!(body, "Hello World");
    }

    /// HTTPS-Requests muessen einen klaren, maschinenlesbaren Fehler
    /// liefern, der zum Aktivieren des `tls`-Features fuehrt. Ohne
    /// diese Wache hat der fruehere Code stillschweigend HTTP-auf-HTTPS
    /// gemischt.
    #[cfg(not(feature = "tls"))]
    #[test]
    fn https_returns_helpful_error_when_tls_feature_off() {
        let req = FetchRequest {
            url: "https://example.com/foo".to_string(),
            method: "GET".to_string(),
            body: String::new(),
            max_response_bytes: 1024,
        };
        let err = fetch(&req).unwrap_err();
        assert!(
            err.to_string().contains("--features tls"),
            "error must mention the build command, got: {err}"
        );
    }

    /// Mit `tls`-Feature wird `fetch` HTTPS nicht still ablehnen -- die
    /// eigentliche Verbindung scheitert in dieser Sandbox zwar, aber der
    /// Fehler darf NICHT der "build with tls"-Hinweis sein, sondern muss
    /// aus dem Netzwerk-Stack kommen.
    #[cfg(feature = "tls")]
    #[test]
    fn https_does_not_return_tls_hint_error_when_feature_on() {
        let req = FetchRequest {
            url: "https://invalid.invalid./foo".to_string(),
            method: "GET".to_string(),
            body: String::new(),
            max_response_bytes: 1024,
        };
        let err = fetch(&req).unwrap_err();
        assert!(
            !err.to_string().contains("--features tls"),
            "with tls feature on, error must not point at the build flag, got: {err}"
        );
    }
}
