mod chat;

use hm_agent::{Agent, TaskOutcome};
use hm_auth::{tokens_match, ALLOW_NO_AUTH_VAR};
use hm_cron::{load_jobs, run as run_cron};
use hm_memory::MemoryStore;
use hm_plugins::PluginRegistry;
use hm_sessions::SessionStore;
use hm_storage::{FileStorage, LocalFsStorage, RemoteHttpStorage};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    env,
    net::{IpAddr, SocketAddr},
    sync::Arc,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    signal::unix::{signal, SignalKind},
    sync::Mutex,
    task::JoinSet,
};
use uuid::Uuid;

/// How long shutdown waits for in-flight connections to finish after a
/// termination signal, before giving up and exiting anyway.
const SHUTDOWN_DRAIN: Duration = Duration::from_secs(10);

const MAX_REQUEST_BYTES: usize = 1_048_576;

/// Bounds memory use of the rate limiter's per-IP map: once it grows past
/// this many distinct IPs, expired entries are pruned on the next check
/// instead of waiting for a dedicated background sweep.
const RATE_LIMITER_PRUNE_THRESHOLD: usize = 10_000;

/// Per-IP fixed-window request limiter, checked before a request is even
/// read off the socket -- rejecting abusive clients before they can make
/// the gateway do any real work (parsing, auth, dispatch) is the point.
struct RateLimiter {
    per_ip: Mutex<HashMap<IpAddr, (Instant, u32)>>,
    max_per_window: u32,
    window: Duration,
}

impl RateLimiter {
    fn new(max_per_window: u32, window: Duration) -> Self {
        Self {
            per_ip: Mutex::new(HashMap::new()),
            max_per_window,
            window,
        }
    }

    /// `max_per_window == 0` disables rate limiting entirely (always allows).
    async fn allow(&self, ip: IpAddr) -> bool {
        if self.max_per_window == 0 {
            return true;
        }
        let now = Instant::now();
        let mut map = self.per_ip.lock().await;

        if map.len() > RATE_LIMITER_PRUNE_THRESHOLD {
            let window = self.window;
            map.retain(|_, (started, _)| now.duration_since(*started) <= window);
        }

        let entry = map.entry(ip).or_insert((now, 0));
        if now.duration_since(entry.0) > self.window {
            *entry = (now, 1);
            true
        } else if entry.1 < self.max_per_window {
            entry.1 += 1;
            true
        } else {
            false
        }
    }
}

#[cfg(test)]
mod rate_limiter_tests {
    use super::*;

    #[tokio::test]
    async fn allows_requests_within_the_window_limit() {
        let limiter = RateLimiter::new(3, Duration::from_secs(60));
        let ip: IpAddr = "127.0.0.1".parse().unwrap();
        assert!(limiter.allow(ip).await);
        assert!(limiter.allow(ip).await);
        assert!(limiter.allow(ip).await);
    }

    #[tokio::test]
    async fn rejects_requests_beyond_the_window_limit() {
        let limiter = RateLimiter::new(2, Duration::from_secs(60));
        let ip: IpAddr = "127.0.0.1".parse().unwrap();
        assert!(limiter.allow(ip).await);
        assert!(limiter.allow(ip).await);
        assert!(!limiter.allow(ip).await);
    }

    #[tokio::test]
    async fn different_ips_have_independent_limits() {
        let limiter = RateLimiter::new(1, Duration::from_secs(60));
        let a: IpAddr = "127.0.0.1".parse().unwrap();
        let b: IpAddr = "127.0.0.2".parse().unwrap();
        assert!(limiter.allow(a).await);
        assert!(!limiter.allow(a).await);
        assert!(limiter.allow(b).await);
    }

    #[tokio::test]
    async fn resets_after_the_window_elapses() {
        let limiter = RateLimiter::new(1, Duration::from_millis(30));
        let ip: IpAddr = "127.0.0.1".parse().unwrap();
        assert!(limiter.allow(ip).await);
        assert!(!limiter.allow(ip).await);
        tokio::time::sleep(Duration::from_millis(60)).await;
        assert!(limiter.allow(ip).await);
    }

    #[tokio::test]
    async fn zero_max_disables_limiting() {
        let limiter = RateLimiter::new(0, Duration::from_secs(60));
        let ip: IpAddr = "127.0.0.1".parse().unwrap();
        for _ in 0..50 {
            assert!(limiter.allow(ip).await);
        }
    }
}

#[derive(Debug)]
struct RequestTooLarge;

impl std::fmt::Display for RequestTooLarge {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "request exceeds {MAX_REQUEST_BYTES} byte limit")
    }
}

impl std::error::Error for RequestTooLarge {}

#[derive(Clone)]
struct AppState {
    started_at: SystemTime,
    zero_staked: bool,
    tasks: Arc<Mutex<Vec<TaskRecord>>>,
    storage: Arc<dyn FileStorage>,
    memory: Arc<MemoryStore>,
    agent: Arc<Agent>,
    sessions: Arc<SessionStore>,
    diagnostics: Arc<Mutex<Vec<DiagnosticsReport>>>,
    diagnostics_key: Arc<String>,
    /// `None` only when `HM_GATEWAY_ALLOW_NO_AUTH=true` was explicitly set at
    /// startup; otherwise the process refuses to start without a real token.
    owner_token: Option<Arc<String>>,
    rate_limiter: Arc<RateLimiter>,
}

