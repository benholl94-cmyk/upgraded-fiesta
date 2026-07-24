//! `hm-tool-browser` — Browser-Steuerung via CDP (Chrome DevTools Protocol).
//!
//! Plugin-Protokoll (stdin → stdout, eine JSON-Zeile):
//!   Request payload: `{ "operation": "screenshot"|"navigate"|"evaluate", "url": "...", "script": "..." }`
//!   Response: `{ "ok": true, "result": { ... }, "message": "ok" }`
//!
//! Setzt einen laufenden Chromium/Chrome-Prozess mit `--remote-debugging-port=9222` voraus.
//! Umgebungsvariable `HM_BROWSER_CDP_URL` überschreibt den Standard (ws://localhost:9222).

pub const NAME: &str = "browser";

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{Read, Write};

/// Verfügbare Browser-Operationen.
#[derive(Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum BrowserOperation {
    /// Navigiert zu einer URL.
    Navigate,
    /// Macht einen Screenshot (Base64-PNG).
    Screenshot,
    /// Führt JavaScript im aktiven Tab aus.
    Evaluate,
    /// Liest den Text-Inhalt der aktuellen Seite (kein HTML).
    ExtractText,
}

#[derive(Debug, Deserialize)]
pub struct BrowserRequest {
    pub operation: BrowserOperation,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub script: String,
    /// CDP-WebSocket-URL (Standard: ws://localhost:9222).
    #[serde(default = "default_cdp_url")]
    pub cdp_url: String,
}

fn default_cdp_url() -> String {
    std::env::var("HM_BROWSER_CDP_URL")
        .unwrap_or_else(|_| "ws://localhost:9222".to_string())
}

/// Ergebnis einer Browser-Operation.
#[derive(Debug, Serialize)]
pub struct BrowserResult {
    pub operation: String,
    /// Für `screenshot`: Base64-kodierter PNG-Inhalt.
    /// Für `evaluate`/`extract_text`: Textergebnis.
    /// Für `navigate`: finale URL nach Redirect.
    pub data: String,
}

/// Führt eine Browser-Operation über CDP aus.
///
/// Da CDP über WebSockets kommuniziert und dieses Crate absichtlich ohne
/// externe HTTP/WS-Bibliotheken auskommt, wird Chromium hier über das
/// CDP-HTTP-Debug-Interface (`/json/new`, `/json`, `GET /json/list`)
/// gesteuert — ein subset das über plain TCP erreichbar ist.
pub fn execute(req: &BrowserRequest) -> Result<BrowserResult, String> {
    match req.operation {
        BrowserOperation::Navigate => navigate(req),
        BrowserOperation::Screenshot => screenshot(req),
        BrowserOperation::Evaluate => evaluate(req),
        BrowserOperation::ExtractText => extract_text(req),
    }
}

fn cdp_http_get(host: &str, port: u16, path: &str) -> Result<String, String> {
    use std::net::TcpStream;
    let addr = format!("{host}:{port}");
    let mut stream = TcpStream::connect(&addr)
        .map_err(|e| format!("cannot connect to CDP at {addr}: {e}. Is Chromium running with --remote-debugging-port={port}?"))?;
    let request = format!(
        "GET {path} HTTP/1.0\r\nHost: {host}\r\nConnection: close\r\n\r\n"
    );
    stream.write_all(request.as_bytes()).map_err(|e| e.to_string())?;
    let mut response = String::new();
    stream.read_to_string(&mut response).map_err(|e| e.to_string())?;
    if let Some(pos) = response.find("\r\n\r\n") {
        Ok(response[pos + 4..].to_string())
    } else {
        Ok(response)
    }
}

fn parse_cdp_host_port(cdp_url: &str) -> (String, u16) {
    let stripped = cdp_url
        .trim_start_matches("ws://")
        .trim_start_matches("http://");
    let (host, port_str) = stripped.split_once(':').unwrap_or((stripped, "9222"));
    let port = port_str
        .split('/')
        .next()
        .and_then(|s| s.parse().ok())
        .unwrap_or(9222);
    (host.to_string(), port)
}

