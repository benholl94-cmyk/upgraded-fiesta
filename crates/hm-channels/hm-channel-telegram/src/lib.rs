//! `hm-channel-telegram` — Telegram Bot API Adapter für hm-gateway.
//!
//! Empfängt eingehende Updates via Long-Polling und leitet Nachrichten als
//! Tasks an `HM_GATEWAY_URL/tasks` weiter. Ausgehende Nachrichten werden
//! via `sendMessage` zugestellt.
//!
//! Env-Vars:
//!   `HM_TELEGRAM_BOT_TOKEN` — Telegram Bot-Token (von @BotFather)
//!   `HM_GATEWAY_URL`        — Gateway-URL (Standard: http://localhost:8080)
//!   `HM_OWNER_TOKEN`        — Gateway-Auth-Token
//!
//! Dieser Adapter sendet **keine** Verbindung auf, solange kein Token gesetzt
//! ist — er schlägt beim Start klar fehl statt lautlos.

pub fn channel_name() -> &'static str {
    "telegram"
}

/// Lädt den Bot-Token aus `HM_TELEGRAM_BOT_TOKEN`.
pub fn bot_token() -> anyhow::Result<String> {
    hm_auth::load_bot_token(channel_name())
}

use serde::Deserialize;
use serde_json::{json, Value};
use std::io::{Read, Write};
use std::net::TcpStream;

// ── Telegram API Typen ────────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
pub struct TelegramUpdate {
    pub update_id: i64,
    pub message: Option<TelegramMessage>,
}

#[derive(Debug, Deserialize)]
pub struct TelegramMessage {
    pub message_id: i64,
    pub from: Option<TelegramUser>,
    pub chat: TelegramChat,
    pub text: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct TelegramUser {
    pub id: i64,
    pub username: Option<String>,
    pub first_name: String,
}

#[derive(Debug, Deserialize)]
pub struct TelegramChat {
    pub id: i64,
    pub r#type: String,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct TelegramResponse<T> {
    ok: bool,
    result: Option<T>,
    description: Option<String>,
}

// ── HTTP-Hilfsfunktion (plain TCP, kein TLS — Telegram erfordert HTTPS) ──────

fn telegram_api_post(token: &str, method: &str, _body: &Value) -> Result<Value, anyhow::Error> {
    // Telegram API erfordert HTTPS. Ohne TLS-Bibliothek geben wir einen
    // klaren Fehler zurück — in Production eine TLS-fähige Implementierung verwenden.
    anyhow::bail!(
        "Telegram API requires HTTPS. \
         Add rustls or native-tls to this crate to enable live requests. \
         Method: {method}, Token: {}***",
        &token[..token.len().min(8)]
    )
}

/// Simulierte Implementierung für Tests und lokale Entwicklung.
/// In Production: durch eine echte HTTPS-Implementierung ersetzen.
pub struct TelegramClient {
    pub token: String,
    pub gateway_url: String,
    pub owner_token: String,
}

impl TelegramClient {
    pub fn new() -> anyhow::Result<Self> {
        Ok(Self {
            token: bot_token()?,
            gateway_url: std::env::var("HM_GATEWAY_URL")
                .unwrap_or_else(|_| "http://localhost:8080".to_string()),
            owner_token: std::env::var("HM_OWNER_TOKEN").unwrap_or_default(),
        })
    }

    /// Holt neue Updates via `getUpdates` (Long-Polling, Timeout 30s).
    pub fn get_updates(&self, offset: i64) -> Result<Vec<TelegramUpdate>, anyhow::Error> {
        telegram_api_post(
            &self.token,
            "getUpdates",
            &json!({ "offset": offset, "timeout": 30, "allowed_updates": ["message"] }),
        )
        .map(|_| vec![]) // Erreicht nie — HTTPS fehlt
    }

    /// Sendet eine Textnachricht an einen Chat.
    pub fn send_message(&self, chat_id: i64, text: &str) -> Result<(), anyhow::Error> {
        telegram_api_post(
            &self.token,
            "sendMessage",
            &json!({ "chat_id": chat_id, "text": text, "parse_mode": "Markdown" }),
        )
        .map(|_| ())
    }

    /// Leitet eine eingehende Nachricht als Task ans Gateway weiter.
    pub fn forward_to_gateway(&self, msg: &TelegramMessage) -> Result<(), anyhow::Error> {
        let text = msg.text.as_deref().unwrap_or("");
        // Der Feldname stammt aus dem geteilten `TaskSubmission`, nicht aus
        // einem hier ausgeschriebenen JSON-Literal: ausgeschrieben hiess er
        // `task_type`, band am Gateway an nichts, und jede weitergeleitete
        // Nachricht wurde mit 202 quittiert, ohne je ein Plugin zu erreichen.
        let task_payload = serde_json::to_string(&hm_sdk::TaskSubmission::new(
            "telegram-message",
            String::new(),
            json!({
                "chat_id": msg.chat.id,
                "text": text,
                "from": msg.from.as_ref().map(|u| &u.first_name),
            }),
        ))?;

        let body = task_payload;
        let url = self.gateway_url.trim_start_matches("http://");
        let (host, port_str) = url.rsplit_once(':').unwrap_or((url, "8080"));
        let port: u16 = port_str.parse().unwrap_or(8080);

        let request = format!(
            "POST /tasks HTTP/1.0\r\nHost: {host}\r\nAuthorization: Bearer {token}\r\n\
             Content-Type: application/json\r\nContent-Length: {len}\r\n\r\n{body}",
            token = self.owner_token,
            len = body.len()
        );

        let addr = format!("{host}:{port}");
        let mut stream = TcpStream::connect(&addr)
            .map_err(|e| anyhow::anyhow!("gateway connect failed: {e}"))?;
        stream.write_all(request.as_bytes())?;
        let mut _resp = String::new();
        stream.read_to_string(&mut _resp)?;
        Ok(())
    }

    /// Startet den Long-Poll-Loop. Blockiert bis `running` auf `false` gesetzt wird.
    pub fn run_polling(&self, running: std::sync::Arc<std::sync::atomic::AtomicBool>) {
        let mut offset: i64 = 0;
        while running.load(std::sync::atomic::Ordering::Relaxed) {
            match self.get_updates(offset) {
                Ok(updates) => {
                    for update in updates {
                        offset = update.update_id + 1;
                        if let Some(msg) = &update.message {
                            if let Err(e) = self.forward_to_gateway(msg) {
                                eprintln!("[telegram] gateway forward failed: {e}");
                            }
                        }
                    }
                }
                Err(e) => {
                    eprintln!("[telegram] getUpdates error: {e}");
                    std::thread::sleep(std::time::Duration::from_secs(5));
                }
            }
        }
    }
}

impl Default for TelegramClient {
    fn default() -> Self {
        Self {
            token: String::new(),
            gateway_url: "http://localhost:8080".to_string(),
            owner_token: String::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn channel_name_is_telegram() {
        assert_eq!(channel_name(), "telegram");
    }

    #[test]
    fn bot_token_fails_without_env() {
        std::env::remove_var("HM_TELEGRAM_BOT_TOKEN");
        assert!(bot_token().is_err());
    }
}
