#!/usr/bin/env python3
"""
autonomy_core.py — Der autonome Existenzkern von upgraded-fiesta.

AUTONOMIE bedeutet hier:
  1. SELBSTKENNTNIS   — das System weiß jederzeit was es ist und was es tut
  2. SELBSTERHALTUNG  — es erkennt Drift und korrigiert was korrigierbar ist
  3. SELBSTDOKUMENTATION — es führt seinen eigenen Zustand ohne externen Anstoß
  4. ESKALATION       — es meldet nur was der Master entscheiden muss

Was es NICHT tut (Verfassungsgrenze):
  - Kein autonomes Push/PR/Commit
  - Kein Netzwerk-Call ohne expliziten Befehl
  - Kein Lockern von Auth oder Sicherheitsregeln
  - Keine Aktionen über den lokalen Workspace hinaus

Architektur:
  pulse()    — Herzschlag: Index update + Audit + Systemzustand erfassen
  heal()     — Selbstheilung: bekannte reparierbare Zustände automatisch fixen
  reflect()  — Selbstdokumentation: munin-state.json mit aktualem Zustand schreiben
  escalate() — Eskalation: Master-relevante Ereignisse in console-log.json schreiben
  run()      — Hauptloop: orchestriert alles mit konfigurierbarem Interval

Usage:
  python3 scripts/autonomy_core.py            # Einmal-Pulse (für Cron/Tests)
  python3 scripts/autonomy_core.py --loop     # Dauerbetrieb
  python3 scripts/autonomy_core.py --interval 60 --loop
  python3 scripts/autonomy_core.py --status   # Aktuellen Zustand ausgeben
  python3 scripts/autonomy_core.py --heal     # Nur Selbstheilung laufen lassen
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import logging
log = logging.getLogger(__name__)

# ── Pfade ─────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parent.parent
PERSONA_DIR = ROOT / ".claude" / "persona"
STATE_FILE  = PERSONA_DIR / "munin-state.json"
CORE_FILE   = PERSONA_DIR / "autonomy-state.json"
LOG_FILE    = PERSONA_DIR / "console-log.json"
INDEX_FILE  = PERSONA_DIR / "repo-index.json"
REPORT_FILE = PERSONA_DIR / "tracker-report.json"
SEC_REPORT  = PERSONA_DIR / "security-report.json"

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception as exc:
        log.warning("swallowed in autonomy_core: %s", exc)
        return default

def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

def _append_console_log(event_type: str, data: dict) -> None:
    log = _read_json(LOG_FILE, {"entries": []})
    if isinstance(log, list):
        log = {"entries": log}
    log.setdefault("entries", [])
    log["entries"].append({"ts": _now(), "type": event_type, **data})
    log["entries"] = log["entries"][-200:]
    _write_json(LOG_FILE, log)

def _run_script(args: list[str], timeout: int = 30) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            [sys.executable] + args,
            cwd=ROOT, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        log.warning("swallowed in autonomy_core: %s", exc)
        return False, str(e)

# ── Pulse — Herzschlag ────────────────────────────────────────────────────────

def pulse() -> dict:
    """
    Führt einen vollständigen Systemherzschlag durch:
    1. Inkrementeller Index-Update
    2. Synergy-Audit
    3. Systemmetriken erfassen
    Gibt einen Zustandsbericht zurück.
    """
    state = {
        "ts": _now(),
        "index_update": None,
        "audit": None,
        "metrics": None,
        "alerts": [],
    }

    # 1. Index-Update (nur mtime-geänderte Dateien)
    ok, out = _run_script(["scripts/repo_tracker.py", "update"])
    state["index_update"] = {"ok": ok, "summary": out.split("\n")[-1] if out else ""}
    if not ok:
        state["alerts"].append({"level": "WARN", "msg": f"Index-Update fehlgeschlagen: {out}"})

    # 2. Synergy-Audit
    ok, out = _run_script(["scripts/repo_tracker.py", "audit"])
    report = _read_json(REPORT_FILE, {})
    score = report.get("score", 0)
    failed_rules = [r["rule"] for r in report.get("rules", []) if not r.get("ok")]
    state["audit"] = {"ok": ok, "score": score, "failed": failed_rules}
    if failed_rules:
        state["alerts"].append({
            "level": "WARN",
            "msg": f"Synergy-Audit: {len(failed_rules)} Regel(n) fehlgeschlagen — {', '.join(failed_rules)}"
        })

    # 3. Systemmetriken
    state["metrics"] = _collect_metrics()

    return state

def _collect_metrics() -> dict:
    m: dict = {}

    # Prozesszahl
    try:
        r = subprocess.run(["ps", "aux", "--no-headers"], capture_output=True, text=True, timeout=5)
        m["process_count"] = len(r.stdout.strip().splitlines())
    except Exception as exc:
        log.warning("swallowed in autonomy_core: %s", exc)
        m["process_count"] = -1

    # Disk-Nutzung Workspace
    try:
        r = subprocess.run(["du", "-sh", str(ROOT)], capture_output=True, text=True, timeout=10)
        m["workspace_size"] = r.stdout.split()[0] if r.stdout else "?"
    except Exception as exc:
        log.warning("swallowed in autonomy_core: %s", exc)
        m["workspace_size"] = "?"

    # Letzter Git-Commit
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=ROOT, capture_output=True, text=True, timeout=5
        )
        m["last_commit"] = r.stdout.strip()
    except Exception as exc:
        log.warning("swallowed in autonomy_core: %s", exc)
        m["last_commit"] = "unknown"

    # Offene Git-Dateien (uncommitted)
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT, capture_output=True, text=True, timeout=5
        )
        m["uncommitted_files"] = len([l for l in r.stdout.strip().splitlines() if l.strip()])
    except Exception as exc:
        log.warning("swallowed in autonomy_core: %s", exc)
        m["uncommitted_files"] = -1

    # Security-Score aus letztem Report
    sec = _read_json(SEC_REPORT, {})
    m["security_score"] = sec.get("overall_score", None)
    m["security_rating"] = sec.get("rating", None)

    return m

# ── Heal — Selbstheilung ──────────────────────────────────────────────────────

def heal() -> list[dict]:
    """
    Erkennt und korrigiert bekannte, reparierbare Zustände.
    Gibt Liste von durchgeführten Heilmaßnahmen zurück.
    """
    actions: list[dict] = []

    # 1. Staler watchPID in munin-state.json
    state = _read_json(STATE_FILE, {})
    ma = state.get("masterAuthority", {})
    pid = ma.get("watchPID")
    if pid and isinstance(pid, int):
        alive = _pid_alive(pid)
        if not alive:
            ma["watchPID"] = None
            ma["watchActive"] = False
            state["masterAuthority"] = ma
            _write_json(STATE_FILE, state)
            actions.append({"action": "stale_watchpid_cleared", "pid": pid,
                            "note": "PID nicht mehr aktiv — bereinigt"})
            _log(f"heal: staler watchPID {pid} bereinigt")

    # 2. console-log.json Schema (flat list → dict mit entries)
    log = _read_json(LOG_FILE, None)
    if isinstance(log, list):
        _write_json(LOG_FILE, {"entries": log[-200:]})
        actions.append({"action": "console_log_schema_migrated",
                        "note": "flat list → {\"entries\":[...]} migriert"})
        _log("heal: console-log.json Schema migriert")

    # 3. Fehlende Pflicht-Verzeichnisse
    for d in [PERSONA_DIR, ROOT / "data" / "storage", ROOT / "diagnostics"]:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            actions.append({"action": "dir_created", "path": str(d.relative_to(ROOT))})
            _log(f"heal: Verzeichnis erstellt: {d.relative_to(ROOT)}")

    # 4. autonomy-state.json initialisieren wenn fehlend
    if not CORE_FILE.exists():
        _write_json(CORE_FILE, {
            "created": _now(),
            "pulse_count": 0,
            "heal_count": 0,
            "alerts_total": 0,
            "last_pulse": None,
            "uptime_since": _now(),
        })
        actions.append({"action": "autonomy_state_initialized",
                        "note": "autonomy-state.json neu erstellt"})

    return actions

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False

# ── Reflect — Selbstdokumentation ────────────────────────────────────────────

def reflect(pulse_state: dict, heal_actions: list[dict]) -> None:
    """
    Schreibt aktuellen Systemzustand in autonomy-state.json und
    aktualisiert munin-state.json focusArea mit aktuellem Status.
    """
    core = _read_json(CORE_FILE, {
        "created": _now(), "pulse_count": 0, "heal_count": 0,
        "alerts_total": 0, "last_pulse": None, "uptime_since": _now(),
    })

    core["pulse_count"] = core.get("pulse_count", 0) + 1
    core["heal_count"] = core.get("heal_count", 0) + len(heal_actions)
    core["alerts_total"] = core.get("alerts_total", 0) + len(pulse_state.get("alerts", []))
    core["last_pulse"] = pulse_state["ts"]
    core["last_metrics"] = pulse_state.get("metrics", {})
    core["last_audit_score"] = pulse_state.get("audit", {}).get("score")
    core["last_audit_failed"] = pulse_state.get("audit", {}).get("failed", [])
    core["last_heal_actions"] = heal_actions
    core["last_alerts"] = pulse_state.get("alerts", [])
    _write_json(CORE_FILE, core)

    # munin-state focusArea mit aktuellem Systemstatus synchronisieren
    munin = _read_json(STATE_FILE, {})
    munin["autonomyCore"] = {
        "active": True,
        "pulse_count": core["pulse_count"],
        "last_pulse": core["last_pulse"],
        "audit_score": core["last_audit_score"],
        "security_score": pulse_state.get("metrics", {}).get("security_score"),
        "uptime_since": core.get("uptime_since"),
        "open_alerts": len(pulse_state.get("alerts", [])),
    }
    _write_json(STATE_FILE, munin)

# ── Escalate — Eskalation ─────────────────────────────────────────────────────

def escalate(alerts: list[dict]) -> None:
    """
    Schreibt Master-relevante Ereignisse in console-log.json.
    Nur Dinge die der Master entscheiden muss — kein Spam.
    """
    for alert in alerts:
        _append_console_log("autonomy_alert", {
            "level": alert.get("level", "INFO"),
            "msg": alert.get("msg", ""),
            "requires_master": alert.get("level") in ("ERROR", "CRITICAL"),
        })
        _log(f"escalate [{alert.get('level')}]: {alert.get('msg')}")

# ── Status-Ausgabe ────────────────────────────────────────────────────────────

def print_status() -> None:
    core = _read_json(CORE_FILE, {})
    if not core:
        print("autonomy_core: Noch kein Zustand — zuerst Pulse ausführen")
        return

    print(f"AUTONOMY CORE STATUS — {_now()}")
    print(f"  Uptime seit    : {core.get('uptime_since', '?')}")
    print(f"  Pulse-Count    : {core.get('pulse_count', 0)}")
    print(f"  Letzter Pulse  : {core.get('last_pulse', '?')}")
    print(f"  Audit-Score    : {core.get('last_audit_score', '?')}%")
    print(f"  Heal-Actions   : {core.get('heal_count', 0)} gesamt")
    print(f"  Alerts gesamt  : {core.get('alerts_total', 0)}")

    metrics = core.get("last_metrics", {})
    print(f"\n  Metriken:")
    print(f"    Prozesse      : {metrics.get('process_count', '?')}")
    print(f"    Workspace     : {metrics.get('workspace_size', '?')}")
    print(f"    Security      : {metrics.get('security_score', '?')}% {metrics.get('security_rating', '')}")
    print(f"    Letzter Commit: {metrics.get('last_commit', '?')}")
    print(f"    Uncommitted   : {metrics.get('uncommitted_files', '?')} Dateien")

    failed = core.get("last_audit_failed", [])
    if failed:
        print(f"\n  Offene Synergy-Fehler:")
        for f in failed:
            print(f"    ✗ {f}")
    else:
        print(f"\n  Synergy: ✓ alle Regeln OK")

    alerts = core.get("last_alerts", [])
    if alerts:
        print(f"\n  Letzte Alerts:")
        for a in alerts:
            print(f"    [{a.get('level')}] {a.get('msg')}")

# ── Hauptloop ─────────────────────────────────────────────────────────────────

def run_once() -> None:
    """Einen vollständigen Zyklus ausführen."""
    _log("pulse start")
    heal_actions = heal()
    pulse_state = pulse()
    reflect(pulse_state, heal_actions)
    if pulse_state["alerts"]:
        escalate(pulse_state["alerts"])
    metrics = pulse_state.get("metrics", {})
    _log(
        f"pulse done — audit {pulse_state['audit']['score']}% | "
        f"security {metrics.get('security_score', '?')}% | "
        f"alerts {len(pulse_state['alerts'])} | "
        f"heal {len(heal_actions)}"
    )

def run_loop(interval: int) -> None:
    """Dauerbetrieb mit konfigurierbarem Interval."""
    _log(f"autonomy_core: Dauerbetrieb gestartet (interval={interval}s)")
    _append_console_log("autonomy_start", {
        "interval": interval,
        "msg": f"Autonomy Core gestartet — Pulse alle {interval}s"
    })
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            _log("autonomy_core: Shutdown via Ctrl-C")
            _append_console_log("autonomy_stop", {"msg": "Shutdown via SIGINT"})
            break
        except Exception as e:
            log.warning("swallowed in autonomy_core: %s", exc)
            _log(f"autonomy_core: Ausnahme im Hauptloop: {e}")
            _append_console_log("autonomy_error", {"error": str(e)})
        time.sleep(interval)

# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Autonomer Existenzkern von upgraded-fiesta")
    ap.add_argument("--loop",     action="store_true", help="Dauerbetrieb")
    ap.add_argument("--interval", type=int, default=60, help="Interval in Sekunden (default: 60)")
    ap.add_argument("--status",   action="store_true", help="Aktuellen Zustand ausgeben")
    ap.add_argument("--heal",     action="store_true", help="Nur Selbstheilung ausführen")
    args = ap.parse_args()

    if args.status:
        print_status()
    elif args.heal:
        actions = heal()
        if actions:
            for a in actions:
                print(f"  healed: {a['action']} — {a.get('note', '')}")
        else:
            print("heal: Nichts zu tun — alles sauber")
    elif args.loop:
        run_loop(args.interval)
    else:
        run_once()

if __name__ == "__main__":
    main()
