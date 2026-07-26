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

        // Ein Plugin, das seine Eingabe gar nicht liest (oder sofort endet),
        // schliesst stdin -- der Schreibvorgang scheitert dann mit EPIPE.
        // Das ist KEIN Protokollfehler, sondern eine Aussage ueber das Plugin,
        // und es wird gleich darunter praeziser gemeldet: entweder liefert es
        // trotzdem eine gueltige Antwort, oder der stdout-Pfad meldet
        // "produced no output".
        //
        // Vorher wurde EPIPE durchgereicht. Weil es ein Wettlauf zwischen
        // Schreiben und Prozessende ist, bekam derselbe Aufruf mal
        // "Broken pipe (os error 32)" und mal "produced no output" -- eine
        // Fehlermeldung, die vom Scheduler abhing. Sichtbar wurde das erst,
        // als dieses Crate ueberhaupt Tests bekam.
        let stdin_result = child
            .stdin
            .as_mut()
            .ok_or_else(|| anyhow::anyhow!("plugin '{task_type}' stdin unavailable"))?
            .write_all(request_line.as_bytes())
            .await;
        match stdin_result {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::BrokenPipe => {}
            Err(e) => {
                return Err(anyhow::anyhow!(
                    "plugin '{task_type}' stdin write failed: {e}"
                ))
            }
        }
        // stdin schliessen, damit ein Plugin, das bis EOF liest, nicht wartet.
        drop(child.stdin.take());

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

#[cfg(test)]
mod tests {
    use super::*;
    /// Ein Plugin als Argument an `/bin/sh`, nicht als frisch geschriebene
    /// Datei.
    ///
    /// Die erste Fassung legte pro Test ein `*.sh` an, machte es ausfuehrbar
    /// und liess es ausfuehren. Das war in etwa jedem zehnten Lauf rot mit
    /// `Text file busy (os error 26)` — der klassische fork/exec-Wettlauf:
    /// waehrend ein Thread die Datei noch zum Schreiben offen hat, forkt ein
    /// anderer, das Kind erbt dieses Schreib-Handle, und `execve` auf genau
    /// diese Datei verweigert der Kernel dann.
    ///
    /// Ein `sleep` oder ein Mutex haetten das Fenster verkleinert. Hier gibt
    /// es keines mehr: ausgefuehrt wird `/bin/sh`, das niemand schreibt, und
    /// das Plugin ist ein Argument. Ein Wackeltest, der "meistens" gruen ist,
    /// bringt weniger als keiner — er bringt anderen bei, rote Laeufe zu
    /// ignorieren.
    fn plugin(body: &str) -> Vec<String> {
        vec!["/bin/sh".into(), "-c".into(), body.into()]
    }

    fn registry(task_type: &str, command: Vec<String>) -> PluginRegistry {
        let mut by_task_type = HashMap::new();
        by_task_type.insert(task_type.to_string(), command);
        PluginRegistry { by_task_type }
    }