/// Exactly the fields `ghm_core report-diagnostics` discloses to the user
/// before sending -- never extend this without updating that prompt too.
#[derive(Debug, Serialize, Deserialize, Clone)]
struct DiagnosticsReport {
    os_name: String,
    os_version: String,
    python_version: String,
    architecture: String,
    reported_at_unix: u64,
}

#[derive(Debug, Deserialize)]
struct DiagnosticsInput {
    #[serde(default)]
    os_name: String,
    #[serde(default)]
    os_version: String,
    #[serde(default)]
    python_version: String,
    #[serde(default)]
    architecture: String,
}

#[derive(Debug)]
struct HttpRequest {
    method: String,
    path: String,
    authorization: Option<String>,
    body: Vec<u8>,
}

#[derive(Debug, Serialize, Clone)]
struct TaskRecord {
    task_id: String,
    task_type: String,
    objective: String,
    payload: Value,
    accepted_at_unix: u64,
    remote_addr: String,
}

#[derive(Debug, Deserialize)]
struct TaskInput {
    #[serde(default, rename = "taskType")]
    task_type: String,
    #[serde(default)]
    objective: String,
    #[serde(default)]
    payload: Value,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let bind = env::var("HM_GATEWAY_BIND")
        .ok()
        .unwrap_or_else(resolve_configured_bind);
    let zero_staked = env::var("HM_ZERO_STAKED")
        .map(|value| {
            matches!(
                value.to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "zero_staked"
            )
        })
        .unwrap_or(false);

    let plugin_manifest =
        env::var("HM_PLUGIN_MANIFEST").unwrap_or_else(|_| "config/plugins.json".to_string());
    let plugins = PluginRegistry::from_manifest_file(&plugin_manifest).unwrap_or_else(|error| {
        eprintln!("hm-gateway: ignoring unreadable plugin manifest {plugin_manifest}: {error}");
        PluginRegistry::empty()
    });

    let storage: Arc<dyn FileStorage> = build_storage_backend()?;
    let memory_key = env::var("HM_MEMORY_KEY").unwrap_or_else(|_| "memory/index.json".to_string());
    let memory = MemoryStore::load(storage.clone(), memory_key).await;

    // Optional: ingest the structural knowledge-graph seed produced by
    // scripts/generate_knowledge_graph_seed.py. A missing/malformed seed
    // must never block gateway startup -- it's a nice-to-have alongside
    // free-text memory, not a required dependency.
    if let Ok(graph_seed_path) = env::var("HM_MEMORY_GRAPH_SEED_PATH") {
        match std::fs::read(&graph_seed_path) {
            Ok(bytes) => {
                if let Err(error) = memory.ingest_graph_seed(&bytes).await {
                    eprintln!(
                        "hm-gateway: ignoring invalid graph seed at {graph_seed_path}: {error}"
                    );
                }
            }
            Err(error) => {
                eprintln!(
                    "hm-gateway: could not read HM_MEMORY_GRAPH_SEED_PATH={graph_seed_path}: {error}"
                );
            }
        }
    }

    let diagnostics_key =
        env::var("HM_DIAGNOSTICS_KEY").unwrap_or_else(|_| "diagnostics/reports.json".to_string());
    let diagnostics: Vec<DiagnosticsReport> = storage
        .get(&diagnostics_key)
        .await
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default();

    let owner_token = match hm_auth::load_owner_token() {
        Ok(token) => Some(Arc::new(token)),
        Err(error) => {
            let allow_no_auth = env::var(ALLOW_NO_AUTH_VAR)
                .map(|v| v == "true")
                .unwrap_or(false);
            if !allow_no_auth {
                eprintln!(
                    "hm-gateway: refusing to start without owner authentication ({error}). \
                     Set {} to a real secret, or explicitly set {}=true to run without auth \
                     (local development only -- never in a reachable deployment).",
                    hm_auth::OWNER_TOKEN_VAR,
                    ALLOW_NO_AUTH_VAR
                );
                std::process::exit(1);
            }
            // Der Ausschalter gilt nur auf Loopback. Ohne diese Pruefung war
            // "nur lokal verwenden" eine Bitte im Log; jetzt ist es eine
            // Bedingung. Ein unauthentifiziertes Gateway auf 0.0.0.0 ist
            // offen fuer jeden im Netz.
            let loopback = bind.starts_with("127.")
                || bind.starts_with("localhost:")
                || bind.starts_with("[::1]");
            if !loopback {
                eprintln!(
                    "hm-gateway: refusing to start. {}=true is only honoured on a \
                     loopback bind, but HM_GATEWAY_BIND is {bind:?}. Either bind to \
                     127.0.0.1 or set a real {}.",
                    ALLOW_NO_AUTH_VAR,
                    hm_auth::OWNER_TOKEN_VAR
                );
                std::process::exit(1);
            }
            eprintln!(
                "hm-gateway: WARNING -- running with no owner authentication ({} is set) \
                 on loopback {bind:?}. Every route is unauthenticated.",
                ALLOW_NO_AUTH_VAR
            );
            None
        }
    };

    let memory = Arc::new(memory);
    let agent = Arc::new(Agent::new(Arc::new(plugins), memory.clone()));

