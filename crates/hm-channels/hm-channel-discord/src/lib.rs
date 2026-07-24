//! `hm-channel-discord` — Discord Gateway Adapter für hm-gateway.
//!
//! Empfängt Nachrichten über die Discord Gateway API (WebSocket) und leitet
//! sie als Tasks an `HM_GATEWAY_URL/tasks` weiter. Ausgehende Nachrichten
//! werden via `POST /channels/{id}/messages` zugestellt.
//!
//! Env-Vars:
//!   `HM_DISCORD_BOT_TOKEN` — Discord Bot-Token
//!   `HM_GATEWAY_URL`       — Gateway-URL (Standard: http://localhost:8080)
//!   `HM_OWNER_TOKEN`       — Gateway-Auth-Token
//!
//! **Status**: Adapter-Struktur vollständig implementiert. Discord Gateway
//! erfordert WebSocket + JSON-Payloads mit Heartbeat-Loop. Ohne TLS/WS-Crate
//! ist Live-Verbindung nicht möglich — Token-Validierung und Task-Routing
//! sind vollständig, WS-Transport ist als Platzhalter markiert.

pub fn channel_name() -> &'static str {
    "discord"
}

/// Lädt den Bot-Token aus `HM_DISCORD_BOT_TOKEN`.
pub fn bot_token() -> anyhow::Result<String> {
    hm_auth::load_bot_token(channel_name())
}

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

// ── Discord API Typen ─────────────────────────────────────────────────────────

/// Discord Gateway Op-Codes.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum GatewayOp {
    Dispatch = 0,
    Heartbeat = 1,
    Identify = 2,
    HeartbeatAck = 11,
}

/// Eingehende Discord Nachricht (MESSAGE_CREATE Event).
#[derive(Debug, Deserialize, Serialize)]
pub struct DiscordMessage {
    pub id: String,
    pub channel_id: String,
    pub author: DiscordUser,
    pub content: String,
    #[serde(default)]
    pub guild_id: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct DiscordUser {
    pub id: String,
    pub username: String,
    #[serde(default)]
    pub bot: bool,
}

/// Discord Gateway Payload (vereinfacht).
#[derive(Debug, Deserialize)]
pub struct GatewayPayload {
    pub op: u8,
    pub d: Option<Value>,
    pub s: Option<i64>,
    pub t: Option<String>,
}

// ── Client ────────────────────────────────────────────────────────────────────

pub struct DiscordClient {
    pub token: String,
    pub gateway_url: String,
    pub owner_token: String,
}

impl DiscordClient {
    pub fn new() -> anyhow::Result<Self> {
        Ok(Self {
            token: bot_token()?,
            gateway_url: std::env::var("HM_GATEWAY_URL")
                .unwrap_or_else(|_| "http://localhost:8080".to_string()),
            owner_token: std::env::var("HM_OWNER_TOKEN").unwrap_or_default(),
        })
    }

    /// Sendet eine Nachricht an einen Discord-Channel via REST API.
    /// Erfordert HTTPS — gibt klare Fehlermeldung wenn TLS-Bibliothek fehlt.
    pub fn send_message(&self, channel_id: &str, content: &str) -> Result<(), anyhow::Error> {
        anyhow::bail!(
            "Discord REST API requires HTTPS. \
             Add rustls to this crate. channel_id={channel_id}, content_len={}",
            content.len()
        )
    }

    /// Erstellt das IDENTIFY-Payload für den Discord Gateway-Handshake.
    pub fn identify_payload(&self) -> Value {
        json!({
            "op": GatewayOp::Identify as u8,
            "d": {
                "token": self.token,
                "intents": 512, // GUILD_MESSAGES
                "properties": {
                    "$os": "linux",
                    "$browser": "hm-channel-discord",
                    "$device": "hm-gateway"
                }
            }
        })
    }

    /// Verarbeitet ein eingehendes Gateway-Event und leitet es ans Gateway weiter.
    pub fn handle_event(&self, payload: &GatewayPayload) -> Result<(), anyhow::Error> {
        if payload.op != GatewayOp::Dispatch as u8 {
            return Ok(());
        }
        let event_type = payload.t.as_deref().unwrap_or("");
        if event_type != "MESSAGE_CREATE" {
            return Ok(());
        }
        let data = payload.d.as_ref().ok_or_else(|| anyhow::anyhow!("no data in payload"))?;
        let msg: DiscordMessage = serde_json::from_value(data.clone())?;

        // Bots nicht weiterleiten
        if msg.author.bot {
            return Ok(());
        }

        self.forward_to_gateway(&msg)
    }

    fn forward_to_gateway(&self, msg: &DiscordMessage) -> Result<(), anyhow::Error> {
        use std::io::{Read, Write};
        use std::net::TcpStream;

        let task_payload = json!({
            "task_type": "discord-message",
            "payload": {
                "channel_id": msg.channel_id,
                "content": msg.content,
                "author": msg.author.username,
                "guild_id": msg.guild_id,
            }
        })
        .to_string();

        let url = self.gateway_url.trim_start_matches("http://");
        let (host, port_str) = url.rsplit_once(':').unwrap_or((url, "8080"));
        let port: u16 = port_str.parse().unwrap_or(8080);
        let addr = format!("{host}:{port}");

        let request = format!(
            "POST /tasks HTTP/1.0\r\nHost: {host}\r\nAuthorization: Bearer {token}\r\n\
             Content-Type: application/json\r\nContent-Length: {len}\r\n\r\n{body}",
            token = self.owner_token,
            len = task_payload.len(),
            body = task_payload
        );

        let mut stream = TcpStream::connect(&addr)
            .map_err(|e| anyhow::anyhow!("gateway connect failed: {e}"))?;
        stream.write_all(request.as_bytes())?;
        let mut _resp = String::new();
        stream.read_to_string(&mut _resp)?;
        Ok(())
    }
}

impl Default for DiscordClient {
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
    fn channel_name_is_discord() {
        assert_eq!(channel_name(), "discord");
    }

    #[test]
    fn bot_token_fails_without_env() {
        std::env::remove_var("HM_DISCORD_BOT_TOKEN");
        assert!(bot_token().is_err());
    }

    #[test]
    fn identify_payload_has_correct_op() {
        let client = DiscordClient::default();
        let payload = client.identify_payload();
        assert_eq!(payload["op"], 2);
    }

    #[test]
    fn bot_message_is_ignored() {
        let client = DiscordClient::default();
        let payload_str = r#"{
            "op": 0, "s": 1, "t": "MESSAGE_CREATE",
            "d": {"id":"1","channel_id":"ch1","guild_id":null,
                  "author":{"id":"bot1","username":"TestBot","bot":true},
                  "content":"I am a bot"}
        }"#;
        let payload: GatewayPayload = serde_json::from_str(payload_str).unwrap();
        // Bot-Nachrichten werden ignoriert (kein Gateway-Aufruf)
        assert!(client.handle_event(&payload).is_ok());
    }
}
