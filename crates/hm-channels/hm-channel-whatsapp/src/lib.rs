//! `hm-channel-whatsapp` — WhatsApp Business API Adapter für hm-gateway.
//!
//! Verarbeitet eingehende Webhooks von der WhatsApp Business Cloud API
//! (Meta Graph API) und leitet Nachrichten als Tasks ans Gateway weiter.
//! Ausgehende Nachrichten werden via `POST /messages` zugestellt.
//!
//! Env-Vars:
//!   `HM_WHATSAPP_BOT_TOKEN`    — WhatsApp API-Token (Bearer, von Meta Dev Portal)
//!   `HM_WHATSAPP_PHONE_ID`     — Phone Number ID (aus Meta Business Manager)
//!   `HM_WHATSAPP_VERIFY_TOKEN` — Webhook-Verification-Token (selbst gewählt)
//!   `HM_GATEWAY_URL`           — Gateway-URL (Standard: http://localhost:8080)
//!   `HM_OWNER_TOKEN`           — Gateway-Auth-Token

pub fn channel_name() -> &'static str {
    "whatsapp"
}

/// Lädt den API-Token aus `HM_WHATSAPP_BOT_TOKEN`.
pub fn bot_token() -> anyhow::Result<String> {
    hm_auth::load_bot_token(channel_name())
}

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

// ── WhatsApp Webhook Payload Typen ────────────────────────────────────────────

/// Eingehender Webhook von der WhatsApp Business Cloud API.
#[derive(Debug, Deserialize, Serialize)]
pub struct WhatsAppWebhook {
    pub object: String,
    pub entry: Vec<WhatsAppEntry>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct WhatsAppEntry {
    pub id: String,
    #[serde(default)]
    pub changes: Vec<WhatsAppChange>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct WhatsAppChange {
    pub value: WhatsAppValue,
    pub field: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct WhatsAppValue {
    pub messaging_product: String,
    #[serde(default)]
    pub messages: Vec<WhatsAppMessage>,
    #[serde(default)]
    pub metadata: Option<WhatsAppMetadata>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct WhatsAppMessage {
    pub from: String,
    pub id: String,
    pub timestamp: String,
    #[serde(rename = "type")]
    pub message_type: String,
    pub text: Option<WhatsAppText>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct WhatsAppText {
    pub body: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct WhatsAppMetadata {
    pub display_phone_number: String,
    pub phone_number_id: String,
}

// ── Client ────────────────────────────────────────────────────────────────────

pub struct WhatsAppClient {
    pub token: String,
    pub phone_number_id: String,
    pub verify_token: String,
    pub gateway_url: String,
    pub owner_token: String,
}

impl WhatsAppClient {
    pub fn new() -> anyhow::Result<Self> {
        Ok(Self {
            token: bot_token()?,
            phone_number_id: std::env::var("HM_WHATSAPP_PHONE_ID").unwrap_or_default(),
            verify_token: std::env::var("HM_WHATSAPP_VERIFY_TOKEN").unwrap_or_default(),
            gateway_url: std::env::var("HM_GATEWAY_URL")
                .unwrap_or_else(|_| "http://localhost:8080".to_string()),
            owner_token: std::env::var("HM_OWNER_TOKEN").unwrap_or_default(),
        })
    }

    /// Verifiziert einen eingehenden Webhook-Verification-Request von Meta.
    /// Gibt `hub.challenge` zurück wenn `hub.verify_token` übereinstimmt.
    pub fn verify_webhook(
        &self,
        mode: &str,
        token: &str,
        challenge: &str,
    ) -> Option<String> {
        if mode == "subscribe" && token == self.verify_token {
            Some(challenge.to_string())
        } else {
            None
        }
    }

    /// Sendet eine Text-Nachricht via WhatsApp Business Cloud API.
    /// Erfordert HTTPS.
    pub fn send_message(&self, to: &str, text: &str) -> Result<(), anyhow::Error> {
        anyhow::bail!(
            "WhatsApp API requires HTTPS (Meta Graph API). \
             Add rustls to this crate. to={to}, text_len={}",
            text.len()
        )
    }

    /// Verarbeitet einen eingehenden Webhook und leitet Nachrichten ans Gateway weiter.
    pub fn handle_webhook(&self, webhook: &WhatsAppWebhook) -> Result<usize, anyhow::Error> {
        if webhook.object != "whatsapp_business_account" {
            return Ok(0);
        }

        let mut forwarded = 0;
        for entry in &webhook.entry {
            for change in &entry.changes {
                if change.field != "messages" {
                    continue;
                }
                for msg in &change.value.messages {
                    if msg.message_type == "text" {
                        if let Some(text) = &msg.text {
                            self.forward_to_gateway(&msg.from, &text.body, &msg.id)?;
                            forwarded += 1;
                        }
                    }
                }
            }
        }
        Ok(forwarded)
    }

    fn forward_to_gateway(
        &self,
        from: &str,
        text: &str,
        message_id: &str,
    ) -> Result<(), anyhow::Error> {
        use std::io::{Read, Write};
        use std::net::TcpStream;

        let task_payload = json!({
            "task_type": "whatsapp-message",
            "payload": {
                "from": from,
                "text": text,
                "message_id": message_id,
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

impl Default for WhatsAppClient {
    fn default() -> Self {
        Self {
            token: String::new(),
            phone_number_id: String::new(),
            verify_token: String::new(),
            gateway_url: "http://localhost:8080".to_string(),
            owner_token: String::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn channel_name_is_whatsapp() {
        assert_eq!(channel_name(), "whatsapp");
    }

    #[test]
    fn verify_webhook_correct_token() {
        let client = WhatsAppClient {
            verify_token: "secret123".to_string(),
            ..Default::default()
        };
        let result = client.verify_webhook("subscribe", "secret123", "abc_challenge");
        assert_eq!(result, Some("abc_challenge".to_string()));
    }

    #[test]
    fn verify_webhook_wrong_token() {
        let client = WhatsAppClient {
            verify_token: "secret123".to_string(),
            ..Default::default()
        };
        let result = client.verify_webhook("subscribe", "wrong_token", "abc");
        assert!(result.is_none());
    }

    #[test]
    fn handle_webhook_ignores_non_wa_objects() {
        let client = WhatsAppClient::default();
        let webhook = WhatsAppWebhook {
            object: "instagram".to_string(),
            entry: vec![],
        };
        let count = client.handle_webhook(&webhook).unwrap();
        assert_eq!(count, 0);
    }
}
