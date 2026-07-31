use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const NAME: &str = "sdk";

/// Optionaler HTTPS-Client (siehe `tls` Modul). Aktiviert durch das
/// Cargo-Feature `tls`; ohne das Feature liefern `post`/`get` einen klaren
/// Fehler statt lautlos HTTP-auf-HTTPS zu mischen.
pub mod tls;

/// One request, written as a single line of JSON to a plugin process's stdin.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PluginRequest {
    pub task_type: String,
    pub objective: String,
    #[serde(default)]
    pub payload: Value,
}

/// One response, read as a single line of JSON from a plugin process's stdout.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PluginResponse {
    pub ok: bool,
    #[serde(default)]
    pub result: Value,
    #[serde(default)]
    pub message: String,
}

/// One task submission, as sent to the gateway's `POST /tasks`.
///
/// It lives here, next to the plugin protocol, because it is the *other* wire
/// this system speaks, and because keeping it in one place is the only thing
/// that actually prevents the failure it was extracted from.
///
/// The gateway bound this field as `taskType` while `hm-cli`, `hm-cron` and
/// all four channel crates sent `task_type`. With `#[serde(default)]` that
/// mismatch produced an empty string rather than an error, so the gateway
/// answered `202 accepted: true` and dispatched to no plugin at all. Every
/// component was tested, every test was green, and the main dispatch path was
/// dead -- because each side was only ever checked against itself.
///
/// A shared type makes the two sides the same declaration rather than two
/// declarations that happen to agree. The `task_type` alias stays for clients
/// outside this workspace, which a repo-wide rename cannot reach.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskSubmission {
    #[serde(default, rename = "taskType", alias = "task_type")]
    pub task_type: String,
    #[serde(default)]
    pub objective: String,
    #[serde(default)]
    pub payload: Value,
}

impl TaskSubmission {
    pub fn new(task_type: impl Into<String>, objective: impl Into<String>, payload: Value) -> Self {
        Self {
            task_type: task_type.into(),
            objective: objective.into(),
            payload,
        }
    }

    /// A submission with no type can never match a plugin, so the gateway
    /// rejects it instead of accepting work it will not do.
    pub fn is_dispatchable(&self) -> bool {
        !self.task_type.trim().is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// The documented spelling. If this ever stops holding, every caller in
    /// the workspace is silently dispatching nothing again.
    #[test]
    fn serializes_task_type_as_camel_case() {
        let body = serde_json::to_string(&TaskSubmission::new("echo", "", json!({}))).unwrap();
        assert!(
            body.contains("\"taskType\":\"echo\""),
            "wire body must use camelCase taskType, got: {body}"
        );
        assert!(
            !body.contains("\"task_type\""),
            "wire body must not emit snake_case, got: {body}"
        );
    }

    /// The counter-test that the original bug needed and did not have: a body
    /// in the *wrong* spelling must still arrive as a real task type, not as
    /// an empty string that later reads as "unspecified".
    #[test]
    fn accepts_both_spellings_on_the_wire() {
        for body in [
            r#"{"taskType":"echo","payload":{}}"#,
            r#"{"task_type":"echo","payload":{}}"#,
        ] {
            let parsed: TaskSubmission = serde_json::from_str(body).unwrap();
            assert_eq!(parsed.task_type, "echo", "failed to bind from: {body}");
            assert!(parsed.is_dispatchable());
        }
    }

    #[test]
    fn a_body_without_any_type_is_not_dispatchable() {
        let parsed: TaskSubmission = serde_json::from_str(r#"{"payload":{}}"#).unwrap();
        assert!(parsed.task_type.is_empty());
        assert!(!parsed.is_dispatchable());

        let blank: TaskSubmission = serde_json::from_str(r#"{"taskType":"   "}"#).unwrap();
        assert!(!blank.is_dispatchable());
    }

    /// A payload round-trips untouched -- the plugin sees what the caller sent.
    #[test]
    fn payload_and_objective_survive_the_round_trip() {
        let original = TaskSubmission::new(
            "ops-tool",
            "check disk",
            json!({"operation": "disk_usage", "nested": {"n": 1}}),
        );
        let back: TaskSubmission =
            serde_json::from_str(&serde_json::to_string(&original).unwrap()).unwrap();
        assert_eq!(back.task_type, "ops-tool");
        assert_eq!(back.objective, "check disk");
        assert_eq!(back.payload["operation"], "disk_usage");
        assert_eq!(back.payload["nested"]["n"], 1);
    }
}
