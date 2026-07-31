"""test_wave1_smoke.py — Wave 1 Liefer-Belege.

Jeder Test hier ist eine statische Wache darueber, dass die in
`/home/box/.claude/plans/zippy-snacking-ritchie.md` (Wave 1) versprochenen
Aenderungen tatsaechlich im Repo stehen. Wenn eine Wache faellt, ist
eine der drei Wellen-Lieferungen zurueckgenommen worden -- und genau das
soll dieser Test laut werden lassen.

Pytest ist die einzige Voraussetzung; der Test braucht weder cargo
noch einen laufenden Container.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1.7 — Auto-Rollback-Workflow ist im Repo
# ---------------------------------------------------------------------------

def test_auto_rollback_workflow_exists():
    """Der Workflow, der laut HANDOFF.md s2-7 verschwunden war, ist wieder da."""
    workflow = REPO / ".github/workflows/auto-rollback.yml"
    assert workflow.is_file(), f"{workflow} fehlt -- Auto-Rollback ist nicht in main"
    text = workflow.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text, "Auto-Rollback braucht mindestens workflow_dispatch"
    # workflow_run ist absichtlich auskommentiert (s2-18 "vor Wiederinbetriebnahme pruefen")
    assert "scripts/auto_rollback_ctx.py" in text, "Auto-Rollback muss decide() rufen"


def test_auto_rollback_uses_allowlist_not_blocklist():
    """Die Mechanik ruft `decide()` -- die Allowlist liegt in auto_rollback_ctx.py,
    Blocklisten waeren in der YAML selbst, was HANDOFF.md s2-5 abgelehnt hat."""
    helper = (REPO / "scripts/auto_rollback_ctx.py").read_text(encoding="utf-8")
    assert "ALLOWLIST" in helper, "auto_rollback_ctx.py muss eine ALLOWLIST-Konstante haben"
    # Keine echte englische "blocklist" (Wort mit Wortgrenzen, case-insensitive)
    # und nicht `if conclusion == "failure"` als alleiniges Kriterium.
    assert re.search(r"\bblocklist\b", helper, re.IGNORECASE) is None, (
        "Blockliste gehoert nicht in die Entscheidung (ALLOWLIST only)"
    )
    # Eine isolierte "failure -> REVERT"-Regel ohne Begleitfaelle waere eine
    # Blockliste in der Mechanik selbst.
    failure_lines = [
        line for line in helper.splitlines()
        if re.match(r'\s*[\'"]failure[\'"]\s*[:=]\s*[\'"]?REVERT', line)
    ]
    assert len(failure_lines) >= 1, (
        "Auto-Rollback muss 'failure' mindestens als REVERT kennen"
    )


# ---------------------------------------------------------------------------
# 1.5 — LocalFsStorage::delete lügt nicht mehr
# ---------------------------------------------------------------------------

def test_storage_delete_returns_bool():
    """`FileStorage::delete` muss `Result<bool>` zurueckgeben -- die alte
    `Result<()>`-Form hat NotFound in Ok stillschweigend kollabiert."""
    storage = _read("crates/hm-storage/src/lib.rs")
    assert "async fn delete(&self, key: &str) -> anyhow::Result<bool>" in storage, (
        "FileStorage::delete muss Result<bool> zurueckgeben"
    )
    # LocalFsStorage::delete muss true bei Erfolg, false bei NotFound liefern
    assert re.search(
        r"async fn delete\(&self, key: &str\) -> anyhow::Result<bool>\s*\{[^}]*Ok\(true\)[^}]*Ok\(false\)",
        storage,
        re.DOTALL,
    ), "LocalFsStorage::delete muss true/false explizit kodieren, nicht Ok(())"


def test_storage_delete_tests_cover_both_branches():
    storage = _read("crates/hm-storage/src/lib.rs")
    assert "delete_returns_false_when_missing" in storage, (
        "Es fehlt ein expliziter Test, dass delete false bei fehlendem Key liefert"
    )
    assert "delete_returns_true_when_present" in storage, (
        "Es fehlt ein expliziter Test, dass delete true bei vorhandenem Key liefert"
    )


def test_gateway_storage_delete_returns_existed_flag():
    """Der Gateway-Handler muss `existed: true|false` in die Antwort schreiben."""
    main = _read("crates/hm-gateway/src/main.rs")
    assert '"existed": true' in main, "storage_delete muss existed:true bei 200 ausgeben"
    assert '"existed": false' in main, "storage_delete muss existed:false bei 404 ausgeben"


# ---------------------------------------------------------------------------
# 1.6 — gateway_service.py ist weg
# ---------------------------------------------------------------------------

def test_gateway_service_py_removed():
    """Der stdlib-Platzhalter ist geloescht; das echte Gateway baut die compose-Datei."""
    ghost = REPO / "deploy/gateway_service.py"
    assert not ghost.exists(), f"{ghost} existiert noch -- sollte geloescht sein"
    # Compose-File baut das echte Gateway via Dockerfile
    compose = _read("deploy/fullstack-compose.yml")
    assert "dockerfile: Dockerfile" in compose, "Compose-File muss Dockerfile verwenden"


def test_install_script_no_longer_references_ghost():
    install = _read("install/ashell_sync_fullstack_files_v2.py")
    assert "gateway_service.py" not in install, (
        "install/ashell_sync_fullstack_files_v2.py zieht die geloeschte Datei noch"
    )


# ---------------------------------------------------------------------------
# 1.1–1.4 — TLS-Feature-Flag in allen 5 betroffenen Crates
# ---------------------------------------------------------------------------

def test_workspace_has_rustls_dep():
    cargo = _read("Cargo.toml")
    assert "rustls" in cargo, "Workspace-Cargo.toml braucht rustls als geteilte Dep"
    assert "webpki-roots" in cargo, "Workspace-Cargo.toml braucht webpki-roots"


def test_tls_feature_in_all_four_channels_and_tool_web():
    """Jeder Kanal und hm-tool-web haben ein opt-in `tls`-Feature."""
    for crate in [
        "crates/hm-channels/hm-channel-telegram",
        "crates/hm-channels/hm-channel-discord",
        "crates/hm-channels/hm-channel-slack",
        "crates/hm-channels/hm-channel-whatsapp",
        "crates/hm-tools/hm-tool-web",
    ]:
        toml = _read(f"{crate}/Cargo.toml")
        assert "tls" in toml, f"{crate}/Cargo.toml braucht ein tls-Feature"
        # optionale Deps, damit das Default-Build keinen rustls-Overhead hat
        assert "optional" in toml, f"{crate}/Cargo.toml: rustls sollte optional sein"


def test_channels_have_honest_bail_when_tls_off():
    """Ohne `tls`-Feature geben alle vier Channels einen klaren 'build with
    --features tls'-Hinweis -- lautloser 'mache nichts' waere genau die
    Bug-Klasse, die hier schon einmal Nachrichten verschluckt hat."""
    for crate, file in [
        ("telegram", "crates/hm-channels/hm-channel-telegram/src/lib.rs"),
        ("discord",  "crates/hm-channels/hm-channel-discord/src/lib.rs"),
        ("slack",    "crates/hm-channels/hm-channel-slack/src/lib.rs"),
        ("whatsapp", "crates/hm-channels/hm-channel-whatsapp/src/lib.rs"),
    ]:
        text = _read(file)
        assert "Build this crate with --features tls" in text, (
            f"{crate} ({file}) braucht eine klare 'build with --features tls' Meldung"
        )


def test_tool_web_honest_bail_when_tls_off():
    text = _read("crates/hm-tools/hm-tool-web/src/lib.rs")
    assert "--features tls" in text, (
        "hm-tool-web braucht eine klare 'build with --features tls' Meldung"
    )


def test_hm_sdk_tls_module_exists():
    """hm-sdk::tls ist der gemeinsame HTTPS-Client -- ohne dieses Modul
    wuerde jeder Kanal seinen eigenen rustls-Code duplizieren."""
    tls_rs = REPO / "crates/hm-sdk/src/tls.rs"
    assert tls_rs.is_file(), "hm-sdk/src/tls.rs fehlt"
    text = tls_rs.read_text(encoding="utf-8")
    assert "pub async fn post" in text, "hm-sdk::tls::post fehlt"
    assert "pub async fn get" in text, "hm-sdk::tls::get fehlt"
    # Stub-Modus ohne Feature: muss klar fehlschlagen, nicht unimplemented!()
    assert "requires the 'tls' feature" in text, "Stub-Modus nennt das fehlende Feature"


# ---------------------------------------------------------------------------
# 1.8 / 1.9 — Cargo.lock + munin-state.json getrackt
# ---------------------------------------------------------------------------

def test_cargo_lock_no_longer_gitignored():
    gi = _read(".gitignore")
    # Kommentarzeilen zaehlen nicht; wir suchen den reinen Pattern-Eintrag.
    pattern_lines = [
        line for line in gi.splitlines()
        if line.strip() == "Cargo.lock" and not line.lstrip().startswith("#")
    ]
    assert not pattern_lines, "Cargo.lock darf nicht mehr in .gitignore stehen (Pattern gefunden)"


def test_munin_state_no_longer_gitignored():
    gi = _read(".gitignore")
    pattern_lines = [
        line for line in gi.splitlines()
        if line.strip() == ".claude/persona/munin-state.json"
        and not line.lstrip().startswith("#")
    ]
    assert not pattern_lines, "munin-state.json darf nicht mehr in .gitignore stehen"


def test_ci_yml_generates_lockfile():
    """ci.yml ruft cargo generate-lockfile vor cargo check --workspace auf."""
    ci = _read(".github/workflows/ci.yml")
    # Position: muss VOR cargo check kommen.
    assert ci.index("cargo generate-lockfile") < ci.index("cargo check --workspace"), (
        "cargo generate-lockfile muss vor cargo check --workspace stehen"
    )


# ---------------------------------------------------------------------------
# 1.10 — HUGIN-Sync ist im CI nur noch eine WARNUNG
# ---------------------------------------------------------------------------

def test_ci_hugin_sync_is_warning_not_failure():
    ci = _read(".github/workflows/ci.yml")
    # Sucht den HUGIN-Sync-Block
    m = re.search(
        r"name: HUGIN index\.html[^\n]*\n(.*?)(?=\n      - name:|\n\n)",
        ci,
        re.DOTALL,
    )
    assert m, "HUGIN-Sync-Step fehlt in ci.yml"
    block = m.group(1)
    # exit 1 darf hier NICHT mehr stehen
    assert "exit 1" not in block, "HUGIN-Sync-Block hat noch 'exit 1' -- soll nur Warning sein"
    assert "::warning" in block, "HUGIN-Sync-Block muss eine ::warning:: Annotation nutzen"


# ---------------------------------------------------------------------------
# Decide()-Logik darf nicht stillschweigend sein
# ---------------------------------------------------------------------------

def test_auto_rollback_decide_unknown_is_hold():
    """HANDOFF.md s2-5: 'unknown' muss HOLD ergeben, sonst wiederholt sich
    der 'cancelled'-Vorfall. Diese Wache ist doppelt zu test_auto_rollback.py
    und existiert hier nur, damit der Smoke-Test allein lauffaehig ist."""
    out = subprocess.run(
        [sys.executable, "scripts/auto_rollback_ctx.py", "--conclusion", "unknown"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert out.returncode == 0, "unknown muss Exit 0 (HOLD) liefern, kein stiller Fehler"
    assert "action=HOLD" in out.stdout, "unknown muss HOLD ergeben"


def test_auto_rollback_decide_failure_is_revert():
    out = subprocess.run(
        [sys.executable, "scripts/auto_rollback_ctx.py", "--conclusion", "failure"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert out.returncode == 2, "failure muss Exit 2 (REVERT sichtbar) liefern"
    # Plain-text-Output-Format: "conclusion='failure' action=REVERT"
    m = re.search(r"action=(\w+)", out.stdout)
    assert m is not None, f"action-Feld fehlt im decide-Output: {out.stdout!r}"
    assert m.group(1) == "REVERT", (
        f"failure muss REVERT ergeben, bekam {m.group(1)!r}"
    )
