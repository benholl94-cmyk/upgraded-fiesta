//! `hm-cli` — Kommandozeilen-Client für hm-gateway.
//!
//! Alle Subcommands kommunizieren per HTTP gegen `HM_GATEWAY_URL`
//! (Standard: `http://localhost:8080`) und authentifizieren sich
//! mit `HM_OWNER_TOKEN`.
//!
//! Verwendung:
//!   hm-cli status
//!   hm-cli tasks list
//!   hm-cli tasks submit --type echo --payload '{"msg":"hi"}'
//!   hm-cli memory recall "gateway speicher"
//!   hm-cli memory store "key" "value"
//!   hm-cli storage get <key>
//!   hm-cli storage put <key> <value>

use clap::{Parser, Subcommand};
use hm_core::{optional_env, HmError};
use std::io::{Read, Write};
use std::net::TcpStream;

// ── CLI-Struktur ─────────────────────────────────────────────────────────────

#[derive(Parser)]
#[command(name = "hm-cli", about = "hm-gateway Kommandozeilen-Client")]
struct Cli {
    /// Gateway-URL (Standard: HM_GATEWAY_URL oder http://localhost:8080)
    #[arg(long, env = "HM_GATEWAY_URL", default_value = "http://localhost:8080")]
    gateway: String,

    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Zeigt Gateway-Status und Versionsinformationen
    Status,
    /// Aufgaben-Verwaltung
    #[command(subcommand)]
    Tasks(TasksCmd),
    /// Semantisches Gedächtnis
    #[command(subcommand)]
    Memory(MemoryCmd),
    /// Schlüssel-Wert-Speicher
    #[command(subcommand)]
    Storage(StorageCmd),
}

#[derive(Subcommand)]
enum TasksCmd {
    /// Alle Tasks auflisten
    List,
    /// Neuen Task einreichen
    Submit {
        /// Task-Typ (z.B. echo, llm-chat, ops-tool)
        #[arg(long)]
        r#type: String,
        /// JSON-Payload (optional)
        #[arg(long, default_value = "{}")]
        payload: String,
    },
}

#[derive(Subcommand)]
enum MemoryCmd {
    /// Ähnliche Einträge suchen
    Recall {
        /// Suchtext
        query: String,
        /// Maximale Anzahl Ergebnisse
        #[arg(long, default_value = "5")]
        top_k: usize,
    },
    /// Eintrag speichern
    Store {
        /// Schlüssel
        key: String,
        /// Wert
        value: String,
    },
    /// Alle Einträge auflisten
    List,
}

#[derive(Subcommand)]
enum StorageCmd {
    /// Wert lesen
    Get { key: String },
    /// Wert speichern
    Put { key: String, value: String },
    /// Eintrag löschen
    Delete { key: String },
}

// ── HTTP-Hilfsfunktionen (keine externen Crates) ─────────────────────────────

struct GatewayClient {
    host: String,
    port: u16,
    token: String,
}

impl GatewayClient {
    fn new(url: &str, token: &str) -> Result<Self, HmError> {
        let url = url.trim_start_matches("http://");
        let (host, port_str) = url.rsplit_once(':').unwrap_or((url, "8080"));
        let port: u16 = port_str
            .parse()
            .map_err(|_| HmError::Config(format!("invalid port in URL: {url}")))?;
        Ok(Self {
            host: host.to_string(),
            port,
            token: token.to_string(),
        })
    }

