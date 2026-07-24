//! `hm-cron` — Einfacher Cron-Runner für hm-gateway.
//!
//! Liest Job-Definitionen aus `HM_CRON_CONFIG` (Standard: `config/cron.json`)
//! und reiht fällige Jobs per HTTP-POST an `HM_GATEWAY_URL/tasks` ein.
//! Unterstützt einfache Intervalle in Sekunden (kein voll POSIX-Cron-Parser).

pub const NAME: &str = "cron";

use serde::{Deserialize, Serialize};
use std::time::{Duration, Instant};

/// Eine einzelne Cron-Job-Definition aus `config/cron.json`.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CronJob {
    /// Eindeutiger Name des Jobs.
    pub name: String,
    /// Task-Typ der an `/tasks` gesendet wird (muss in `config/plugins.json` registriert sein).
    pub task_type: String,
    /// Payload-JSON (wird unverändert an das Gateway weitergeleitet).
    #[serde(default)]
    pub payload: serde_json::Value,
    /// Ausführungsintervall in Sekunden.
    pub interval_secs: u64,
}

/// Laufzeitstatus eines einzelnen Jobs (wann er zuletzt ausgeführt wurde).
#[derive(Debug)]
struct JobState {
    job: CronJob,
    last_run: Option<Instant>,
}

impl JobState {
    fn is_due(&self) -> bool {
        match self.last_run {
            None => true,
            Some(t) => t.elapsed() >= Duration::from_secs(self.job.interval_secs),
        }
    }
}

/// Schickt einen Task per HTTP-POST an das Gateway.
///
/// Verwendet eine raw TCP-Verbindung ohne externe HTTP-Bibliothek,
/// konsistent mit dem Rest des Workspace.
fn submit_task(gateway_url: &str, token: &str, job: &CronJob) -> Result<(), anyhow::Error> {
    use std::io::{Read, Write};
    use std::net::TcpStream;

    let url = gateway_url.trim_start_matches("http://");
    let (host, port_str) = url.rsplit_once(':').unwrap_or((url, "8080"));
    let port: u16 = port_str.parse().unwrap_or(8080);

    let body = serde_json::json!({
        "task_type": job.task_type,
        "payload": job.payload,
    })
    .to_string();

    let request = format!(
        "POST /tasks HTTP/1.0\r\n\
         Host: {host}\r\n\
         Authorization: Bearer {token}\r\n\
         Content-Type: application/json\r\n\
         Content-Length: {len}\r\n\
         \r\n{body}",
        len = body.len()
    );

    let addr = format!("{host}:{port}");
    let mut stream = TcpStream::connect(&addr)?;
    stream.write_all(request.as_bytes())?;

    let mut response = String::new();
    stream.read_to_string(&mut response)?;
    Ok(())
}

/// Liest die Job-Konfiguration aus einer JSON-Datei.
pub fn load_jobs(config_path: &str) -> Result<Vec<CronJob>, anyhow::Error> {
    let content = std::fs::read_to_string(config_path)?;
    let jobs: Vec<CronJob> = serde_json::from_str(&content)?;
    Ok(jobs)
}

/// Startet den Cron-Runner in einer Tokio-Task.
///
/// Prüft jede Sekunde ob ein Job fällig ist und reiht ihn dann im Gateway ein.
/// Läuft bis `shutdown` gedropt wird.
pub async fn run(
    jobs: Vec<CronJob>,
    gateway_url: String,
    token: String,
    mut shutdown: tokio::sync::watch::Receiver<bool>,
) {
    let mut states: Vec<JobState> = jobs
        .into_iter()
        .map(|job| JobState {
            job,
            last_run: None,
        })
        .collect();

    let mut interval = tokio::time::interval(Duration::from_secs(1));

    loop {
        tokio::select! {
            _ = interval.tick() => {
                for state in states.iter_mut() {
                    if state.is_due() {
                        let result = submit_task(&gateway_url, &token, &state.job);
                        if let Err(e) = result {
                            eprintln!("[hm-cron] job '{}' failed: {e}", state.job.name);
                        } else {
                            eprintln!("[hm-cron] job '{}' submitted ({})", state.job.name, state.job.task_type);
                        }
                        state.last_run = Some(Instant::now());
                    }
                }
            }
            _ = shutdown.changed() => {
                if *shutdown.borrow() {
                    eprintln!("[hm-cron] shutdown received");
                    break;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_job_is_due() {
        let state = JobState {
            job: CronJob {
                name: "test".into(),
                task_type: "echo".into(),
                payload: serde_json::Value::Null,
                interval_secs: 60,
            },
            last_run: None,
        };
        assert!(state.is_due());
    }

    #[test]
    fn recently_run_job_is_not_due() {
        let state = JobState {
            job: CronJob {
                name: "test".into(),
                task_type: "echo".into(),
                payload: serde_json::Value::Null,
                interval_secs: 3600,
            },
            last_run: Some(Instant::now()),
        };
        assert!(!state.is_due());
    }

    #[test]
    fn load_jobs_from_valid_json() {
        let tmp = std::env::temp_dir().join("hm_cron_test.json");
        std::fs::write(
            &tmp,
            r#"[{"name":"ping","task_type":"echo","interval_secs":300}]"#,
        )
        .unwrap();
        let jobs = load_jobs(tmp.to_str().unwrap()).unwrap();
        assert_eq!(jobs.len(), 1);
        assert_eq!(jobs[0].name, "ping");
        assert_eq!(jobs[0].interval_secs, 300);
    }
}
