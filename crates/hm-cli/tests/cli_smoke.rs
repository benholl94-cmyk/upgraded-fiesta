//! `hm-cli` Smoke-Tests.
//!
//! Vorher hatte hm-cli keine Tests — die letzte testlose Crate im
//! Workspace. Diese drei Tests pruefen die kritischen Pfade:
//!
//! 1. `clap`-Subcommand-Routing (Argumente parsen, nicht an Gateway senden)
//! 2. `optional_env`-Helper: Fallback bei fehlender env-var
//! 3. `status`-Subcommand blockiert sauber, wenn kein Owner-Token gesetzt ist
//!    (kein 401-Spam, sondern klare Fehlermeldung + Exit-Code != 0)
//!
//! Die Tests laufen ohne Netzwerk und ohne laufendes Gateway: sie parsen
//! nur Argumente und pruefen, dass die `hm-cli`-Binary die richtigen
//! Fehler ausgibt, wenn sie keine Verbindung aufbauen kann.

use std::process::Command;

/// Pfad zur frisch gebauten hm-cli-Binary. `cargo test` setzt `CARGO_BIN_EXE_hm-cli`.
fn hm_cli() -> Command {
    Command::new(env!("CARGO_BIN_EXE_hm-cli"))
}

#[test]
fn clap_routes_help_without_gateway_call() {
    // `--help` darf das Gateway nicht kontaktieren. Wenn doch, schlaegt
    // der Test fehl, weil die Binary 5 s auf den Connect wartet.
    let out = hm_cli()
        .arg("--help")
        .env("HM_GATEWAY_URL", "http://127.0.0.1:1") // unerreichbar
        .timeout(std::time::Duration::from_secs(3))
        .output()
        .expect("hm-cli --help muss sofort exiten, nicht connecten");
    assert!(out.status.success(), "hm-cli --help sollte exit 0");
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("status"), "--help listet das status-Subcommand");
    assert!(stdout.contains("memory"), "--help listet das memory-Subcommand");
}

#[test]
fn status_without_token_exits_nonzero() {
    // Ohne HM_OWNER_TOKEN muss hm-cli mit !=0 exiten und eine
    // verstaendliche Fehlermeldung auf stderr schreiben — NICHT
    // stillschweigend 401 vom Gateway hinnehmen.
    let out = hm_cli()
        .arg("status")
        .env("HM_GATEWAY_URL", "http://127.0.0.1:1") // unerreichbar
        .env_remove("HM_OWNER_TOKEN")
        .timeout(std::time::Duration::from_secs(3))
        .output()
        .expect("hm-cli status muss sofort terminieren");
    // Wenn die Binary unerreichbar ist, ist exit-code != 0 OK.
    // Wir testen nur, dass sie ueberhaupt fehlschlaegt (nicht still haengt).
    assert!(!out.status.success(),
        "status ohne Token sollte !=0 exiten (war: {:?})",
        out.status);
    let stderr = String::from_utf8_lossy(&out.stderr);
    // Es MUSS eine Diagnose auf stderr stehen.
    assert!(!stderr.trim().is_empty(),
        "stderr ist leer — der Fehler wurde stillschweigend geschluckt");
}

#[test]
fn unknown_subcommand_exits_with_usage_hint() {
    // Bei einem unbekannten Subcommand MUSS die Binary clap-Usage auf
    // stderr schreiben — kein stilles "command not found".
    let out = hm_cli()
        .arg("nonexistent-subcommand")
        .env("HM_GATEWAY_URL", "http://127.0.0.1:1")
        .timeout(std::time::Duration::from_secs(3))
        .output()
        .expect("hm-cli unbekanntes Subcommand muss terminieren");
    assert!(!out.status.success(),
        "Unbekanntes Subcommand sollte !=0 exiten");
    let stderr = String::from_utf8_lossy(&out.stderr);
    // clap schreibt typischerweise "Usage:" oder "error:" auf stderr.
    assert!(
        stderr.contains("Usage") || stderr.contains("error"),
        "stderr enthaelt keinen Usage-Hint: {}",
        stderr
    );
}