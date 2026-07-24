/// Plugin-Name — entspricht dem `task_type`-Eintrag in `config/plugins.json`.
pub const NAME: &str = "ops-tool";

/// Erlaubte Operationen (gespiegelt aus `main.rs` für externe Tests).
pub const ALLOWED_OPERATIONS: &[&str] = &[
    "gateway_status",
    "gateway_logs",
    "disk_usage",
    "memory_usage",
];