    // 0 disables rate limiting entirely; unset defaults to a generous but
    // real per-IP cap so a single misbehaving client can't monopolize the
    // gateway, without needing any configuration to get basic protection.
    let rate_limit_per_minute: u32 = env::var("HM_RATE_LIMIT_PER_MINUTE")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(120);
    let rate_limiter = Arc::new(RateLimiter::new(
        rate_limit_per_minute,
        Duration::from_secs(60),
    ));

    let sessions = Arc::new(SessionStore::new());

    // Optional: cron scheduler — start if config/cron.json (or HM_CRON_CONFIG) exists.
    let cron_config = env::var("HM_CRON_CONFIG").unwrap_or_else(|_| "config/cron.json".to_string());
    let (cron_shutdown_tx, cron_shutdown_rx) = tokio::sync::watch::channel(false);
    if std::path::Path::new(&cron_config).exists() {
        let cron_config_clone = cron_config.clone();
        let cron_gateway_url = format!("http://{}", bind);
        let cron_token = owner_token
            .clone()
            .map(|t| (*t).clone())
            .unwrap_or_default();
        tokio::spawn(async move {
            match load_jobs(&cron_config_clone) {
                Ok(jobs) => {
                    run_cron(jobs, cron_gateway_url, cron_token, cron_shutdown_rx).await;
                }
                Err(e) => eprintln!("hm-cron: could not load {cron_config_clone}: {e}"),
            }
        });
        println!("hm-gateway: cron scheduler started from {cron_config}");
    }

    let state = AppState {
        started_at: SystemTime::now(),
        zero_staked,
        tasks: Arc::new(Mutex::new(Vec::new())),
        storage,
        memory,
        agent,
        sessions,
        diagnostics: Arc::new(Mutex::new(diagnostics)),
        diagnostics_key: Arc::new(diagnostics_key),
        owner_token,
        rate_limiter,
    };

    let listener = TcpListener::bind(&bind).await?;
    println!("hm-gateway listening on {bind}");

    let mut sigterm = signal(SignalKind::terminate())?;
    let mut connections = JoinSet::new();

    loop {
        tokio::select! {
            accepted = listener.accept() => {
                let (stream, remote_addr) = match accepted {
                    Ok(pair) => pair,
                    Err(error) => {
                        eprintln!("hm-gateway: accept() failed, continuing: {error}");
                        continue;
                    }
                };
                let state = state.clone();
                connections.spawn(async move {
                    if let Err(error) = handle_connection(stream, remote_addr, state).await {
                        eprintln!("hm-gateway request failed: {error}");
                    }
                });
                while connections.try_join_next().is_some() {}
            }
            _ = tokio::signal::ctrl_c() => {
                println!("hm-gateway received SIGINT, shutting down gracefully");
                let _ = cron_shutdown_tx.send(true);
                break;
            }
            _ = sigterm.recv() => {
                println!("hm-gateway received SIGTERM, shutting down gracefully");
                let _ = cron_shutdown_tx.send(true);
                break;
            }
        }
    }

    drop(listener);
    println!(
        "hm-gateway draining {} in-flight connection(s)",
        connections.len()
    );
    let drain_deadline = tokio::time::sleep(SHUTDOWN_DRAIN);
    tokio::pin!(drain_deadline);
    loop {
        tokio::select! {
            _ = &mut drain_deadline => {
                eprintln!(
                    "hm-gateway drain timed out with {} connection(s) still running; exiting anyway",
                    connections.len()
                );
                break;
            }
            joined = connections.join_next() => {
                if joined.is_none() {
                    break;
                }
            }
        }
    }
    println!("hm-gateway stopped");
    Ok(())
}

async fn handle_connection(
    mut stream: TcpStream,
    remote_addr: SocketAddr,
    state: AppState,
) -> anyhow::Result<()> {
    let started = Instant::now();

    if !state.rate_limiter.allow(remote_addr.ip()).await {
        let response = json_response(
            429,
            json!({ "status": "rate_limited", "reason": "too many requests from this client" }),
        );
        audit_log(remote_addr, "?", "?", 429, started.elapsed());
        stream.write_all(&response).await?;
        stream.shutdown().await?;
        return Ok(());
    }

    let response = match read_request(&mut stream).await {
        Ok(request) if is_chat_route(&request) => {
            // Streaming needs the socket itself, so this branch takes it
            // instead of returning a buffer. Auth and the rate limiter above
            // still apply -- the same gate, not a parallel one.
            let (status, path) = (chat_turn(&mut stream, request, &state).await, "/chat");
            audit_log(remote_addr, "POST", path, status, started.elapsed());
            return Ok(());
        }
        Ok(request) => {
            let method = request.method.clone();
            let path = request.path.clone();
            let response = route_request(request, remote_addr, state).await;
            audit_log(
                remote_addr,
                &method,
                &path,
                extract_status_code(&response),
                started.elapsed(),
            );
            response
        }
        Err(error) => {
            let status = if error.downcast_ref::<RequestTooLarge>().is_some() {
                413
            } else {
                400
            };
            audit_log(remote_addr, "?", "?", status, started.elapsed());
            json_response(
                status,
                json!({
                    "status": "invalid_request",
                    "accepted": false,
                    "reason": error.to_string()
                }),
            )
        }
    };
    stream.write_all(&response).await?;
    stream.shutdown().await?;
    Ok(())
}

