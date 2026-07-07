use std::{collections::HashMap, path::Path, process::Stdio, time::Duration};

use hm_sdk::{PluginRequest, PluginResponse};
use serde::Deserialize;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    process::Command,
    time::timeout,
};

pub const NAME: &str = "plugins";

const PLUGIN_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, Deserialize)]
pub struct PluginManifestEntry {
    pub task_type: String,
    pub command: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
struct PluginManifest {
    #[serde(default)]
    plugins: Vec<PluginManifestEntry>,
}

/// Registry of task-type -> external-process plugins, loaded from a JSON
/// manifest. Each plugin is invoked as a one-shot subprocess: one
/// `PluginRequest` line of JSON on stdin, one `PluginResponse` line of JSON
/// back on stdout.
#[derive(Clone, Default)]
pub struct PluginRegistry {
    by_task_type: HashMap<String, Vec<String>>,
}

impl PluginRegistry {
    pub fn empty() -> Self {
        Self::default()
    }

    /// Loads a manifest from `path`. Returns an empty registry (not an
    /// error) if the file doesn't exist, so plugins are entirely optional.
    pub fn from_manifest_file(path: impl AsRef<Path>) -> anyhow::Result<Self> {
        let path = path.as_ref();
        if !path.exists() {
            return Ok(Self::empty());
        }
        let text = std::fs::read_to_string(path)?;
        let manifest: PluginManifest = serde_json::from_str(&text)?;
        let by_task_type = manifest
            .plugins
            .into_iter()
            .map(|entry| (entry.task_type, entry.command))
            .collect();
        Ok(Self { by_task_type })
    }

    pub fn has(&self, task_type: &str) -> bool {
        self.by_task_type.contains_key(task_type)
    }

    pub async fn invoke(
        &self,
        task_type: &str,
        objective: &str,
        payload: serde_json::Value,
    ) -> anyhow::Result<PluginResponse> {
        let command = self
            .by_task_type
            .get(task_type)
            .ok_or_else(|| anyhow::anyhow!("no plugin registered for task_type '{task_type}'"))?;
        let (program, args) = command
            .split_first()
            .ok_or_else(|| anyhow::anyhow!("plugin command for '{task_type}' is empty"))?;

        let request = PluginRequest {
            task_type: task_type.to_string(),
            objective: objective.to_string(),
            payload,
        };
        let request_line = serde_json::to_string(&request)? + "\n";

        let mut child = Command::new(program)
            .args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| anyhow::anyhow!("failed to spawn plugin '{task_type}': {error}"))?;

        child
            .stdin
            .as_mut()
            .ok_or_else(|| anyhow::anyhow!("plugin '{task_type}' stdin unavailable"))?
            .write_all(request_line.as_bytes())
            .await?;

        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| anyhow::anyhow!("plugin '{task_type}' stdout unavailable"))?;
        let mut lines = BufReader::new(stdout).lines();

        let response_line = timeout(PLUGIN_TIMEOUT, lines.next_line())
            .await
            .map_err(|_| {
                anyhow::anyhow!("plugin '{task_type}' timed out after {PLUGIN_TIMEOUT:?}")
            })??
            .ok_or_else(|| anyhow::anyhow!("plugin '{task_type}' produced no output"))?;

        let _ = child.kill().await;

        serde_json::from_str(&response_line)
            .map_err(|error| anyhow::anyhow!("plugin '{task_type}' returned invalid JSON: {error}"))
    }
}