    #[tokio::test]
    async fn a_well_formed_plugin_round_trips() {
        let cmd = plugin(r#"read -r line; echo '{"ok":true,"result":"pong"}'"#);
        let reg = registry("ping", cmd);
        let r = reg
            .invoke("ping", "obj", serde_json::json!({"a": 1}))
            .await
            .expect("round trip");
        assert!(r.ok);
        assert_eq!(r.result, serde_json::json!("pong"));
    }

    #[tokio::test]
    async fn the_request_actually_reaches_the_plugin_stdin() {
        // Without this the protocol could be write-only and every test above
        // would still pass -- the plugin would just ignore its input.
        let cmd = plugin(
            r#"read -r line; printf '{"ok":true,"message":%s}\n' "$(printf '%s' "$line" | sed 's/"/\\"/g; s/^/"/; s/$/"/')""#,
        );
        let reg = registry("mirror", cmd);
        let r = reg
            .invoke(
                "mirror",
                "das ziel",
                serde_json::json!({"schluessel": "wert"}),
            )
            .await
            .unwrap();
        let seen = r.message;
        assert!(
            seen.contains("das ziel"),
            "objective did not reach the plugin: {seen}"
        );
        assert!(
            seen.contains("schluessel"),
            "payload did not reach the plugin: {seen}"
        );
        assert!(
            seen.contains("mirror"),
            "task_type did not reach the plugin: {seen}"
        );
    }

    #[tokio::test]
    async fn a_hanging_plugin_is_cut_off_rather_than_waited_on() {
        // The 5 s bound is the reason chat cannot use this path at all. If it
        // silently stopped applying, that whole design decision would be
        // based on a property the code no longer has.
        let cmd = plugin("sleep 30");
        let reg = registry("haengt", cmd);
        let started = std::time::Instant::now();
        let err = reg
            .invoke("haengt", "", serde_json::Value::Null)
            .await
            .unwrap_err();
        assert!(err.to_string().contains("timed out"), "wrong error: {err}");
        assert!(
            started.elapsed() < PLUGIN_TIMEOUT + Duration::from_secs(3),
            "waited {:?}, bound is {PLUGIN_TIMEOUT:?}",
            started.elapsed()
        );
    }

    #[tokio::test]
    async fn a_plugin_that_ignores_its_input_still_gets_its_answer_read() {
        // Gegentest zur EPIPE-Toleranz oben: das Plugin liest stdin nie,
        // antwortet aber gueltig. Frueher entschied der Scheduler, ob das
        // "Broken pipe" oder ein Ergebnis wurde.
        let reg = registry("taub", plugin(r#"echo '{"ok":true,"result":"trotzdem"}'"#));
        let r = reg
            .invoke("taub", "", serde_json::Value::Null)
            .await
            .expect("EPIPE beim Schreiben darf die Antwort nicht verwerfen");
        assert!(r.ok);
        assert_eq!(r.result, serde_json::json!("trotzdem"));
    }

    #[tokio::test]
    async fn garbage_output_is_an_error_not_a_silent_success() {
        let cmd = plugin(r#"read -r line; echo 'nicht json'"#);
        let reg = registry("muell", cmd);
        let err = reg
            .invoke("muell", "", serde_json::Value::Null)
            .await
            .unwrap_err();
        assert!(
            err.to_string().contains("invalid JSON"),
            "wrong error: {err}"
        );
    }

    #[tokio::test]
    async fn a_plugin_that_says_nothing_is_an_error() {
        let cmd = plugin("exit 0");
        let reg = registry("stumm", cmd);
        let err = reg
            .invoke("stumm", "", serde_json::Value::Null)
            .await
            .unwrap_err();
        assert!(err.to_string().contains("no output"), "wrong error: {err}");
    }

    #[tokio::test]
    async fn an_unregistered_task_type_names_itself_in_the_error() {
        let reg = PluginRegistry::empty();
        let err = reg
            .invoke("gibtsnicht", "", serde_json::Value::Null)
            .await
            .unwrap_err();
        assert!(
            err.to_string().contains("gibtsnicht"),
            "unhelpful error: {err}"
        );
    }

    #[tokio::test]
    async fn a_missing_binary_is_reported_not_hidden() {
        let reg = registry("weg", vec!["/nicht/vorhanden/xyz".into()]);
        let err = reg
            .invoke("weg", "", serde_json::Value::Null)
            .await
            .unwrap_err();
        assert!(
            err.to_string().contains("failed to spawn"),
            "wrong error: {err}"
        );
    }

    #[test]
    fn a_missing_manifest_is_an_empty_registry_not_a_failure() {
        // Plugins are optional; a gateway must start without them.
        let reg = PluginRegistry::from_manifest_file("/nicht/vorhanden/plugins.json").unwrap();
        assert!(!reg.has("echo"));
    }

    #[test]
    fn a_corrupt_manifest_fails_loudly() {
        let dir = std::env::temp_dir();
        let p = dir.join(format!("hm-plugins-kaputt-{}.json", std::process::id()));
        std::fs::write(&p, "{ das ist kein json").unwrap();
        assert!(PluginRegistry::from_manifest_file(&p).is_err());
    }

    #[test]
    fn the_repos_own_manifest_parses_and_registers_its_task_types() {
        // Recomputed, not assumed: config/plugins.json is what the running
        // gateway loads, so a typo there is a production defect.
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config/plugins.json");
        let reg = PluginRegistry::from_manifest_file(&root).unwrap();
        assert!(reg.has("echo"), "echo plugin not registered");
        assert!(reg.has("ops-tool"), "ops-tool not registered");
    }
}