fn is_chat_route(request: &HttpRequest) -> bool {
    request.method == "POST"
        && matches!(
            request.path.as_str(),
            "/chat" | "/api/chat" | "/gateway/chat"
        )
}

/// Repository root for the brain subprocess. Configurable because the
/// container image and a checkout put it in different places, and a wrong
/// default here would fail at the first chat turn rather than at startup.
fn brain_repo() -> std::path::PathBuf {
    env::var("HM_BRAIN_REPO")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| std::path::PathBuf::from("."))
}

/// Runs one chat turn on the socket. Returns the status code for the audit
/// line -- once the stream has started that is always 200, which is why every
/// rejection has to happen before the first byte of body goes out.
async fn chat_turn(stream: &mut TcpStream, request: HttpRequest, state: &AppState) -> u16 {
    if !authorized(state, request.authorization.as_deref()) {
        let body = json_response(
            401,
            json!({ "status": "unauthorized", "reason": "missing or invalid bearer token" }),
        );
        let _ = stream.write_all(&body).await;
        let _ = stream.shutdown().await;
        return 401;
    }

    let input: chat::ChatInput = match serde_json::from_slice(&request.body) {
        Ok(v) => v,
        Err(e) => {
            let body = json_response(
                400,
                json!({ "status": "invalid_request", "reason": e.to_string() }),
            );
            let _ = stream.write_all(&body).await;
            let _ = stream.shutdown().await;
            return 400;
        }
    };
    if let Err(reason) = chat::validate(&input) {
        let body = json_response(
            400,
            json!({ "status": "invalid_request", "reason": reason }),
        );
        let _ = stream.write_all(&body).await;
        let _ = stream.shutdown().await;
        return 400;
    }

    let origin_header = match allowed_origin(None) {
        Some(o) => format!("Access-Control-Allow-Origin: {o}\r\n"),
        None => String::new(),
    };
    let python = env::var("HM_BRAIN_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let _ = chat::stream_chat(stream, input, origin_header, &brain_repo(), &python).await;
    let _ = stream.shutdown().await;
    200
}

async fn read_request(stream: &mut TcpStream) -> anyhow::Result<HttpRequest> {
    let mut buffer = Vec::new();
    let mut chunk = [0_u8; 4096];
    let mut header_end = None;
    let mut content_length = 0_usize;

    loop {
        let n = stream.read(&mut chunk).await?;
        if n == 0 {
            break;
        }
        buffer.extend_from_slice(&chunk[..n]);
        if buffer.len() > MAX_REQUEST_BYTES {
            return Err(RequestTooLarge.into());
        }
        if header_end.is_none() {
            header_end = find_header_end(&buffer);
            if let Some(end) = header_end {
                let headers = String::from_utf8_lossy(&buffer[..end]);
                content_length = parse_content_length(&headers);
                if content_length > MAX_REQUEST_BYTES {
                    return Err(RequestTooLarge.into());
                }
            }
        }
        if let Some(end) = header_end {
            let body_start = end + 4;
            if buffer.len() >= body_start + content_length {
                break;
            }
        }
    }

    let header_end = header_end.ok_or_else(|| anyhow::anyhow!("missing http headers"))?;
    let header_text = String::from_utf8_lossy(&buffer[..header_end]);
    let mut lines = header_text.lines();
    let start_line = lines
        .next()
        .ok_or_else(|| anyhow::anyhow!("missing request line"))?;
    let mut parts = start_line.split_whitespace();
    let method = parts.next().unwrap_or_default().to_string();
    let raw_path = parts.next().unwrap_or("/");
    let path = raw_path.split('?').next().unwrap_or("/").to_string();
    let authorization = parse_authorization(&header_text);
    let body_start = header_end + 4;
    let body_end = body_start.saturating_add(content_length).min(buffer.len());

    Ok(HttpRequest {
        method,
        path,
        authorization,
        body: buffer[body_start..body_end].to_vec(),
    })
}

fn parse_authorization(headers: &str) -> Option<String> {
    headers.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        if name.eq_ignore_ascii_case("authorization") {
            Some(value.trim().to_string())
        } else {
            None
        }
    })
}

fn find_header_end(buffer: &[u8]) -> Option<usize> {
    buffer.windows(4).position(|window| window == b"\r\n\r\n")
}

fn parse_content_length(headers: &str) -> usize {
    headers
        .lines()
        .find_map(|line| {
            let (name, value) = line.split_once(':')?;
            if name.eq_ignore_ascii_case("content-length") {
                value.trim().parse::<usize>().ok()
            } else {
                None
            }
        })
        .unwrap_or(0)
}

