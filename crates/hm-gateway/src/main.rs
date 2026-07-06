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

#[derive(Clone)]
struct AppState {
    started_at: SystemTime,
    zero_staked: bool,
    tasks: Arc<Mutex<Vec<TaskRecord>>>,
    storage: Arc<LocalFsStorage>,
}

#[derive(Debug)]
struct HttpRequest {
    method: String,
    path: String,
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
    let bind = env::var("HM_GATEWAY_BIND").unwrap_or_else(|_| "0.0.0.0:8080".to_string());
    let zero_staked = env::var("HM_ZERO_STAKED")
        .map(|value| {
            matches!(
                value.to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "zero_staked"
            )
        })
        .unwrap_or(false);

    let state = AppState {
        started_at: SystemTime::now(),
        zero_staked,
        tasks: Arc::new(Mutex::new(Vec::new())),
        storage: Arc::new(LocalFsStorage::from_env()),
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
        Err(error) => json_response(
            400,
            json!({
                "status": "invalid_request",
                "accepted": false,
                "reason": error.to_string()
            }),
        ),
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
            anyhow::bail!("request too large");
        }
        if header_end.is_none() {
            header_end = find_header_end(&buffer);
            if let Some(end) = header_end {
                let headers = String::from_utf8_lossy(&buffer[..end]);
                content_length = parse_content_length(&headers);
                if content_length > MAX_REQUEST_BYTES {
                    anyhow::bail!("request body too large");
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
    let body_start = header_end + 4;
    let body_end = body_start.saturating_add(content_length).min(buffer.len());

    Ok(HttpRequest {
        method,
        path,
        body: buffer[body_start..body_end].to_vec(),
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
        _ => json_response(404, json!({ "status": "not_found", "path": request.path })),
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

async fn gateway_info(state: &AppState) -> Value {
    json!({
        "service": "hm-gateway",
        "status": status_text(state.zero_staked),
        "agent_managed": true,
        "routes": [
            "GET /health", "GET /api/health", "POST /tasks", "POST /api/tasks", "GET /tasks",
            "PUT /storage/{key}", "GET /storage/{key}", "DELETE /storage/{key}"
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

    json_response(
        202,
        json!({
            "status": "online",
            "accepted": true,
            "task_id": task.task_id,
            "task_type": task.task_type,
            "agent_managed": true
        }),
    )
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
        "Content-Type: {content_type}\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: GET, POST, OPTIONS\r\nAccess-Control-Allow-Headers: content-type, accept\r\nConnection: close\r\n"
    )
}

fn reason_phrase(status: u16) -> &'static str {
    match status {
        200 => "OK",
        202 => "Accepted",
        204 => "No Content",
        400 => "Bad Request",
        404 => "Not Found",
        413 => "Payload Too Large",
        503 => "Service Unavailable",
        _ => "OK",
    }
}
