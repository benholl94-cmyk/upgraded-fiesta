"""test_auto_rollback.py — Wache ueber die Allowlist-Logik.

Die Mechanik des Auto-Rollback-Workflows darf sich nicht zurueck zu einer
Blockliste entwickeln. Genau das war HANDOFF.md s2-5: Lock 2 pruefte nur
`== 'failure'` und lies `cancelled`, `timed_out` und `unknown` als
stillen Erfolg durch. Diese Tests pinnen die volle Tabelle fest.

Was NICHT getestet wird: der eigentliche GitHub-Workflow (`workflow_run`,
`workflow_dispatch`). Den testet der Workflow selbst, sobald er auf main
ist; hier geht es um die reine Entscheidungsfunktion.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "auto_rollback_ctx.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("auto_rollback_ctx", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_decide_allowlist_full_table():
    """Jede in GitHub Actions moegliche Conclusio ist abgebildet."""
    mod = _load_module()
    expected = {
        "success": "NOOP",
        "skipped": "NOOP",
        "neutral": "NOOP",
        "failure": "REVERT",
        "cancelled": "HOLD",
        "timed_out": "HOLD",
        "action_required": "HOLD",
        "startup_failure": "HOLD",
        "stale": "HOLD",
    }
    for conclusion, action in expected.items():
        got = mod.decide(conclusion)
        assert got == action, (
            f"decide({conclusion!r}) returned {got!r}, expected {action!r}"
        )


def test_decide_unknown_falls_back_to_hold():
    """Eine unbekannte Conclusio darf NIE REVERT ausloesen."""
    mod = _load_module()
    for weird in ["", "   ", "mystery", "0", "True", "OK"]:
        assert mod.decide(weird) == "HOLD", (
            f"decide({weird!r}) returned {mod.decide(weird)!r}; must be HOLD"
        )


def test_decide_is_case_insensitive():
    """Conclusiones werden in der Praxis in verschiedenen Cases geliefert."""
    mod = _load_module()
    assert mod.decide("Failure") == "REVERT"
    assert mod.decide("FAILURE") == "REVERT"
    assert mod.decide("Cancelled") == "HOLD"


def test_from_env_without_conclusion_is_hold():
    """Ohne env-Variable: HOLD, niemals REVERT."""
    mod = _load_module()
    old = os.environ.pop("CONCLUSION", None)
    try:
        conclusion, action = mod.from_env()
        assert conclusion == ""
        assert action == "HOLD"
    finally:
        if old is not None:
            os.environ["CONCLUSION"] = old


def test_from_env_with_failure_reverts():
    mod = _load_module()
    os.environ["CONCLUSION"] = "failure"
    try:
        conclusion, action = mod.from_env()
        assert conclusion == "failure"
        assert action == "REVERT"
    finally:
        os.environ.pop("CONCLUSION", None)


def test_cli_json_output_shape():
    """`--json` gibt genau {conclusion, action} aus, eine Zeile."""
    # success → NOOP → Exit 0, sonst wuerde check=True den Test kippen.
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json", "--conclusion", "success"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
    )
    payload = json.loads(result.stdout.strip())
    assert payload == {"conclusion": "success", "action": "NOOP"}


def test_cli_json_output_includes_revert_when_failure():
    """Mit --conclusion failure wird action=REVERT in der JSON-Zeile gemeldet,
    auch wenn der Exit-Code 2 ist (REVERT ist explizit kein stiller Erfolg)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json", "--conclusion", "failure"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout.strip())
    assert payload == {"conclusion": "failure", "action": "REVERT"}


def test_cli_show_allowlist_is_a_complete_map():
    """Die ausgegebene Allowlist enthaelt alle 9 bekannten Conclusiones."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--show-allowlist"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
    )
    table = json.loads(result.stdout.strip())
    assert "failure" in table and table["failure"] == "REVERT"
    assert "cancelled" in table and table["cancelled"] == "HOLD"
    assert "timed_out" in table and table["timed_out"] == "HOLD"
    assert "unknown" not in table  # keine "unknown"-Conclusio bei GitHub


def test_cli_exit_code_for_revert_is_2():
    """REVERT exit 2, damit ein Cron-Lauf im stillen Erfolgsfall nicht rot
    wird, ein REVERT aber sichtbar ist (siehe scripts/auto_rollback_ctx.py)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--conclusion", "failure"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 2


def test_cli_exit_code_for_noop_is_0():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--conclusion", "success"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0
