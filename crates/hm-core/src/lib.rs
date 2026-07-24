//! Gemeinsame Typen und Hilfsfunktionen für den gesamten hm-Workspace.
//!
//! Alle Crates können dieses Crate als Dependency einbinden um einheitliche
//! Fehlertypen, Versionsinfos und Config-Hilfsfunktionen zu verwenden.

/// Workspace-weite Version (gespiegelt aus `Cargo.toml`).
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Identifiziert eine Workspace-Komponente namentlich.
pub trait ComponentName {
    fn component_name() -> &'static str;
}

/// Einheitlicher Fehlertyp für alle hm-Komponenten.
#[derive(Debug)]
pub enum HmError {
    /// Ungültige Konfiguration (fehlende Env-Var, ungültiger Wert).
    Config(String),
    /// I/O-Fehler (Datei nicht lesbar, Verbindung abgelehnt).
    Io(String),
    /// Authentifizierungsfehler (Token fehlt oder ungültig).
    Auth(String),
    /// Allgemeiner Fehler mit freier Beschreibung.
    Other(String),
}

impl std::fmt::Display for HmError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Config(s) => write!(f, "config error: {s}"),
            Self::Io(s) => write!(f, "I/O error: {s}"),
            Self::Auth(s) => write!(f, "auth error: {s}"),
            Self::Other(s) => write!(f, "{s}"),
        }
    }
}

impl std::error::Error for HmError {}

impl From<std::io::Error> for HmError {
    fn from(e: std::io::Error) -> Self {
        Self::Io(e.to_string())
    }
}

impl From<anyhow::Error> for HmError {
    fn from(e: anyhow::Error) -> Self {
        Self::Other(e.to_string())
    }
}

/// Liest eine Pflicht-Umgebungsvariable oder gibt einen `HmError::Config` zurück.
pub fn require_env(key: &str) -> Result<String, HmError> {
    std::env::var(key)
        .map_err(|_| HmError::Config(format!("required environment variable {key} is not set")))
}

/// Liest eine optionale Umgebungsvariable, gibt `None` zurück wenn nicht gesetzt.
pub fn optional_env(key: &str) -> Option<String> {
    std::env::var(key).ok().filter(|v| !v.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn require_env_missing_returns_config_error() {
        let err = require_env("__HM_CORE_NONEXISTENT_VAR__").unwrap_err();
        assert!(matches!(err, HmError::Config(_)));
        assert!(err.to_string().contains("__HM_CORE_NONEXISTENT_VAR__"));
    }

    #[test]
    fn optional_env_missing_returns_none() {
        assert!(optional_env("__HM_CORE_NONEXISTENT_VAR__").is_none());
    }

    #[test]
    fn hm_error_display_includes_message() {
        let e = HmError::Auth("token invalid".to_string());
        assert!(e.to_string().contains("token invalid"));
    }
}
