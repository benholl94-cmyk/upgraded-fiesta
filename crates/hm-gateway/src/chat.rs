//! Streaming chat surface -- the one port through which the system is commanded.
//!
//! # Why this cannot go through the plugin protocol
//!
//! `hm-plugins` writes one JSON line to a child and reads one back with a 5 s
//! timeout. A local 12B model answers in minutes and must be visible while it
//! works. Forcing chat through that protocol would mean either raising the
//! timeout for *every* plugin (removing a real safety bound) or showing the
//! operator a hung socket. So chat gets its own path -- and, unlike the plugin
//! path, it never buffers: each line the brain emits is on the wire before the
//! next one is computed.
//!
//! # Why no `Content-Length`, and why not chunked
//!
//! The length is unknown when the headers go out. HTTP/1.1 chunked encoding
//! would work, but this is a hand-rolled server and every framing layer is
//! another thing to get subtly wrong. `Connection: close` plus EOF-delimited
//! body is the same contract with nothing to encode -- and it is exactly what
//! `fetch()` + `ReadableStream` consumes in a browser.
//!
//! # Why not EventSource on the client
//!
//! `EventSource` cannot set an `Authorization` header. Every route here is
//! bearer-gated, so a client using it would have to move the owner token into
//! the query string, where it lands in logs and history. The body format is
//! still SSE (`data: ...\n\n`) so it stays readable with `curl`, but the
//! browser side must use `fetch`.
//!
//! # Trust boundary
//!
//! The request body chooses; it never constructs. `line` is passed as a single
//! `argv` element to a fixed program, with no shell anywhere in the path
//! (`tokio::process::Command` does not use one). Context file arguments are
//! rejected unless they are plain relative paths -- an entry starting with `-`
//! would otherwise become an option to the brain rather than an argument.

use serde::Deserialize;
use std::path::Path;
use std::process::Stdio;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;
use tokio::process::Command;

/// A chat turn takes as long as the model takes. This bound exists so a wedged
/// child cannot hold a connection (and a rate-limiter slot) forever.
const TURN_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(1800);

const MAX_LINE_BYTES: usize = 32_768;
const MAX_FILES: usize = 16;

#[derive(Debug, Deserialize, Default)]
pub struct ChatInput {
    #[serde(default)]
    pub line: String,
    #[serde(default)]
    pub files: Vec<String>,
}

/// Rejects anything that would turn a context path into an option or escape
/// the repository. Returns the reason, so the client learns what was wrong
/// instead of silently getting fewer files than it asked for.
fn check_file(arg: &str) -> Result<(), String> {
    if arg.is_empty() {
        return Err("empty file argument".into());
    }
    if arg.starts_with('-') {
        return Err(format!("{arg:?} would be read as an option, not a path"));
    }
    if arg.contains('\0') || arg.contains('\n') {
        return Err("file argument contains a control character".into());
    }
    let p = Path::new(arg);
    if p.is_absolute() || p.components().any(|c| c.as_os_str() == "..") {
        return Err(format!("{arg:?} must be a relative path inside the repo"));
    }
    Ok(())
}

pub fn validate(input: &ChatInput) -> Result<(), String> {
    if input.line.trim().is_empty() {
        return Err("line must not be empty".into());
    }
    if input.line.len() > MAX_LINE_BYTES {
        return Err(format!("line exceeds {MAX_LINE_BYTES} bytes"));
    }
    if input.files.len() > MAX_FILES {
        return Err(format!("at most {MAX_FILES} context files"));
    }
    for f in &input.files {
        check_file(f)?;
    }
    Ok(())
}

pub fn sse_headers(origin_header: &str) -> String {
    format!(
        "HTTP/1.1 200 OK\r\n\
         Content-Type: text/event-stream; charset=utf-8\r\n\
         Cache-Control: no-cache, no-transform\r\n\
         X-Accel-Buffering: no\r\n\
         Connection: close\r\n{origin_header}\r\n"
    )
}

/// One NDJSON line from the brain becomes one SSE event. The gateway does not
/// parse it: the event vocabulary belongs to `agents/brain.py`, and a gateway
/// that understood it would have to be changed every time a new event type
/// appears.
pub fn sse_event(line: &str) -> String {
    format!("data: {line}\n\n")
}