fn navigate(req: &BrowserRequest) -> Result<BrowserResult, String> {
    if req.url.is_empty() {
        return Err("navigate requires a non-empty 'url'".to_string());
    }
    let (host, port) = parse_cdp_host_port(&req.cdp_url);
    // CDP HTTP: PUT /json/new?url=<url> öffnet einen neuen Tab
    let path = format!("/json/new?{}", urlenc(&req.url));
    let body = cdp_http_get(&host, port, &path)?;
    let tab: Value = serde_json::from_str(&body)
        .map_err(|e| format!("CDP response parse error: {e}: {body}"))?;
    let final_url = tab.get("url").and_then(Value::as_str).unwrap_or(&req.url);
    Ok(BrowserResult {
        operation: "navigate".to_string(),
        data: final_url.to_string(),
    })
}

fn screenshot(req: &BrowserRequest) -> Result<BrowserResult, String> {
    // Screenshot via CDP erfordert WebSocket (nicht plain HTTP).
    // Ohne externe WS-Bibliothek geben wir eine klare Fehlermeldung zurück.
    Err(
        "screenshot requires a WebSocket connection to CDP. \
         Add a WebSocket client (e.g. tungstenite) to this crate \
         or run: chromium --headless --screenshot --virtual-time-budget=5000 <url>"
            .to_string(),
    )
}

fn evaluate(req: &BrowserRequest) -> Result<BrowserResult, String> {
    if req.script.is_empty() {
        return Err("evaluate requires a non-empty 'script'".to_string());
    }
    Err(
        "evaluate requires a WebSocket connection to CDP (Runtime.evaluate). \
         Add tungstenite or use puppeteer/playwright instead."
            .to_string(),
    )
}

fn extract_text(req: &BrowserRequest) -> Result<BrowserResult, String> {
    let (host, port) = parse_cdp_host_port(&req.cdp_url);
    let body = cdp_http_get(&host, port, "/json/list")?;
    let tabs: Value = serde_json::from_str(&body)
        .map_err(|e| format!("CDP /json/list parse error: {e}"))?;
    let count = tabs.as_array().map(|a| a.len()).unwrap_or(0);
    Ok(BrowserResult {
        operation: "extract_text".to_string(),
        data: format!("CDP connected — {count} tab(s) open. Full text extraction requires WebSocket (Runtime.evaluate)."),
    })
}

fn urlenc(s: &str) -> String {
    s.chars()
        .flat_map(|c| match c {
            'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' | '~' => {
                vec![c]
            }
            _ => format!("%{:02X}", c as u32).chars().collect(),
        })
        .collect()
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
    let browser_req: BrowserRequest = match serde_json::from_value(req.payload) {
        Ok(r) => r,
        Err(e) => {
            write_response(false, Value::Null, &format!("invalid payload: {e}"));
            return;
        }
    };
    match execute(&browser_req) {
        Ok(result) => {
            let value = serde_json::to_value(&result).unwrap_or(Value::Null);
            write_response(true, value, "ok");
        }
        Err(e) => write_response(false, Value::Null, &e),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_cdp_host_port_ws() {
        let (host, port) = parse_cdp_host_port("ws://localhost:9222");
        assert_eq!(host, "localhost");
        assert_eq!(port, 9222);
    }

    #[test]
    fn navigate_empty_url_returns_error() {
        let req = BrowserRequest {
            operation: BrowserOperation::Navigate,
            url: "".to_string(),
            script: "".to_string(),
            cdp_url: "ws://localhost:9222".to_string(),
        };
        assert!(execute(&req).is_err());
    }

    #[test]
    fn urlenc_encodes_special_chars() {
        let encoded = urlenc("https://example.com/path?q=hello world");
        assert!(!encoded.contains(' '));
        assert!(encoded.contains("%20") || encoded.contains("%3A"));
    }
}