async fn route_request(request: HttpRequest, remote_addr: SocketAddr, state: AppState) -> Vec<u8> {
    if request.method == "OPTIONS" {
        return empty_response(204);
    }

    if !authorized(&state, request.authorization.as_deref()) {
        return json_response(
            401,
            json!({ "status": "unauthorized", "reason": "missing or invalid bearer token" }),
        );
    }

    match (request.method.as_str(), request.path.as_str()) {
        ("GET", "/") => json_response(200, gateway_info(&state).await),
        ("GET", "/health") | ("GET", "/api/health") | ("GET", "/gateway/health") => {
            json_response(200, health_payload(&state).await)
        }
        ("GET", "/tasks") | ("GET", "/api/tasks") | ("GET", "/gateway/tasks") => {
            let tasks = state.tasks.lock().await.clone();
            json_response(
                200,
                json!({ "status": status_text(state.zero_staked), "tasks": tasks }),
            )
        }
        ("POST", "/tasks") | ("POST", "/api/tasks") | ("POST", "/gateway/tasks") => {
            accept_task(request.body, remote_addr, state).await
        }
        ("PUT", path) if path.starts_with("/storage/") => {
            storage_put(&state, storage_key(path), request.body).await
        }
        ("GET", path) if path.starts_with("/storage/") => {
            storage_get(&state, storage_key(path)).await
        }
        ("DELETE", path) if path.starts_with("/storage/") => {
            storage_delete(&state, storage_key(path)).await
        }
        ("GET", "/memory") => memory_list(&state).await,
        ("POST", "/memory") => memory_remember(&state, request.body).await,
        ("POST", "/memory/search") => memory_search(&state, request.body).await,
        ("GET", "/memory/graph") => memory_graph(&state).await,
        ("GET", "/diagnostics") => diagnostics_list(&state).await,
        ("POST", "/diagnostics") => diagnostics_submit(&state, request.body).await,
        // Sessions
        ("GET", "/sessions") => sessions_list(&state).await,
        ("POST", "/sessions") => sessions_create(&state, request.body).await,
        ("GET", path) if path.starts_with("/sessions/") => {
            sessions_get(&state, path.trim_start_matches("/sessions/")).await
        }
        ("POST", path) if path.starts_with("/sessions/") && path.ends_with("/messages") => {
            let id = path
                .trim_start_matches("/sessions/")
                .trim_end_matches("/messages");
            sessions_append(&state, id, request.body).await
        }
        ("DELETE", path) if path.starts_with("/sessions/") => {
            sessions_delete(&state, path.trim_start_matches("/sessions/")).await
        }
        _ => json_response(404, json!({ "status": "not_found", "path": request.path })),
    }
}

/// The single auth decision. The streaming chat path cannot go through
/// `route_request` (it needs the socket, not a finished buffer), and a second
/// hand-written token check next to this one is exactly how a route ends up
/// unprotected after a later edit touches only one of them.
fn authorized(state: &AppState, authorization: Option<&str>) -> bool {
    match &state.owner_token {
        Some(expected) => bearer_matches(authorization, expected),
        // `None` only exists when HM_GATEWAY_ALLOW_NO_AUTH was set explicitly.
        None => true,
    }
}

fn bearer_matches(header: Option<&str>, expected: &str) -> bool {
    match header.and_then(|value| value.strip_prefix("Bearer ")) {
        Some(provided) => tokens_match(provided, expected),
        None => false,
    }
}

fn storage_key(path: &str) -> &str {
    path.trim_start_matches("/storage/")
}

async fn storage_put(state: &AppState, key: &str, body: Vec<u8>) -> Vec<u8> {
    match state.storage.put(key, &body).await {
        Ok(()) => json_response(
            200,
            json!({ "status": "stored", "key": key, "bytes": body.len() }),
        ),
        Err(error) => json_response(
            400,
            json!({ "status": "storage_error", "key": key, "reason": error.to_string() }),
        ),
    }
}

async fn storage_get(state: &AppState, key: &str) -> Vec<u8> {
    match state.storage.get(key).await {
        Ok(bytes) => binary_response(200, &bytes),
        Err(_) => json_response(404, json!({ "status": "not_found", "key": key })),
    }
}

async fn storage_delete(state: &AppState, key: &str) -> Vec<u8> {
    match state.storage.delete(key).await {
        Ok(()) => json_response(200, json!({ "status": "deleted", "key": key })),
        Err(error) => json_response(
            400,
            json!({ "status": "storage_error", "key": key, "reason": error.to_string() }),
        ),
    }
}

#[derive(Debug, Deserialize)]
struct RememberInput {
    text: String,
}

#[derive(Debug, Deserialize)]
struct SearchInput {
    query: String,
    #[serde(default = "default_top_k", rename = "topK")]
    top_k: usize,
}

fn default_top_k() -> usize {
    5
}

async fn memory_list(state: &AppState) -> Vec<u8> {
    let records = state.memory.list().await;
    json_response(200, json!({ "status": "online", "records": records }))
}

/// Distinct from `GET /memory`: the structural knowledge-graph seed, if one
/// has been ingested at startup (`HM_MEMORY_GRAPH_SEED_PATH`), never the
/// free-text records. `404` if nothing has been ingested rather than an
/// empty 200, so a caller can tell "no graph" apart from "empty graph".
async fn memory_graph(state: &AppState) -> Vec<u8> {
    match state.memory.graph().await {
        Some(graph) => json_response(200, json!({ "status": "online", "graph": graph })),
        None => json_response(
            404,
            json!({ "status": "not_found", "reason": "no graph seed has been ingested" }),
        ),
    }
}

async fn memory_remember(state: &AppState, body: Vec<u8>) -> Vec<u8> {
    let input: RememberInput = match serde_json::from_slice(&body) {
        Ok(input) => input,
        Err(error) => {
            return json_response(
                400,
                json!({ "status": "invalid_request", "reason": error.to_string() }),
            );
        }
    };
    if input.text.trim().is_empty() {
        return json_response(
            400,
            json!({ "status": "invalid_request", "reason": "text must not be empty" }),
        );
    }
    match state.memory.remember(input.text).await {
        Ok(record) => json_response(201, json!({ "status": "stored", "record": record })),
        Err(error) => json_response(
            500,
            json!({ "status": "memory_error", "reason": error.to_string() }),
        ),
    }
}

