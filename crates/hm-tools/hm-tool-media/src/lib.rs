//! `hm-tool-media` — Media-Analyse Plugin für hm-gateway.
//!
//! Plugin-Protokoll (stdin → stdout, eine JSON-Zeile):
//!   Request payload: `{ "operation": "inspect"|"thumbnail"|"transcode", "path": "/abs/path/to/file" }`
//!   Response: `{ "ok": true, "result": { "format": "...", "size": 12345, ... }, "message": "ok" }`
//!
//! Nutzt externe System-Tools (`file`, `identify`, `ffprobe`) wenn vorhanden —
//! fällt auf eingebaute Signatur-Erkennung zurück wenn nicht.

pub const NAME: &str = "media";

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{Read, Write};
use std::path::Path;
use std::process::Command;

/// Verfügbare Media-Operationen.
#[derive(Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum MediaOperation {
    /// Dateiformat, Größe und grundlegende Metadaten ermitteln.
    Inspect,
    /// Dateiformat anhand Magic Bytes erkennen (kein externes Tool).
    Detect,
    /// Dauer und Codec-Info via `ffprobe` ermitteln (falls installiert).
    Probe,
}

#[derive(Debug, Deserialize)]
pub struct MediaRequest {
    pub operation: MediaOperation,
    /// Absoluter Pfad zur Mediendatei.
    pub path: String,
}

#[derive(Debug, Serialize)]
pub struct MediaResult {
    pub operation: String,
    pub path: String,
    pub format: String,
    pub size_bytes: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub extra: Option<Value>,
}

/// Magic-Byte-Signaturen für gängige Medienformate.
const SIGNATURES: &[(&[u8], &str)] = &[
    (b"\xFF\xD8\xFF", "jpeg"),
    (b"\x89PNG\r\n\x1A\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"RIFF", "wav/avi"),  // Erstes Segment — für sicheres Matching WAVE/AVI unterscheiden
    (b"ftyp", "mp4/mov"),  // an Byte-Offset 4 — vereinfachte Prüfung
    (b"\x1A\x45\xDF\xA3", "webm/mkv"),
    (b"ID3", "mp3"),
    (b"\xFF\xFB", "mp3"),
    (b"OggS", "ogg"),
    (b"fLaC", "flac"),
    (b"BM", "bmp"),
    (b"\x00\x00\x01\x00", "ico"),
    (b"WEBP", "webp"), // an Offset 8 — vereinfachte Prüfung
    (b"%PDF", "pdf"),
];

/// Erkennt das Dateiformat anhand der ersten Bytes.
pub fn detect_format(path: &Path) -> String {
    use std::fs::File;
    let Ok(mut f) = File::open(path) else {
        return "unknown".to_string();
    };
    let mut header = [0u8; 16];
    let n = f.read(&mut header).unwrap_or(0);
    let header = &header[..n];

    for (sig, fmt) in SIGNATURES {
        if header.starts_with(sig) {
            return fmt.to_string();
        }
    }

    // Texterkennung: wenn alle Bytes druckbar sind → text
    if header.iter().all(|b| b.is_ascii_graphic() || b.is_ascii_whitespace()) {
        return "text".to_string();
    }

    path.extension()
        .and_then(|e| e.to_str())
        .unwrap_or("unknown")
        .to_lowercase()
}

pub fn execute(req: &MediaRequest) -> Result<MediaResult, String> {
    let path = Path::new(&req.path);

    if !path.is_absolute() {
        return Err(format!(
            "path must be absolute for security reasons: '{}'",
            req.path
        ));
    }

    if !path.exists() {
        return Err(format!("file not found: '{}'", req.path));
    }

    let size_bytes = path.metadata().map(|m| m.len()).unwrap_or(0);

    match req.operation {
        MediaOperation::Detect | MediaOperation::Inspect => {
            let format = detect_format(path);
            let extra = if req.operation == MediaOperation::Inspect {
                // Versuche `file --brief` für detailliertere Info
                Command::new("file")
                    .args(["--brief", &req.path])
                    .output()
                    .ok()
                    .map(|out| {
                        let desc = String::from_utf8_lossy(&out.stdout).trim().to_string();
                        json!({ "file_description": desc })
                    })
            } else {
                None
            };

            Ok(MediaResult {
                operation: format!("{:?}", req.operation).to_lowercase(),
                path: req.path.clone(),
                format,
                size_bytes,
                extra,
            })
        }
        MediaOperation::Probe => {
            let output = Command::new("ffprobe")
                .args([
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    &req.path,
                ])
                .output()
                .map_err(|e| format!("ffprobe not available: {e}. Install ffmpeg."))?;

            let probe_json: Value = serde_json::from_slice(&output.stdout)
                .unwrap_or(Value::Null);

            let format = probe_json
                .pointer("/format/format_name")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
                .to_string();

            Ok(MediaResult {
                operation: "probe".to_string(),
                path: req.path.clone(),
                format,
                size_bytes,
                extra: Some(probe_json),
            })
        }
    }
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
    let media_req: MediaRequest = match serde_json::from_value(req.payload) {
        Ok(r) => r,
        Err(e) => {
            write_response(false, Value::Null, &format!("invalid payload: {e}"));
            return;
        }
    };
    match execute(&media_req) {
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
    use std::io::Write as _;

    #[test]
    fn detect_png_by_magic_bytes() {
        let tmp = std::env::temp_dir().join("hm_media_test.png");
        let mut f = std::fs::File::create(&tmp).unwrap();
        f.write_all(b"\x89PNG\r\n\x1A\n").unwrap();
        assert_eq!(detect_format(&tmp), "png");
    }

    #[test]
    fn detect_jpeg_by_magic_bytes() {
        let tmp = std::env::temp_dir().join("hm_media_test.jpg");
        let mut f = std::fs::File::create(&tmp).unwrap();
        f.write_all(b"\xFF\xD8\xFF\xE0").unwrap();
        assert_eq!(detect_format(&tmp), "jpeg");
    }

    #[test]
    fn relative_path_is_rejected() {
        let req = MediaRequest {
            operation: MediaOperation::Detect,
            path: "relative/path.jpg".to_string(),
        };
        assert!(execute(&req).is_err());
    }

    #[test]
    fn nonexistent_file_is_rejected() {
        let req = MediaRequest {
            operation: MediaOperation::Detect,
            path: "/tmp/hm_media_nonexistent_abc123.jpg".to_string(),
        };
        assert!(execute(&req).is_err());
    }
}
