//! `hm-sessions` — persistente Gesprächsverläufe.
//!
//! `SessionStore` verwaltet benannte, persistente Gesprächsverläufe im
//! Arbeitsspeicher. Nachrichten werden in Insertion-Order gespeichert.
//! Persistenz (Ablegen in Dateisystem/Storage) ist über `export_json` /
//! `import_json` möglich.

pub const NAME: &str = "sessions";

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;
use uuid::Uuid;

/// Eine einzelne Nachricht in einer Session.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    /// Wer hat diese Nachricht gesendet (z.B. "user", "assistant", "system").
    pub role: String,
    /// Nachrichteninhalt.
    pub content: String,
    /// Unix-Timestamp der Erstellung (Sekunden seit Epoch).
    pub created_at: u64,
}

impl Message {
    pub fn new(role: impl Into<String>, content: impl Into<String>) -> Self {
        Self {
            role: role.into(),
            content: content.into(),
            created_at: unix_now(),
        }
    }
}

/// Eine benannte Gesprächssession mit Metadaten und Nachrichtenhistorie.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    /// Eindeutige Session-ID (UUID v4).
    pub id: String,
    /// Benutzerlesbarer Name (z.B. "gateway-debug-2026-07").
    pub name: String,
    /// Unix-Timestamp der Erstellung.
    pub created_at: u64,
    /// Unix-Timestamp der letzten Nachricht.
    pub updated_at: u64,
    /// Geordnete Nachrichtenhistorie.
    pub messages: Vec<Message>,
}

impl Session {
    pub fn new(name: impl Into<String>) -> Self {
        let now = unix_now();
        Self {
            id: Uuid::new_v4().to_string(),
            name: name.into(),
            created_at: now,
            updated_at: now,
            messages: Vec::new(),
        }
    }

    /// Fügt eine neue Nachricht hinzu und aktualisiert `updated_at`.
    pub fn push(&mut self, msg: Message) {
        self.updated_at = unix_now();
        self.messages.push(msg);
    }

    /// Gibt die letzten `n` Nachrichten zurück (für Context-Window-Management).
    pub fn tail(&self, n: usize) -> &[Message] {
        let start = self.messages.len().saturating_sub(n);
        &self.messages[start..]
    }
}

fn unix_now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

/// Thread-sicherer In-Memory-Store für Sessions.
#[derive(Clone, Default)]
pub struct SessionStore {
    inner: Arc<Mutex<HashMap<String, Session>>>,
}

impl SessionStore {
    pub fn new() -> Self {
        Self::default()
    }

    /// Erstellt eine neue Session und gibt ihre ID zurück.
    pub async fn create(&self, name: impl Into<String>) -> String {
        let session = Session::new(name);
        let id = session.id.clone();
        self.inner.lock().await.insert(id.clone(), session);
        id
    }

    /// Gibt eine Session per ID zurück (geklont).
    pub async fn get(&self, id: &str) -> Option<Session> {
        self.inner.lock().await.get(id).cloned()
    }

    /// Gibt eine Session per Name zurück (erste Übereinstimmung).
    pub async fn get_by_name(&self, name: &str) -> Option<Session> {
        self.inner
            .lock()
            .await
            .values()
            .find(|s| s.name == name)
            .cloned()
    }

    /// Fügt eine Nachricht zu einer Session hinzu.
    /// Gibt `false` zurück wenn die Session nicht existiert.
    pub async fn append(&self, session_id: &str, msg: Message) -> bool {
        let mut guard = self.inner.lock().await;
        if let Some(session) = guard.get_mut(session_id) {
            session.push(msg);
            true
        } else {
            false
        }
    }

    /// Löscht eine Session. Gibt `true` zurück wenn sie existierte.
    pub async fn delete(&self, id: &str) -> bool {
        self.inner.lock().await.remove(id).is_some()
    }

    /// Listet alle Sessions (Metadaten ohne Nachrichten, sortiert nach `updated_at` desc).
    pub async fn list(&self) -> Vec<SessionSummary> {
        let guard = self.inner.lock().await;
        let mut summaries: Vec<SessionSummary> = guard
            .values()
            .map(|s| SessionSummary {
                id: s.id.clone(),
                name: s.name.clone(),
                message_count: s.messages.len(),
                created_at: s.created_at,
                updated_at: s.updated_at,
            })
            .collect();
        summaries.sort_by_key(|b| std::cmp::Reverse(b.updated_at));
        summaries
    }

    /// Exportiert alle Sessions als JSON-String (für Persistenz).
    pub async fn export_json(&self) -> String {
        let guard = self.inner.lock().await;
        serde_json::to_string(&*guard).unwrap_or_else(|_| "{}".to_string())
    }

    /// Importiert Sessions aus einem JSON-String (aus Persistenz geladen).
    pub async fn import_json(&self, json: &str) -> Result<usize, serde_json::Error> {
        let sessions: HashMap<String, Session> = serde_json::from_str(json)?;
        let count = sessions.len();
        *self.inner.lock().await = sessions;
        Ok(count)
    }
}

/// Kurzfassung einer Session ohne Nachrichtenhistorie (für Listenansichten).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionSummary {
    pub id: String,
    pub name: String,
    pub message_count: usize,
    pub created_at: u64,
    pub updated_at: u64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn create_and_retrieve_session() {
        let store = SessionStore::new();
        let id = store.create("test-session").await;
        let session = store.get(&id).await.expect("session should exist");
        assert_eq!(session.name, "test-session");
        assert!(session.messages.is_empty());
    }

    #[tokio::test]
    async fn append_message_updates_session() {
        let store = SessionStore::new();
        let id = store.create("chat").await;
        let ok = store.append(&id, Message::new("user", "Hallo MUNIN")).await;
        assert!(ok);
        let session = store.get(&id).await.unwrap();
        assert_eq!(session.messages.len(), 1);
        assert_eq!(session.messages[0].role, "user");
    }

    #[tokio::test]
    async fn tail_returns_last_n_messages() {
        let store = SessionStore::new();
        let id = store.create("tail-test").await;
        for i in 0..10 {
            store
                .append(&id, Message::new("user", format!("msg {i}")))
                .await;
        }
        let session = store.get(&id).await.unwrap();
        let tail = session.tail(3);
        assert_eq!(tail.len(), 3);
        assert_eq!(tail[2].content, "msg 9");
    }

    #[tokio::test]
    async fn delete_removes_session() {
        let store = SessionStore::new();
        let id = store.create("to-delete").await;
        assert!(store.delete(&id).await);
        assert!(store.get(&id).await.is_none());
        assert!(!store.delete(&id).await);
    }

    #[tokio::test]
    async fn export_import_roundtrip() {
        let store = SessionStore::new();
        let id = store.create("persist-me").await;
        store
            .append(&id, Message::new("assistant", "ich erinnere mich"))
            .await;
        let json = store.export_json().await;

        let store2 = SessionStore::new();
        let count = store2.import_json(&json).await.unwrap();
        assert_eq!(count, 1);
        let s = store2.get(&id).await.unwrap();
        assert_eq!(s.messages[0].content, "ich erinnere mich");
    }
}
