//! End-to-end contract test for `POST /tasks`, run against the real gateway
//! binary over a real socket.
//!
//! **Why this file exists.** Every crate in this workspace had tests and every
//! one of them passed while the main dispatch path was dead: the gateway bound
//! the field as `taskType`, `hm-cli` and `hm-cron` sent `task_type`, and
//! `#[serde(default)]` turned the mismatch into an empty string instead of an
//! error. The gateway answered `202 accepted: true` and ran nothing. Unit
//! tests could not see it, because each side was only ever checked against
//! itself -- the defect lived exactly in the gap between them.
//!
//! So this test imports nothing from the gateway. It spawns the compiled
//! binary, writes bytes at a socket and reads bytes back. If the request
//! field, the dispatch wiring or the plugin protocol drifts again, the
//! assertions below fail.
//!
//! The plugin is `/bin/sh` with its body passed as an *argument* rather than a
//! script written to disk and then executed: writing-then-executing races the
//! kernel's file lock and fails intermittently with `Text file busy`, which
//! this repository has already paid for once.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::{Duration, Instant};

const TOKEN: &str = "wire-contract-test-token";

/// Echoes the `PluginRequest` it received back as its result, so the test can
/// assert what the gateway actually handed the plugin -- not merely that
/// something ran.
const PLUGIN_BODY: &str =
    r#"read -r line; printf '{"ok":true,"result":%s,"message":"plugin ran"}\n' "$line""#;

static NEXT_ID: AtomicU32 = AtomicU32::new(0);

struct Gateway {
    child: Child,
    addr: SocketAddr,
    dir: PathBuf,
}

impl Drop for Gateway {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

/// Asks the OS for a free port and immediately releases it. There is a window
/// between release and re-bind, so `start_gateway` retries.
fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .expect("cannot bind an ephemeral port")
        .local_addr()
        .expect("no local addr")
        .port()
}

fn start_gateway() -> Gateway {
    let id = NEXT_ID.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!("hm-gateway-wire-{}-{id}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("create temp dir");

    let manifest = dir.join("plugins.json");
    std::fs::write(
        &manifest,
        serde_json::json!({
            "plugins": [
                { "task_type": "contract-echo", "command": ["/bin/sh", "-c", PLUGIN_BODY] }
            ]
        })
        .to_string(),
    )
    .expect("write manifest");

    let mut last_err = String::from("no attempt made");
    for _ in 0..10 {
        let addr: SocketAddr = format!("127.0.0.1:{}", free_port()).parse().unwrap();
        let mut child = Command::new(env!("CARGO_BIN_EXE_hm-gateway"))
            .env("HM_OWNER_TOKEN", TOKEN)
            .env("HM_GATEWAY_BIND", addr.to_string())
            .env("HM_STORAGE_ROOT", dir.join("storage"))
            .env("HM_PLUGIN_MANIFEST", &manifest)
            // No scheduler in a contract test: cron would submit tasks of its
            // own and make these assertions depend on timing.
            .env("HM_CRON_CONFIG", dir.join("no-such-cron.json"))
            .env("HM_RATE_LIMIT_PER_MINUTE", "0")
            .spawn()
            .expect("cannot spawn hm-gateway");

        let deadline = Instant::now() + Duration::from_secs(20);
        let mut ready = false;
        while Instant::now() < deadline {
            if TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
                ready = true;
                break;
            }
            match child.try_wait() {
                Ok(Some(status)) => {
                    last_err = format!("gateway exited early with {status}");
                    break;
                }
                _ => std::thread::sleep(Duration::from_millis(100)),
            }
        }

        if ready {
            return Gateway { child, addr, dir };
        }
        let _ = child.kill();
        let _ = child.wait();
        if last_err == "no attempt made" {
            last_err = format!("{addr} never accepted a connection");
        }
    }
    let _ = std::fs::remove_dir_all(&dir);
    panic!("gateway never became reachable: {last_err}");
}

