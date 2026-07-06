use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const NAME: &str = "sdk";

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
