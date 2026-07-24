//! `hm-channel-slack` — Slack Events API Adapter für hm-gateway.
//!
//! Empfängt eingehende Slack Events via Socket Mode (WebSocket) oder
//! Events API (HTTP-Webhook) und leitet sie als Tasks ans Gateway weiter.
//!
//! Env-Vars:
//!   `HM_SLACK_BOT_TOKEN`   — Slack Bot-Token (xoxb-...)
//!   `HM_SLACK_APP_TOKEN`   — Slack App-Token für Socket Mode (xapp-...)
//!   `HM_GATEWAY_URL`       — Gateway-URL (Standard: http://localhost:8080)
//!   `HM_OWNER_TOKEN`       — Gateway-Auth-Token

pub fn channel_name() -> &'static str {
    "slack"
}

/// Lädt den Bot-Token aus `HM_SLACK_BOT_TOKEN`.
pub fn bot_token() -> anyhow::Result<String> {
    hm_auth::load_bot_token(channel_name())
}

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

// ── Slack Event Typen ─────────────────────────────────────────────────────────

/// Slack Events API Callback-Payload.
#[derive(Debug, Deserialize, Serialize)]
pub struct SlackEvent {
    #[serde(rename = "type")]
    pub event_type: String,
    #[serde(default)]
    pub event: Option<SlackMessageEvent>,
    #[serde(default)]
    pub challenge: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct SlackMessageEvent {
    #[serde(rename = "type")]
    pub event_type: String,
    pub user: Option<String>,
    pub text: Option<String>,
    pub channel: String,
    pub ts: String,
    #[serde(default)]
    pub bot_id: Option<String>,
}

// ── Client ────────────────────────────────────────────────────────────────────

pub struct SlackClient {
    pub bot_token: String,
    pub app_token: String,
    pub gateway_url: String,
    pub owner_token: String,
}

impl SlackClient {
    pub fn new() -> anyhow::Result<Self> {
        Ok(Self {
            bot_token: bot_token()?,
            app_token: std::env::var("HM_SLACK_APP_TOKEN").unwrap_or_default(),
            gateway_url: std::env::var("HM_GATEWAY_URL")
                .unwrap_or_else(|_| "http://localhost:8080".to_string()),
            owner_token: std::env::var("HM_OWNER_TOKEN").unwrap_or_default(),
        })
    }

    /// Sendet eine Slack-Nachricht an einen Channel via `chat.postMessage`.
    /// Erfordert HTTPS.
    pub fn post_message(&self, channel: &str, text: &str) -> Result<(), anyhow::Error> {
        anyhow::bail!(
            "Slack API requires HTTPS. Add rustls to this crate. \
             channel={channel}, text_len={}",
            text.len()
        )
    }

    /// Verarbeitet ein eingehendes Slack Event.
    /// Gibt bei URL-Verification den challenge-String zurück.
    pub fn handle_event(&self, event: &SlackEvent) -> Result<Option<String>, anyhow::Error> {
        // URL-Verifizierung für Events API Setup
        if event.event_type == "url_verification" {
            return Ok(event.challenge.clone());
        }

        if let Some(msg) = &event.event {
            // Bot-Nachrichten ignorieren
            if msg.bot_id.is_some() {
                return Ok(None);
            }
            if let Some(text) = &msg.text {
                if !text.is_empty() {
                    self.forward_to_gateway(&msg.channel, text, msg.user.as_deref())?;
                }
            }
        }

        Ok(None)
    }

    fn forward_to_gateway(
        &self,
        channel: &str,
        text: &str,
        user: Option<&str>,
    ) -> Result<(), anyhow::Error> {
        use std::io::{Read, Write};
        use std::net::TcpStream;

        let task_payload = json!({
            "task_type": "slack-message",
            "payload": {
                "channel": channel,
                "text": text,
                "user": user,
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

impl Default for SlackClient {
    fn default() -> Self {
        Self {
            bot_token: String::new(),
            app_token: String::new(),
            gateway_url: "http://localhost:8080".to_string(),
            owner_token: String::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn channel_name_is_slack() {
        assert_eq!(channel_name(), "slack");
    }

    #[test]
    fn url_verification_returns_challenge() {
        let client = SlackClient::default();
        let event = SlackEvent {
            event_type: "url_verification".to_string(),
            event: None,
            challenge: Some("test_challenge_xyz".to_string()),
        };
        let result = client.handle_event(&event).unwrap();
        assert_eq!(result, Some("test_challenge_xyz".to_string()));
    }

    #[test]
    fn bot_message_is_ignored() {
        let client = SlackClient::default();
        let event = SlackEvent {
            event_type: "event_callback".to_string(),
            challenge: None,
            event: Some(SlackMessageEvent {
                event_type: "message".to_string(),
                user: None,
                text: Some("Bot message".to_string()),
                channel: "C123".to_string(),
                ts: "123.456".to_string(),
                bot_id: Some("B123".to_string()),
            }),
        };
        let result = client.handle_event(&event).unwrap();
        assert!(result.is_none());
    }
}
