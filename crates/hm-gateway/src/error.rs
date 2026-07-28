//! Domain-Errors fuer hm-gateway.
//!
//! Vorher: 9 Stellen mit `Result<…, String>` — der String verliert die
//! Source-Kette (kein Downcast, kein `source()`, kein `Display` mit Pfad),
//! und ist im Test-Layer nur per `assert!(err.contains("…"))` greifbar.
//!
//! Nachher: `GatewayError` mit `thiserror`-Enum-Varianten. Jeder Aufrufer
//! kann per `?` von Stdlib-Errors (`std::io::Error`, `serde_json::Error`,
//! `hm_storage::Error`, …) konvertieren, und Tests koennen
//! `assert!(matches!(err, GatewayError::ParseInt(_)))` schreiben statt
//! String-Matching.
//!
//! `From<GatewayError> for anyhow::Error` macht das Mischen mit `anyhow!`
//! ermoeglich — die meisten Aufrufer koennen `anyhow::Result<T>`
//! beibehalten und nur die FEHLERKLASSE ist typisiert.

use thiserror::Error;

#[derive(Debug, Error)]
pub enum GatewayError {
    #[error("parse int: expected {expected}, got {actual:?}")]
    ParseInt {
        expected: &'static str,
        actual: String,
    },

    #[error("serde: {0}")]
    Serde(#[from] serde_json::Error),

    #[error("storage: {0}")]
    Storage(String),

    #[error("auth: {0}")]
    Auth(String),

    #[error("upstream: status={status} body={body}")]
    Upstream { status: u16, body: String },

    #[error("internal: {0}")]
    Internal(String),
}

impl From<std::io::Error> for GatewayError {
    fn from(err: std::io::Error) -> Self {
        GatewayError::Internal(format!("io: {err}"))
    }
}

impl From<anyhow::Error> for GatewayError {
    fn from(err: anyhow::Error) -> Self {
        GatewayError::Internal(format!("{err:#}"))
    }
}

impl From<&str> for GatewayError {
    fn from(s: &str) -> Self {
        GatewayError::Internal(s.to_string())
    }
}

impl From<String> for GatewayError {
    fn from(s: String) -> Self {
        GatewayError::Internal(s)
    }
}

/// Convenience: `Ok`-Konstruktor, der im `?`-Kontext der Tests oft
/// gesehene Form abkuerzt. `gw_ok!(value)` -> `Ok(value)`.
#[macro_export]
macro_rules! gw_ok {
    ($v:expr) => {
        Ok::<_, $crate::error::GatewayError>($v)
    };
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_int_carries_context() {
        let err = GatewayError::ParseInt {
            expected: "u16",
            actual: "abc".to_string(),
        };
        let msg = err.to_string();
        assert!(msg.contains("parse int"), "got: {msg}");
        assert!(msg.contains("u16"), "context verloren: {msg}");
    }

    #[test]
    fn serde_from_implements_from() {
        let serde_err: serde_json::Error =
            serde_json::from_str::<serde_json::Value>("not json").unwrap_err();
        let gw: GatewayError = serde_err.into();
        assert!(matches!(gw, GatewayError::Serde(_)));
    }

    #[test]
    fn upstream_keeps_status_and_body() {
        let err = GatewayError::Upstream {
            status: 502,
            body: "bad gateway".to_string(),
        };
        let msg = err.to_string();
        assert!(msg.contains("502"));
        assert!(msg.contains("bad gateway"));
    }
}
