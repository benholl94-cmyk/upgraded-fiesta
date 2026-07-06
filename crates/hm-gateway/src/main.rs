use hm_auth::{tokens_match, ALLOW_NO_AUTH_VAR};
use hm_memory::MemoryStore;
use hm_plugins::PluginRegistry;
use hm_storage::{FileStorage, LocalFsStorage};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    env,
    net::SocketAddr,
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::Mutex,
};

const MAX_REQUEST_BYTES: usize = 1_048_576;

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
    storage: Arc<LocalFsStorage>,
    plugins: Arc<PluginRegistry>,
    memory: Arc<MemoryStore>,
    diagnostics: Arc<Mutex<Vec<DiagnosticsReport>>>,
    diagnostics_key: Arc<String>,
    /// `None` only when `HM_GATEWAY_ALLOW_NO_AUTH=true` was explicitly set at
    /// startup; otherwise the process refuses to start without a real token.
    owner_token: Option<Arc<String>>,
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

    let storage: Arc<LocalFsStorage> = Arc::new(LocalFsStorage::from_env());
    let memory_key = env::var("HM_MEMORY_KEY").unwrap_or_else(|_| "memory/index.json".to_string());
    let memory = MemoryStore::load(storage.clone(), memory_key).await;

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
            eprintln!(
                "hm-gateway: WARNING -- running with no owner authentication ({} is set). \
                 Every route is unauthenticated. Do not expose this port to anything but \
                 localhost/trusted networks.",
                ALLOW_NO_AUTH_VAR
            );
            None
        }
    };

    let state = AppState {
        started_at: SystemTime::now(),
        zero_staked,
        tasks: Arc::new(Mutex::new(Vec::new())),
        storage,
        plugins: Arc::new(plugins),
        memory: Arc::new(memory),
        diagnostics: Arc::new(Mutex::new(diagnostics)),
        diagnostics_key: Arc::new(diagnostics_key),
        owner_token,
    };

    let listener = TcpListener::bind(&bind).await?;
    println!("hm-gateway listening on {bind}");

    loop {
        let (stream, remote_addr) = listener.accept().await?;
        let state = state.clone();
        tokio::spawn(async move {
            if let Err(error) = handle_connection(stream, remote_addr, state).await {
                eprintln!("hm-gateway request failed: {error}");
            }
        });
    }
}

async fn handle_connection(
    mut stream: TcpStream,
    remote_addr: SocketAddr,
    state: AppState,
) -> anyhow::Result<()> {
    let response = match read_request(&mut stream).await {
        Ok(request) => route_request(request, remote_addr, state).await,
        Err(error) => {
            let status = if error.downcast_ref::<RequestTooLarge>().is_some() {
                413
            } else {
                400
            };
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

    if let Some(owner_token) = &state.owner_token {
        if !bearer_matches(request.authorization.as_deref(), owner_token) {
            return json_response(
                401,
                json!({ "status": "unauthorized", "reason": "missing or invalid bearer token" }),
            );
        }
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
        ("GET", "/diagnostics") => diagnostics_list(&state).await,
        ("POST", "/diagnostics") => diagnostics_submit(&state, request.body).await,
        _ => json_response(404, json!({ "status": "not_found", "path": request.path })),
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
        task_id: format!("task-{accepted_at_unix}-{}", remote_addr.port()),
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

    if state.plugins.has(&task.task_type) {
        let plugin_result = match state
            .plugins
            .invoke(&task.task_type, &task.objective, task.payload.clone())
            .await
        {
            Ok(plugin_response) => json!({
                "ok": plugin_response.ok,
                "result": plugin_response.result,
                "message": plugin_response.message
            }),
            Err(error) => json!({ "ok": false, "message": error.to_string() }),
        };
        response["plugin_result"] = plugin_result;
    }

    json_response(202, response)
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

fn common_headers(content_type: &str) -> String {
    format!(
        "Content-Type: {content_type}\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS\r\nAccess-Control-Allow-Headers: content-type, accept, authorization\r\nConnection: close\r\n"
    )
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
        500 => "Internal Server Error",
        503 => "Service Unavailable",
        _ => "OK",
    }
}