async fn memory_search(state: &AppState, body: Vec<u8>) -> Vec<u8> {
    let input: SearchInput = match serde_json::from_slice(&body) {
        Ok(input) => input,
        Err(error) => {
            return json_response(
                400,
                json!({ "status": "invalid_request", "reason": error.to_string() }),
            );
        }
    };
    let hits = state.memory.recall(&input.query, input.top_k).await;
    let results: Vec<Value> = hits
        .into_iter()
        .map(|(record, score)| json!({ "record": record, "score": score }))
        .collect();
    json_response(200, json!({ "status": "online", "results": results }))
}

async fn diagnostics_list(state: &AppState) -> Vec<u8> {
    let reports = state.diagnostics.lock().await.clone();
    json_response(200, json!({ "status": "online", "reports": reports }))
}

async fn diagnostics_submit(state: &AppState, body: Vec<u8>) -> Vec<u8> {
    let input: DiagnosticsInput = match serde_json::from_slice(&body) {
        Ok(input) => input,
        Err(error) => {
            return json_response(
                400,
                json!({ "status": "invalid_request", "reason": error.to_string() }),
            );
        }
    };

    let report = DiagnosticsReport {
        os_name: input.os_name,
        os_version: input.os_version,
        python_version: input.python_version,
        architecture: input.architecture,
        reported_at_unix: unix_now(),
    };

    let snapshot = {
        let mut reports = state.diagnostics.lock().await;
        reports.push(report.clone());
        reports.clone()
    };

    match state
        .storage
        .put(
            &state.diagnostics_key,
            serde_json::to_string(&snapshot)
                .unwrap_or_default()
                .as_bytes(),
        )
        .await
    {
        Ok(()) => json_response(201, json!({ "status": "stored", "report": report })),
        Err(error) => json_response(
            500,
            json!({ "status": "diagnostics_error", "reason": error.to_string() }),
        ),
    }
}

async fn gateway_info(state: &AppState) -> Value {
    json!({
        "service": "hm-gateway",
        "status": status_text(state.zero_staked),
        "agent_managed": true,
        "routes": [
            "GET /health", "GET /api/health", "GET /gateway/health",
            "POST /tasks", "POST /api/tasks", "POST /gateway/tasks", "GET /tasks",
            "PUT /storage/{key}", "GET /storage/{key}", "DELETE /storage/{key}",
            "GET /memory", "POST /memory", "POST /memory/search",
            "GET /diagnostics", "POST /diagnostics"
        ],
        "uptime_seconds": uptime_seconds(state.started_at)
    })
}

async fn health_payload(state: &AppState) -> Value {
    let task_count = state.tasks.lock().await.len();
    json!({
        "service": "hm-gateway",
        "status": status_text(state.zero_staked),
        "zero_staked": state.zero_staked,
        "agent_managed": true,
        "task_count": task_count,
        "uptime_seconds": uptime_seconds(state.started_at),
        "checked_at_unix": unix_now()
    })
}

async fn accept_task(body: Vec<u8>, remote_addr: SocketAddr, state: AppState) -> Vec<u8> {
    if state.zero_staked {
        return json_response(
            503,
            json!({
                "status": "zero_staked",
                "accepted": false,
                "reason": "gateway_zero_staked_rotation_required"
            }),
        );
    }

    let input = match serde_json::from_slice::<TaskInput>(&body) {
        Ok(input) => input,
        Err(error) => {
            return json_response(
                400,
                json!({
                    "status": "invalid_request",
                    "accepted": false,
                    "reason": error.to_string()
                }),
            );
        }
    };

    let accepted_at_unix = unix_now();
    let task = TaskRecord {
        task_id: format!("task-{}", Uuid::new_v4()),
        task_type: if input.task_type.trim().is_empty() {
            "unspecified".to_string()
        } else {
            input.task_type
        },
        objective: input.objective,
        payload: input.payload,
        accepted_at_unix,
        remote_addr: remote_addr.to_string(),
    };

    state.tasks.lock().await.push(task.clone());

    let mut response = json!({
        "status": "online",
        "accepted": true,
        "task_id": task.task_id,
        "task_type": task.task_type,
        "agent_managed": true
    });

    let outcome = state
        .agent
        .dispatch(&task.task_type, &task.objective, task.payload.clone())
        .await;
    if let TaskOutcome::PluginDispatched {
        ok,
        result,
        message,
    } = outcome
    {
        response["plugin_result"] = json!({ "ok": ok, "result": result, "message": message });
    }

    json_response(202, response)
}

/// Selects the `FileStorage` backend from `HM_STORAGE_BACKEND` (`local`,
/// the default, or `remote`). Fails loudly rather than silently falling
/// back to local disk if `remote` is requested but `HM_REMOTE_STORAGE_URL`
/// is missing or malformed -- an operator who asked for external storage
/// and got local storage instead without being told is a correctness bug,
/// not a convenience.
fn build_storage_backend() -> anyhow::Result<Arc<dyn FileStorage>> {
    let backend = env::var("HM_STORAGE_BACKEND").unwrap_or_else(|_| "local".to_string());
    match backend.as_str() {
        "local" => Ok(Arc::new(LocalFsStorage::from_env())),
        "remote" => match RemoteHttpStorage::from_env()? {
            Some(remote) => Ok(Arc::new(remote)),
            None => anyhow::bail!(
                "HM_STORAGE_BACKEND=remote requires HM_REMOTE_STORAGE_URL to be set \
                 (e.g. http://storage-host:8080), and optionally HM_REMOTE_STORAGE_TOKEN"
            ),
        },
        other => {
            anyhow::bail!("unknown HM_STORAGE_BACKEND '{other}'; expected 'local' or 'remote'")
        }
    }
}

