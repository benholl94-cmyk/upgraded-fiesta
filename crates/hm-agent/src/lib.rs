use std::sync::Arc;

use hm_memory::MemoryStore;
use hm_plugins::PluginRegistry;
use serde::Serialize;
use serde_json::Value;

pub fn component_name() -> &'static str {
    "hm-agent"
}

/// What happened when the agent tried to carry out a task.
#[derive(Debug, Clone, Serialize)]
pub enum TaskOutcome {
    /// A registered plugin ran; carries its response verbatim.
    PluginDispatched {
        ok: bool,
        result: Value,
        message: String,
    },
    /// No plugin is registered for this task_type -- nothing was executed.
    Unhandled { reason: String },
}

/// Minimal orchestration layer between the gateway's task intake and the
/// rest of the system: routes a task to a plugin (via [`PluginRegistry`])
/// if one is registered for its `task_type`, and records a durable,
/// recallable summary of the outcome to [`MemoryStore`]. This is the
/// `Agent Runtime -> Memory` link in the intended
/// `Gateway -> Agent Runtime -> Memory -> ...` chain (see
/// `docs/architecture.md`) -- before this crate did anything, task
/// dispatch and memory were entirely disconnected from each other.
pub struct Agent {
    plugins: Arc<PluginRegistry>,
    memory: Arc<MemoryStore>,
}

impl Agent {
    pub fn new(plugins: Arc<PluginRegistry>, memory: Arc<MemoryStore>) -> Self {
        Self { plugins, memory }
    }

    /// Dispatches `task_type` to its registered plugin, if any, then
    /// records a one-line summary of the outcome to memory. Never panics
    /// or propagates a plugin failure as an `Err` -- a failing plugin is a
    /// normal, representable outcome (`ok: false`), not a caller-facing
    /// error.
    pub async fn dispatch(&self, task_type: &str, objective: &str, payload: Value) -> TaskOutcome {
        let outcome = if !self.plugins.has(task_type) {
            TaskOutcome::Unhandled {
                reason: format!("no plugin registered for task_type '{task_type}'"),
            }
        } else {
            match self.plugins.invoke(task_type, objective, payload).await {
                Ok(response) => TaskOutcome::PluginDispatched {
                    ok: response.ok,
                    result: response.result,
                    message: response.message,
                },
                Err(error) => TaskOutcome::PluginDispatched {
                    ok: false,
                    result: Value::Null,
                    message: error.to_string(),
                },
            }
        };
        self.record(task_type, objective, &outcome).await;
        outcome
    }

    async fn record(&self, task_type: &str, objective: &str, outcome: &TaskOutcome) {
        let summary = match outcome {
            TaskOutcome::PluginDispatched { ok, message, .. } => {
                format!("task '{task_type}' ({objective}) dispatched: ok={ok} message={message}")
            }
            TaskOutcome::Unhandled { reason } => {
                format!("task '{task_type}' ({objective}) unhandled: {reason}")
            }
        };
        // Best-effort: a memory write failure shouldn't fail task dispatch,
        // but it must not vanish silently either -- a persistently failing
        // memory backend (e.g. a storage permission issue) should be
        // observable, not just an empty GET /memory nobody can explain.
        if let Err(error) = self.memory.remember(summary).await {
            eprintln!("hm-agent: failed to record task outcome to memory: {error}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use hm_storage::{FileStorage, LocalFsStorage};
    use serde_json::json;
    use std::path::PathBuf;
    use uuid::Uuid;

    struct TempDir(PathBuf);
    impl TempDir {
        fn new() -> Self {
            Self(std::env::temp_dir().join(format!("hm-agent-test-{}", Uuid::new_v4())))
        }
    }
    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    async fn agent_with_manifest(manifest_json: &str, dir: &TempDir) -> Agent {
        std::fs::create_dir_all(&dir.0).unwrap();
        let manifest_path = dir.0.join("plugins.json");
        std::fs::write(&manifest_path, manifest_json).unwrap();
        let plugins = Arc::new(PluginRegistry::from_manifest_file(&manifest_path).unwrap());

        let storage: Arc<dyn FileStorage> = Arc::new(LocalFsStorage::new(dir.0.clone()));
        let memory = Arc::new(MemoryStore::load(storage, "memory.json").await.unwrap());

        Agent::new(plugins, memory)
    }

    #[tokio::test]
    async fn unregistered_task_type_is_unhandled_and_recorded() {
        let dir = TempDir::new();
        let agent = agent_with_manifest(r#"{"plugins":[]}"#, &dir).await;

        let outcome = agent.dispatch("nonexistent", "do a thing", json!({})).await;
        match outcome {
            TaskOutcome::Unhandled { reason } => assert!(reason.contains("nonexistent")),
            other => panic!("expected Unhandled, got {other:?}"),
        }

        let records = agent.memory.list().await;
        assert_eq!(records.len(), 1);
        assert!(records[0].text.contains("unhandled"));
    }

    #[tokio::test]
    async fn registered_plugin_is_invoked_and_recorded() {
        let dir = TempDir::new();
        // `cat` echoes its stdin JSON straight back as the "response" line,
        // which is not valid PluginResponse JSON -- this exercises the
        // dispatch-and-record path deterministically without depending on
        // Python being on PATH in the test environment.
        let manifest = r#"{"plugins":[{"task_type":"echo-ish","command":["cat"]}]}"#;
        let agent = agent_with_manifest(manifest, &dir).await;

        let outcome = agent.dispatch("echo-ish", "say hi", json!({"n": 1})).await;
        match outcome {
            TaskOutcome::PluginDispatched { ok, .. } => assert!(!ok),
            other => panic!("expected PluginDispatched, got {other:?}"),
        }

        let records = agent.memory.list().await;
        assert_eq!(records.len(), 1);
        assert!(records[0].text.contains("echo-ish"));
    }
}