pub fn sse_error(reason: &str) -> String {
    let payload = serde_json::json!({ "typ": "fehler", "text": reason });
    sse_event(&payload.to_string())
}

/// Streams a chat turn. Errors after the headers are sent are reported *in*
/// the stream, because the status code is already gone -- a silently truncated
/// body would look like a finished answer.
pub async fn stream_chat(
    stream: &mut TcpStream,
    input: ChatInput,
    origin_header: String,
    repo: &Path,
    python: &str,
) -> std::io::Result<()> {
    stream
        .write_all(sse_headers(&origin_header).as_bytes())
        .await?;
    stream.flush().await?;

    let mut cmd = Command::new(python);
    cmd.arg("-m")
        .arg("agents.brain")
        .arg("--json")
        .arg(&input.line);
    for f in &input.files {
        cmd.arg("--file").arg(f);
    }
    cmd.current_dir(repo)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);

    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            stream
                .write_all(sse_error(&format!("brain not startable: {e}")).as_bytes())
                .await?;
            stream.flush().await?;
            return Ok(());
        }
    };

    let stdout = child.stdout.take().expect("stdout piped above");
    let mut lines = BufReader::new(stdout).lines();

    let pump = async {
        while let Some(line) = lines.next_line().await? {
            if line.trim().is_empty() {
                continue;
            }
            stream.write_all(sse_event(&line).as_bytes()).await?;
            // Flush per line: buffering here would defeat the entire point and
            // the operator would see one burst at the end.
            stream.flush().await?;
        }
        Ok::<(), std::io::Error>(())
    };

    match tokio::time::timeout(TURN_TIMEOUT, pump).await {
        Ok(Ok(())) => {}
        Ok(Err(_)) => {
            // The client hung up. Killing the child is the point of
            // kill_on_drop; nothing to report to a socket that is gone.
            let _ = child.start_kill();
            return Ok(());
        }
        Err(_) => {
            let _ = child.start_kill();
            let _ = stream
                .write_all(sse_error("turn timed out after 1800s").as_bytes())
                .await;
        }
    }

    let _ = child.wait().await;
    stream.write_all(b"data: [DONE]\n\n").await?;
    stream.flush().await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_an_option_disguised_as_a_file() {
        // The concrete hazard: "--file" then "--json" would silently change
        // how the brain runs rather than adding context.
        assert!(check_file("--json").is_err());
        assert!(check_file("-rf").is_err());
    }

    #[test]
    fn rejects_paths_that_leave_the_repo() {
        assert!(check_file("/etc/passwd").is_err());
        assert!(check_file("../../etc/passwd").is_err());
        assert!(check_file("a/../../b").is_err());
    }

    #[test]
    fn accepts_a_plain_relative_path() {
        assert!(check_file("crates/hm-gateway/src/main.rs").is_ok());
    }

    #[test]
    fn rejects_empty_and_oversized_lines() {
        assert!(validate(&ChatInput {
            line: "  ".into(),
            files: vec![]
        })
        .is_err());
        assert!(validate(&ChatInput {
            line: "x".repeat(MAX_LINE_BYTES + 1),
            files: vec![]
        })
        .is_err());
        assert!(validate(&ChatInput {
            line: "/status".into(),
            files: vec![]
        })
        .is_ok());
    }

    #[test]
    fn rejects_too_many_files() {
        let files = (0..MAX_FILES + 1).map(|i| format!("f{i}.rs")).collect();
        assert!(validate(&ChatInput {
            line: "hi".into(),
            files
        })
        .is_err());
    }

    #[test]
    fn one_ndjson_line_becomes_one_sse_event() {
        let ev = sse_event(r#"{"typ":"token","text":"a"}"#);
        assert!(ev.starts_with("data: "));
        assert!(ev.ends_with("\n\n"));
        assert_eq!(ev.matches("data: ").count(), 1);
    }

    #[test]
    fn headers_disable_proxy_buffering_and_keepalive() {
        // Both are load-bearing: a buffering proxy or a kept-alive connection
        // turns the stream back into a single delayed response.
        let h = sse_headers("");
        assert!(h.contains("text/event-stream"));
        assert!(h.contains("X-Accel-Buffering: no"));
        assert!(h.contains("Connection: close"));
        assert!(!h.to_lowercase().contains("content-length"));
    }
}