/// Falls back to `server.bind` in `config/heavy-metal.json` (relative to the
/// process working directory) when `HM_GATEWAY_BIND` is unset, so the
/// checked-in config isn't silently ignored. Falls back to the hardcoded
/// default if the file is missing, unparseable, or lacks that field.
fn resolve_configured_bind() -> String {
    std::fs::read_to_string("config/heavy-metal.json")
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .and_then(|value| {
            value
                .get("server")?
                .get("bind")?
                .as_str()
                .map(str::to_string)
        })
        .unwrap_or_else(|| "0.0.0.0:8080".to_string())
}

fn status_text(zero_staked: bool) -> &'static str {
    if zero_staked {
        "zero_staked"
    } else {
        "online"
    }
}

fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn uptime_seconds(started_at: SystemTime) -> u64 {
    SystemTime::now()
        .duration_since(started_at)
        .unwrap_or_default()
        .as_secs()
}

fn empty_response(status: u16) -> Vec<u8> {
    raw_response(status, "text/plain", &[])
}

fn binary_response(status: u16, body: &[u8]) -> Vec<u8> {
    raw_response(status, "application/octet-stream", body)
}

fn json_response(status: u16, payload: Value) -> Vec<u8> {
    let body = serde_json::to_string_pretty(&payload).unwrap_or_else(|_| "{}".to_string());
    raw_response(status, "application/json; charset=utf-8", body.as_bytes())
}

fn raw_response(status: u16, content_type: &str, body: &[u8]) -> Vec<u8> {
    let headers = format!(
        "HTTP/1.1 {status} {}\r\n{}Content-Length: {}\r\n\r\n",
        reason_phrase(status),
        common_headers(content_type),
        body.len()
    );
    let mut response = headers.into_bytes();
    response.extend_from_slice(body);
    response
}

/// Origins die das Gateway aus einem Browser aufrufen duerfen.
///
/// `HM_ALLOWED_ORIGINS` als kommaseparierte Liste, z.B.
/// `https://benholl94-cmyk.github.io,http://localhost:5173`.
/// Nicht gesetzt heisst: **keine** fremde Origin. `*` war die alte
/// Voreinstellung und ist bewusst nicht mehr der Fallback -- eine
/// Wildcard laesst jede beliebige Website Anfragen im Namen des Browsers
/// stellen, sobald sie an das Token kommt.
fn allowed_origin(request_origin: Option<&str>) -> Option<String> {
    allowed_origin_from(
        &env::var("HM_ALLOWED_ORIGINS").unwrap_or_default(),
        request_origin,
    )
}

/// Reine Funktion -- die Konfiguration kommt als Parameter, nicht aus der
/// Prozessumgebung. Tests, die `env::set_var` benutzen, beeinflussen sich
/// bei Rusts paralleler Testausfuehrung gegenseitig; genau das ist hier
/// einmal passiert und hat einen Wackeltest erzeugt.
fn allowed_origin_from(configured: &str, request_origin: Option<&str>) -> Option<String> {
    if configured.trim() == "*" {
        // Ausdrueckliche Wildcard bleibt moeglich, aber nur wenn sie jemand
        // hinschreibt -- nicht als stiller Standard.
        return Some("*".to_string());
    }
    let origin = request_origin?;
    configured
        .split(',')
        .map(str::trim)
        .filter(|o| !o.is_empty())
        .find(|o| *o == origin)
        .map(str::to_string)
}

fn common_headers(content_type: &str) -> String {
    common_headers_for(content_type, None)
}

fn common_headers_for(content_type: &str, request_origin: Option<&str>) -> String {
    let mut headers = format!(
        "Content-Type: {content_type}\r\nAccess-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS\r\nAccess-Control-Allow-Headers: content-type, accept, authorization\r\n"
    );
    if let Some(origin) = allowed_origin(request_origin) {
        headers.push_str(&format!("Access-Control-Allow-Origin: {origin}\r\n"));
        if origin != "*" {
            // Ohne Vary cachen Proxies die Antwort fuer eine Origin und
            // liefern sie einer anderen aus.
            headers.push_str("Vary: Origin\r\n");
        }
    }
    headers.push_str("Connection: close\r\n");
    headers
}

fn reason_phrase(status: u16) -> &'static str {
    match status {
        200 => "OK",
        201 => "Created",
        202 => "Accepted",
        204 => "No Content",
        400 => "Bad Request",
        401 => "Unauthorized",
        404 => "Not Found",
        413 => "Payload Too Large",
        429 => "Too Many Requests",
        500 => "Internal Server Error",
        503 => "Service Unavailable",
        _ => "OK",
    }
}