    fn request(&self, method: &str, path: &str, body: Option<&str>) -> Result<String, HmError> {
        let addr = format!("{}:{}", self.host, self.port);
        let mut stream = TcpStream::connect(&addr)
            .map_err(|e| HmError::Io(format!("cannot connect to {addr}: {e}")))?;

        let body_bytes = body.unwrap_or("").as_bytes();
        let request = format!(
            "{method} {path} HTTP/1.0\r\n\
             Host: {host}\r\n\
             Authorization: Bearer {token}\r\n\
             Content-Type: application/json\r\n\
             Content-Length: {len}\r\n\
             \r\n",
            host = self.host,
            token = self.token,
            len = body_bytes.len(),
        );

        stream
            .write_all(request.as_bytes())
            .map_err(|e| HmError::Io(e.to_string()))?;
        if !body_bytes.is_empty() {
            stream
                .write_all(body_bytes)
                .map_err(|e| HmError::Io(e.to_string()))?;
        }

        let mut response = String::new();
        stream
            .read_to_string(&mut response)
            .map_err(|e| HmError::Io(e.to_string()))?;

        // HTTP-Header abschneiden — Body nach \r\n\r\n
        if let Some(pos) = response.find("\r\n\r\n") {
            Ok(response[pos + 4..].to_string())
        } else {
            Ok(response)
        }
    }

    fn get(&self, path: &str) -> Result<String, HmError> {
        self.request("GET", path, None)
    }

    fn post(&self, path: &str, body: &str) -> Result<String, HmError> {
        self.request("POST", path, Some(body))
    }

    fn put(&self, path: &str, body: &str) -> Result<String, HmError> {
        self.request("PUT", path, Some(body))
    }

    fn delete(&self, path: &str) -> Result<String, HmError> {
        self.request("DELETE", path, None)
    }
}

// ── Subcommand-Handler ────────────────────────────────────────────────────────

fn handle_status(client: &GatewayClient) -> Result<(), HmError> {
    let body = client.get("/health")?;
    println!("{body}");
    Ok(())
}

fn handle_tasks(client: &GatewayClient, cmd: TasksCmd) -> Result<(), HmError> {
    match cmd {
        TasksCmd::List => {
            let body = client.get("/tasks")?;
            println!("{body}");
        }
        TasksCmd::Submit { r#type, payload } => {
            let json = format!(r#"{{"task_type":"{type}","payload":{payload}}}"#);
            let body = client.post("/tasks", &json)?;
            println!("{body}");
        }
    }
    Ok(())
}

fn handle_memory(client: &GatewayClient, cmd: MemoryCmd) -> Result<(), HmError> {
    match cmd {
        MemoryCmd::Recall { query, top_k } => {
            let json = format!(r#"{{"query":"{query}","top_k":{top_k}}}"#);
            let body = client.post("/memory/search", &json)?;
            println!("{body}");
        }
        MemoryCmd::Store { key, value } => {
            let json = format!(r#"{{"key":"{key}","value":"{value}"}}"#);
            let body = client.post("/memory", &json)?;
            println!("{body}");
        }
        MemoryCmd::List => {
            let body = client.get("/memory")?;
            println!("{body}");
        }
    }
    Ok(())
}

fn handle_storage(client: &GatewayClient, cmd: StorageCmd) -> Result<(), HmError> {
    match cmd {
        StorageCmd::Get { key } => {
            let body = client.get(&format!("/storage/{key}"))?;
            println!("{body}");
        }
        StorageCmd::Put { key, value } => {
            let body = client.put(&format!("/storage/{key}"), &value)?;
            println!("{body}");
        }
        StorageCmd::Delete { key } => {
            let body = client.delete(&format!("/storage/{key}"))?;
            println!("{body}");
        }
    }
    Ok(())
}

// ── Main ──────────────────────────────────────────────────────────────────────

fn main() {
    let cli = Cli::parse();

    let token = optional_env("HM_OWNER_TOKEN").unwrap_or_default();
    if token.is_empty() {
        eprintln!("warning: HM_OWNER_TOKEN not set — requests will be rejected by gateway");
    }

    let client = match GatewayClient::new(&cli.gateway, &token) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("error: {e}");
            std::process::exit(1);
        }
    };

    let result = match cli.command {
        Command::Status => handle_status(&client),
        Command::Tasks(cmd) => handle_tasks(&client, cmd),
        Command::Memory(cmd) => handle_memory(&client, cmd),
        Command::Storage(cmd) => handle_storage(&client, cmd),
    };

    if let Err(e) = result {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}
