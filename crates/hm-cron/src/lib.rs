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
/// Wie lange ein Selbstaufruf hoechstens dauern darf.
///
/// Ohne Grenze haengt der Runner an einer Gegenstelle, die nie antwortet —
/// und die Gegenstelle ist hier das eigene Gateway.
const SUBMIT_TIMEOUT: Duration = Duration::from_secs(10);

/// Reiht einen Job im Gateway ein.
///
/// **Warum async und nicht `std::net`.** Die erste Fassung benutzte
/// `std::net::TcpStream` mit `read_to_string` — synchrone, unbegrenzte
/// Blockade mitten in einer Tokio-Task. Gemessene Folge: mit aktivem Cron
/// beantwortete das Gateway **keine einzige** Anfrage mehr, dauerhaft, ab
/// der ersten Sekunde; mit `HM_CRON_CONFIG` auf einen nicht existierenden
/// Pfad lief dasselbe Binary normal. Der Runner legte also genau den Dienst
/// lahm, den er bedienen sollte.
///
/// Blockierendes I/O gehoert nicht auf den Async-Scheduler, und ein Aufruf
/// ohne Zeitgrenze gehoert nirgendwohin.
async fn submit_task(gateway_url: &str, token: &str, job: &CronJob) -> Result<(), anyhow::Error> {
    tokio::time::timeout(SUBMIT_TIMEOUT, submit_task_inner(gateway_url, token, job))
        .await
        .map_err(|_| anyhow::anyhow!("timeout after {}s", SUBMIT_TIMEOUT.as_secs()))?
}

async fn submit_task_inner(
    gateway_url: &str,
    token: &str,
    job: &CronJob,
) -> Result<(), anyhow::Error> {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpStream;

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
    let mut stream = TcpStream::connect(&addr).await?;
    stream.write_all(request.as_bytes()).await?;

    let mut response = String::new();
    stream.read_to_string(&mut response).await?;
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

    'runner: loop {
        tokio::select! {
            _ = interval.tick() => {
                for state in states.iter_mut() {
                    if !state.is_due() {
                        continue;
                    }
                    // Shutdown wird auch WAEHREND eines laufenden Jobs
                    // beachtet. Ohne dieses zweite select! wartete der
                    // Runner erst den Job (bis zu SUBMIT_TIMEOUT) ab und
                    // reagierte danach — der Gegentest unten hat genau das
                    // aufgedeckt, nachdem die eigentliche Blockade schon
                    // behoben war. Ein Dienst, der beim Beenden zehn
                    // Sekunden nachhaengt, verfehlt das Drain-Fenster in
                    // deploy/hm-gateway.service.
                    tokio::select! {
                        result = submit_task(&gateway_url, &token, &state.job) => {
                            if let Err(e) = result {
                                eprintln!("[hm-cron] job '{}' failed: {e}", state.job.name);
                            } else {
                                eprintln!("[hm-cron] job '{}' submitted ({})",
                                          state.job.name, state.job.task_type);
                            }
                            state.last_run = Some(Instant::now());
                        }
                        _ = shutdown.changed() => {
                            if *shutdown.borrow() {
                                eprintln!("[hm-cron] shutdown received (job '{}' abgebrochen)",
                                          state.job.name);
                                break 'runner;
                            }
                        }
                    }
                }
            }
            _ = shutdown.changed() => {
                if *shutdown.borrow() {
                    eprintln!("[hm-cron] shutdown received");
                    break 'runner;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Der Gegentest zum Fehler, der das Gateway lahmlegte.
    ///
    /// Die Gegenstelle nimmt die Verbindung an und antwortet **nie** — genau
    /// die Lage, die im Betrieb auftrat. Mit der alten, synchronen Fassung
    /// blockierte `read_to_string` hier den Runtime-Thread, der Zaehler blieb
    /// stehen und der Test lief in seinen eigenen Timeout. Mit der async
    /// Fassung laeuft nebenher weiter, was nebenher laufen soll.
    ///
    /// Der Test prueft also nicht "der Job wurde gesendet", sondern die
    /// eigentliche Eigenschaft: **ein haengender Job haelt nichts anderes an.**
    #[tokio::test(flavor = "current_thread")]
    async fn a_hanging_job_does_not_stall_everything_else() {
        use std::sync::atomic::{AtomicU32, Ordering};
        use std::sync::Arc;

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        // Schwarzes Loch: annehmen, festhalten, nie antworten.
        tokio::spawn(async move {
            let mut held = Vec::new();
            while let Ok((s, _)) = listener.accept().await {
                held.push(s);
            }
        });

        let ticks = Arc::new(AtomicU32::new(0));
        let t = ticks.clone();
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(Duration::from_millis(50)).await;
                t.fetch_add(1, Ordering::SeqCst);
            }
        });

        let (tx, rx) = tokio::sync::watch::channel(false);
        let jobs = vec![CronJob {
            name: "haengt".into(),
            task_type: "echo".into(),
            payload: serde_json::Value::Null,
            interval_secs: 1,
        }];
        let runner = tokio::spawn(run(jobs, format!("http://{addr}"), "t".into(), rx));

        tokio::time::sleep(Duration::from_secs(3)).await;
        assert!(
            ticks.load(Ordering::SeqCst) >= 20,
            "Nebenlaeufigkeit stand still: nur {} Ticks in 3s — der Runner blockiert den Scheduler",
            ticks.load(Ordering::SeqCst)
        );

        // Und er reagiert weiterhin auf Shutdown, statt im Aufruf zu haengen.
        tx.send(true).unwrap();
        tokio::time::timeout(Duration::from_secs(5), runner)
            .await
            .expect("Runner reagierte nicht auf Shutdown")
            .unwrap();
    }

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