/// Pulls the status code back out of a fully-rendered response (`"HTTP/1.1
/// 200 OK\r\n..."`). Every response in this file goes through
/// [`raw_response`], which always writes exactly this format, so this is
/// exact, not a heuristic -- kept separate from the handler functions so
/// audit logging doesn't require threading a status code through every
/// individual route handler's return type.
fn extract_status_code(response: &[u8]) -> u16 {
    let prefix_len = response.len().min(32);
    let text = String::from_utf8_lossy(&response[..prefix_len]);
    text.split_whitespace()
        .nth(1)
        .and_then(|code| code.parse().ok())
        .unwrap_or(0)
}

/// One structured JSON line per request to stdout -- under the systemd unit
/// this repo ships (`deploy/hm-gateway.service`), stdout goes straight to
/// journald, so this is a real, queryable audit trail with no extra
/// plumbing required, not a logging framework that still needs wiring up.
fn audit_log(remote_addr: SocketAddr, method: &str, path: &str, status: u16, latency: Duration) {
    println!(
        "{}",
        json!({
            "audit": true,
            "ts_unix": unix_now(),
            "remote_addr": remote_addr.to_string(),
            "method": method,
            "path": path,
            "status": status,
            "latency_ms": latency.as_millis(),
        })
    );
}

// ── Sessions routes ──────────────────────────────────────────────────────────

async fn sessions_list(state: &AppState) -> Vec<u8> {
    let list = state.sessions.list().await;
    json_response(200, json!({ "sessions": list }))
}

async fn sessions_create(state: &AppState, body: Vec<u8>) -> Vec<u8> {
    #[derive(Deserialize)]
    struct Req {
        name: Option<String>,
    }
    let name = serde_json::from_slice::<Req>(&body)
        .ok()
        .and_then(|r| r.name)
        .unwrap_or_else(|| "unnamed".to_string());
    let session = state.sessions.create(name).await;
    json_response(201, json!({ "status": "created", "session": session }))
}

async fn sessions_get(state: &AppState, id: &str) -> Vec<u8> {
    match state.sessions.get(id).await {
        Some(s) => json_response(200, json!(s)),
        None => json_response(404, json!({ "status": "not_found", "id": id })),
    }
}

async fn sessions_append(state: &AppState, id: &str, body: Vec<u8>) -> Vec<u8> {
    #[derive(Deserialize)]
    struct Req {
        role: String,
        content: String,
    }
    let req = match serde_json::from_slice::<Req>(&body) {
        Ok(r) => r,
        Err(e) => {
            return json_response(
                400,
                json!({ "status": "bad_request", "reason": e.to_string() }),
            )
        }
    };
    let msg = hm_sessions::Message::new(req.role, req.content);
    if state.sessions.append(id, msg).await {
        match state.sessions.get(id).await {
            Some(s) => json_response(200, json!({ "status": "appended", "session": s })),
            None => json_response(200, json!({ "status": "appended" })),
        }
    } else {
        json_response(404, json!({ "status": "not_found", "id": id }))
    }
}

async fn sessions_delete(state: &AppState, id: &str) -> Vec<u8> {
    let removed = state.sessions.delete(id).await;
    if removed {
        json_response(200, json!({ "status": "deleted", "id": id }))
    } else {
        json_response(404, json!({ "status": "not_found", "id": id }))
    }
}

#[cfg(test)]
mod audit_tests {
    use super::*;

    #[test]
    fn extracts_status_from_a_real_response() {
        let response = json_response(200, json!({"ok": true}));
        assert_eq!(extract_status_code(&response), 200);
    }

    #[test]
    fn extracts_status_for_every_response_helper() {
        assert_eq!(extract_status_code(&empty_response(204)), 204);
        assert_eq!(extract_status_code(&binary_response(200, b"x")), 200);
        assert_eq!(extract_status_code(&json_response(429, json!({}))), 429);
        assert_eq!(extract_status_code(&json_response(404, json!({}))), 404);
    }

    /// Die Wildcard war die alte Voreinstellung. Sie darf nur noch
    /// erscheinen, wenn jemand sie ausdruecklich hinschreibt.
    #[test]
    fn cors_denies_unknown_origin_by_default() {
        assert_eq!(allowed_origin_from("", Some("https://boese.example")), None);
        assert_eq!(allowed_origin_from("", None), None);
    }

    #[test]
    fn cors_allows_only_configured_origins() {
        let cfg = "https://a.example, https://b.example";
        assert_eq!(
            allowed_origin_from(cfg, Some("https://a.example")),
            Some("https://a.example".to_string())
        );
        assert_eq!(allowed_origin_from(cfg, Some("https://c.example")), None);
    }

    #[test]
    fn cors_wildcard_requires_explicit_opt_in() {
        assert_eq!(
            allowed_origin_from("*", Some("https://beliebig.example")),
            Some("*".to_string())
        );
    }

    /// Eine Origin, die nur Praefix einer erlaubten ist, darf nicht passen.
    #[test]
    fn cors_matches_origins_exactly() {
        let cfg = "https://a.example";
        assert_eq!(
            allowed_origin_from(cfg, Some("https://a.example.boese.tld")),
            None
        );
        assert_eq!(allowed_origin_from(cfg, Some("https://a.exampl")), None);
    }

    #[test]
    fn cors_header_absent_when_origin_not_allowed() {
        let h = common_headers_for("application/json", Some("https://fremd.example"));
        assert!(!h.contains("Access-Control-Allow-Origin"));
    }
}
