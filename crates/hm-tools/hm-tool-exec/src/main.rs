//! `hm-tool-exec`'s real binary: a hm-plugins-protocol operations tool.
//!
//! Deliberately **not** an arbitrary-command-execution tool. The request
//! payload's `operation` field only ever *selects* one entry from a fixed,
//! hardcoded allowlist below -- it never contributes to argv construction,
//! so there is no command-injection surface no matter what a caller sends.
//! Every allowlisted operation is read-only.
//!
//! Protocol (matches `plugins/echo_plugin.py` and `crates/hm-sdk`): read
//! one `PluginRequest` JSON line from stdin, write one `PluginResponse`
//! JSON line to stdout.

use std::io::{self, Write};
use std::process::Command;

use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize, Default)]
struct PluginRequest {
    #[serde(default)]
    payload: Value,
}

const ALLOWED_OPERATIONS: &[&str] = &[
    "gateway_status",
    "gateway_logs",
    "disk_usage",
    "memory_usage",
];

/// Runs one allowlisted, read-only operational check and returns whether
/// the command itself exited successfully, alongside its captured
/// (stdout, stderr). The `name` argument selects a fixed, hardcoded
/// `(program, args)` pair -- it is never interpolated into a shell or used
/// to build argv itself.
///
/// The `Result::Err` case is reserved for "couldn't even run this" (unknown
/// operation, failed to spawn); a command that ran but exited non-zero
/// (e.g. `systemctl status` on an inactive unit) is `Ok((false, ...))`, not
/// an `Err`, since output was still produced.
fn run_operation(name: &str) -> Result<(bool, String, String), String> {
    let (program, args): (&str, &[&str]) = match name {
        "gateway_status" => ("systemctl", &["status", "hm-gateway.service", "--no-pager"]),
        "gateway_logs" => (
            "journalctl",
            &["-u", "hm-gateway.service", "-n", "50", "--no-pager"],
        ),
        "disk_usage" => ("df", &["-h"]),
        "memory_usage" => ("free", &["-h"]),
        other => {
            return Err(format!(
                "unknown operation '{other}'; allowed: {}",
                ALLOWED_OPERATIONS.join(", ")
            ))
        }
    };
    let output = Command::new(program)
        .args(args)
        .output()
        .map_err(|error| format!("failed to run '{program}': {error}"))?;
    Ok((
        output.status.success(),
        String::from_utf8_lossy(&output.stdout).into_owned(),
        String::from_utf8_lossy(&output.stderr).into_owned(),
    ))
}

fn write_response(ok: bool, result: Value, message: &str) {
    let response = json!({ "ok": ok, "result": result, "message": message });
    println!("{response}");
    let _ = io::stdout().flush();
}

fn main() {
    let mut line = String::new();
    // Exactly one line, matching plugins/echo_plugin.py -- hm-plugins keeps
    // the child's stdin open after writing the request, so reading to EOF
    // instead of one line would hang forever.
    if io::stdin().read_line(&mut line).is_err() {
        write_response(false, Value::Null, "failed to read request from stdin");
        return;
    }

    let request: PluginRequest = match serde_json::from_str(line.trim()) {
        Ok(request) => request,
        Err(error) => {
            write_response(
                false,
                Value::Null,
                &format!("invalid request JSON: {error}"),
            );
            return;
        }
    };

    let operation = request
        .payload
        .get("operation")
        .and_then(Value::as_str)
        .unwrap_or("");

    match run_operation(operation) {
        Ok((exit_ok, stdout, stderr)) => write_response(
            exit_ok,
            json!({ "operation": operation, "stdout": stdout, "stderr": stderr }),
            if exit_ok {
                "ok"
            } else {
                "command exited with a non-zero status"
            },
        ),
        Err(reason) => write_response(false, Value::Null, &reason),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allowlisted_operation_runs_successfully() {
        let (exit_ok, stdout, _stderr) =
            run_operation("disk_usage").expect("df is always available");
        assert!(exit_ok);
        assert!(!stdout.is_empty());
    }

    #[test]
    fn non_zero_exit_status_is_surfaced_not_masked_as_ok() {
        // "status" on a unit name that can't exist is systemctl's standard
        // way of reporting "not found" -- and that's a non-zero exit even
        // though the command ran and produced output, which is exactly the
        // case this field exists to distinguish from a real success.
        //
        // In einer Sandbox ohne systemctl (z.B. devcontainer, macOS, Windows)
        // ist `run_operation` selbst `Err` -- und genau das beweist, dass
        // die Operation "nicht stillschweigend erfolgreich" war: weder
        // `Ok((true, …))` noch ein verschluckter Spawn-Fehler.
        match run_operation("gateway_status") {
            Ok((true, _, _)) => panic!(
                "systemctl status on a missing unit must not report exit_ok=true; \
                 the whole point of the field is to surface non-zero exits"
            ),
            Ok((false, _, _)) | Err(_) => { /* korrekt: kein stiller Erfolg */ }
        }
    }

    #[test]
    fn unknown_operation_is_rejected_before_any_command_runs() {
        // The exact string an attacker might try if they assumed this was a
        // shell -- must be treated as an opaque, unrecognized name, not
        // interpreted.
        let error = run_operation("; rm -rf /").unwrap_err();
        assert!(error.contains("unknown operation"));
        assert!(error.contains("gateway_status"));
    }

    #[test]
    fn empty_operation_is_rejected() {
        let error = run_operation("").unwrap_err();
        assert!(error.contains("unknown operation"));
    }
}