/// Deliberately hand-rolled, exactly like every other client of this gateway.
/// A typed helper here would re-introduce the shared assumption the original
/// defect hid behind.
fn post(addr: SocketAddr, path: &str, body: &str, token: &str) -> (u16, String) {
    let mut stream = TcpStream::connect(addr).expect("connect");
    stream
        .set_read_timeout(Some(Duration::from_secs(30)))
        .unwrap();
    let request = format!(
        "POST {path} HTTP/1.0\r\nHost: {host}\r\nAuthorization: Bearer {token}\r\n\
         Content-Type: application/json\r\nContent-Length: {len}\r\n\r\n{body}",
        host = addr.ip(),
        len = body.len(),
    );
    stream.write_all(request.as_bytes()).expect("write");
    let mut response = String::new();
    stream.read_to_string(&mut response).expect("read");

    let status = response
        .split_whitespace()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);
    let body = response
        .find("\r\n\r\n")
        .map(|i| response[i + 4..].to_string())
        .unwrap_or_default();
    (status, body)
}

fn json_of(body: &str) -> serde_json::Value {
    serde_json::from_str(body).unwrap_or_else(|e| panic!("not JSON: {e}\nbody was: {body}"))
}

/// The regression itself: both spellings must reach the plugin. `taskType` is
/// the documented name; `task_type` is what every in-repo caller sent while
/// the gateway silently ignored it.
#[test]
fn both_spellings_reach_the_plugin() {
    let gw = start_gateway();

    for body in [
        r#"{"taskType":"contract-echo","objective":"camel","payload":{"n":1}}"#,
        r#"{"task_type":"contract-echo","objective":"snake","payload":{"n":1}}"#,
    ] {
        let (status, response) = post(gw.addr, "/tasks", body, TOKEN);
        assert_eq!(status, 202, "unexpected status for {body}: {response}");
        let v = json_of(&response);

        assert_eq!(
            v["dispatch"], "plugin_dispatched",
            "task was accepted but never dispatched for {body}: {response}"
        );
        assert_eq!(
            v["task_type"], "contract-echo",
            "gateway recorded the wrong task type for {body}: {response}"
        );
        // What the plugin actually received -- the far side of the boundary.
        assert_eq!(
            v["plugin_result"]["result"]["task_type"], "contract-echo",
            "the plugin did not receive the task type for {body}: {response}"
        );
        assert_eq!(v["plugin_result"]["result"]["payload"]["n"], 1);
        assert_eq!(v["plugin_result"]["ok"], true);
    }
}

/// A task that matches no plugin must say so. Previously this was expressed
/// only by the *absence* of `plugin_result` -- a caller had to know to look
/// for a field that isn't there, and none of them did.
#[test]
fn an_unhandled_task_says_so_explicitly() {
    let gw = start_gateway();
    let (status, response) = post(gw.addr, "/tasks", r#"{"taskType":"no-such-plugin"}"#, TOKEN);
    assert_eq!(status, 202, "{response}");
    let v = json_of(&response);
    assert_eq!(v["dispatch"], "unhandled", "{response}");
    assert!(
        v["dispatch_reason"]
            .as_str()
            .unwrap_or_default()
            .contains("no-such-plugin"),
        "the reason must name the task type: {response}"
    );
    assert!(v["plugin_result"].is_null(), "{response}");
}

/// A submission with no type can never match a plugin, so accepting it would
/// promise work that provably will not happen. It used to be recorded as
/// "unspecified" and answered `202 accepted: true`, which is precisely how the
/// field-name mismatch stayed invisible for so long.
#[test]
fn a_task_without_a_type_is_rejected() {
    let gw = start_gateway();
    for body in [r#"{"payload":{}}"#, r#"{"taskType":"   "}"#] {
        let (status, response) = post(gw.addr, "/tasks", body, TOKEN);
        assert_eq!(status, 400, "must not accept {body}: {response}");
        let v = json_of(&response);
        assert_eq!(v["accepted"], false, "{response}");
    }
}

/// The contract route is not a hole in the auth model.
#[test]
fn the_task_route_still_requires_the_owner_token() {
    let gw = start_gateway();
    let (status, response) = post(
        gw.addr,
        "/tasks",
        r#"{"taskType":"contract-echo"}"#,
        "wrong-token",
    );
    assert_eq!(status, 401, "{response}");
}
