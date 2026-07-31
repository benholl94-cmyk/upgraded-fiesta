"""Tests der Rollback-Entscheidung und der Conclusio-Allowlist.

Ein Rollback, das falsch auslöst, verwirft gute Arbeit oder dreht sich im
Kreis. Die Tests halten deshalb vor allem fest, **wann nicht** revertiert
wird — die vier Sperren sind der eigentliche Gegenstand.

Die Mechanik darf sich nicht zurueck zu einer Blockliste entwickeln. Genau
das war HANDOFF.md s2-5: Sperre 2 pruefte nur `== 'failure'` und liess
`cancelled`, `timed_out` und `unknown` als stillen Erfolg durch. Ein
eigener Abschnitt unten pinnt die volle Conclusio→Aktion-Tabelle aus
`scripts/auto_rollback_ctx.py` fest, die `decide()` fuer Sperre 2
wiederverwendet.

Was NICHT getestet wird: der eigentliche GitHub-Workflow (`workflow_run`,
`workflow_dispatch`). Den testet der Workflow selbst, sobald er auf main
ist; hier geht es um die reinen Entscheidungsfunktionen.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

_S = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "auto_rollback.py"
_spec = importlib.util.spec_from_file_location("auto_rollback", _S)
ar = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ar
_spec.loader.exec_module(ar)

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
MERGE = "feat(x): etwas gebaut (#42)"


def ctx(**kw):
    base = dict(sha="a" * 40, subject=MERGE, branch="main", conclusion="failure",
                previous_conclusion="success", recent_reverts=(),
                now=NOW.isoformat())
    base.update(kw)
    return ar.Context(**base)


def test_clean_case_reverts():
    d = ar.decide(ctx())
    assert d.action == ar.REVERT and d.should_revert


# --------------------------------------------------------------------------
# Sperre 1 — Schleifenschutz
# --------------------------------------------------------------------------

@pytest.mark.parametrize("subject", [
    'Revert "feat(x): etwas gebaut (#42)"',
    'revert "feat(x): etwas (#42)"',
])
def test_never_reverts_a_revert(subject):
    d = ar.decide(ctx(subject=subject))
    assert d.action == ar.HOLD and "Endlosschleife" in d.reason


# --------------------------------------------------------------------------
# Sperre 2 — Vorgaenger nicht nachweislich unbedenklich
#
# Reuse der Conclusio-Allowlist aus auto_rollback_ctx.py: sicher ist nur ein
# Vorgaenger, den die Allowlist als NOOP einstuft (success/skipped/neutral).
# --------------------------------------------------------------------------

def test_holds_when_previous_commit_was_already_red():
    d = ar.decide(ctx(previous_conclusion="failure"))
    assert d.action == ar.HOLD and "Vorgaengercommit" in d.reason


@pytest.mark.parametrize("previous", [
    "unknown", "cancelled", "timed_out", "action_required",
    "startup_failure", "stale", "",
])
def test_holds_when_previous_state_is_not_allowlisted_noop(previous):
    """Alles, was auto_rollback_ctx.ALLOWLIST nicht als NOOP einstuft, muss
    HOLD ergeben. Ein unbestimmter Vorgaenger-Status darf nie wie ein
    sicherer durchrutschen — genau das hat den einfuehrenden Merge-Commit
    dieses Moduls selbst revertiert (previous_conclusion war 'unknown', eine
    Blockliste auf '== failure' hat es durchgewinkt)."""
    d = ar.decide(ctx(previous_conclusion=previous))
    assert d.action == ar.HOLD
    assert previous in d.reason


@pytest.mark.parametrize("previous", ["success", "skipped", "neutral"])
def test_reverts_when_previous_state_is_allowlisted_noop(previous):
    """Jeder von der geteilten Allowlist als NOOP eingestufte Vorgaenger
    (nicht nur 'success') gilt als sicher genug fuer Sperre 2 — das ist die
    bewusste Erweiterung ueber die reine 'success'-Pruefung hinaus, die aus
    der Wiederverwendung der Allowlist folgt."""
    assert ar.decide(ctx(previous_conclusion=previous)).action == ar.REVERT


# --------------------------------------------------------------------------
# Sperre 3 — Sicherung
# --------------------------------------------------------------------------

def test_circuit_breaker_holds_after_repeated_reverts():
    recent = [(NOW - timedelta(hours=1)).isoformat(),
              (NOW - timedelta(hours=2)).isoformat()]
    d = ar.decide(ctx(recent_reverts=tuple(recent)))
    assert d.action == ar.HOLD and "Sicherung" in d.reason


def test_old_reverts_do_not_trip_the_breaker():
    old = [(NOW - timedelta(hours=20)).isoformat(),
           (NOW - timedelta(hours=30)).isoformat()]
    assert ar.decide(ctx(recent_reverts=tuple(old))).action == ar.REVERT


def test_one_recent_revert_is_still_allowed():
    one = ((NOW - timedelta(minutes=30)).isoformat(),)
    assert ar.decide(ctx(recent_reverts=one)).action == ar.REVERT


def test_unparsable_timestamps_are_ignored_not_fatal():
    d = ar.decide(ctx(recent_reverts=("kaputt", "auch kaputt")))
    assert d.action == ar.REVERT


# --------------------------------------------------------------------------
# Sperre 4 — nur ganze Merges
# --------------------------------------------------------------------------

@pytest.mark.parametrize("subject", [
    "fix: kleiner Einzelcommit",
    "chore: ohne PR-Nummer",
])
def test_holds_on_non_merge_commits(subject):
    d = ar.decide(ctx(subject=subject))
    assert d.action == ar.HOLD and "Zwischenstand" in d.reason


@pytest.mark.parametrize("subject", [
    "feat(x): etwas (#42)",
    "Merge pull request #42 from foo/bar",
])
def test_merge_shapes_are_recognised(subject):
    assert ar.decide(ctx(subject=subject)).action == ar.REVERT


# --------------------------------------------------------------------------
# Kein Bruch, kein Rollback
# --------------------------------------------------------------------------

@pytest.mark.parametrize("conclusion", ["success", "cancelled", "skipped"])
def test_noop_when_ci_did_not_fail(conclusion):
    assert ar.decide(ctx(conclusion=conclusion)).action == ar.NOOP


def test_noop_on_other_branches():
    assert ar.decide(ctx(branch="feature/x")).action == ar.NOOP


def test_missing_sha_holds():
    assert ar.decide(ctx(sha="")).action == ar.HOLD


# --------------------------------------------------------------------------
# Form
# --------------------------------------------------------------------------

def test_every_decision_carries_a_reason():
    for c in (ctx(), ctx(conclusion="success"), ctx(subject="einzeln"),
              ctx(previous_conclusion="failure")):
        assert ar.decide(c).reason.strip()


def test_decision_is_json_serialisable():
    json.dumps(ar.decide(ctx()).to_dict())


def test_context_from_dict_tolerates_missing_fields():
    """Ein fehlender Vorgaenger-Status muss zu 'unknown' werden, nie zu
    'success' — sonst waere das Fehlen eines Feldes gleichbedeutend mit
    einem gruenen Vorgaenger."""
    c = ar.Context.from_dict({"sha": "x", "branch": "main"})
    assert c.previous_conclusion == "unknown" and c.recent_reverts == ()


def test_cli_exit_code_signals_the_decision():
    payload = json.dumps({"sha": "a" * 40, "subject": MERGE, "branch": "main",
                          "conclusion": "failure", "previous_conclusion": "success",
                          "now": NOW.isoformat()})
    assert ar.main(["decide", "--json", payload, "--machine"]) == 0
    payload2 = json.dumps({"sha": "a" * 40, "subject": MERGE, "branch": "main",
                           "conclusion": "success"})
    assert ar.main(["decide", "--json", payload2, "--machine"]) == 1


# --------------------------------------------------------------------------
# Kontext-Einsammlung (scripts/auto_rollback_ctx.py)
# --------------------------------------------------------------------------

_C = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "auto_rollback_ctx.py"
_cspec = importlib.util.spec_from_file_location("auto_rollback_ctx", _C)
ctxmod = importlib.util.module_from_spec(_cspec)
sys.modules[_cspec.name] = ctxmod
_cspec.loader.exec_module(ctxmod)


def test_prev_conclusion_reads_the_ci_run(tmp_path):
    p = tmp_path / "runs.json"
    p.write_text(json.dumps({"workflow_runs": [
        {"name": "CodeQL", "conclusion": "success"},
        {"name": "ci", "conclusion": "failure"},
    ]}))
    assert ctxmod.prev_conclusion(str(p)) == "failure"


@pytest.mark.parametrize("content", ['{"workflow_runs": []}', "{}", "kein json"])
def test_prev_conclusion_falls_back_to_unknown(tmp_path, content):
    """Unbekannt darf nie zu 'success' werden — sonst revertiert das System
    auf Verdacht."""
    p = tmp_path / "runs.json"
    p.write_text(content)
    assert ctxmod.prev_conclusion(str(p)) == "unknown"


def test_prev_conclusion_on_missing_file():
    assert ctxmod.prev_conclusion("/gibt/es/nicht.json") == "unknown"


def test_build_context_from_env(tmp_path, monkeypatch):
    r = tmp_path / "reverts.txt"
    r.write_text("2026-07-26T10:00:00+00:00\n\n2026-07-26T11:00:00+00:00\n")
    for k, v in {"SHA": "abc", "SUBJECT": "feat: x (#1)",
                 "CONCLUSION": "failure", "PREV_CONCLUSION": "success\n"}.items():
        monkeypatch.setenv(k, v)
    d = ctxmod.build(str(r))
    assert d["sha"] == "abc" and d["branch"] == "main"
    assert d["previous_conclusion"] == "success"      # getrimmt
    assert len(d["recent_reverts"]) == 2              # Leerzeile faellt weg


def test_built_context_feeds_the_decision(tmp_path, monkeypatch):
    r = tmp_path / "reverts.txt"
    r.write_text("")
    for k, v in {"SHA": "a" * 40, "SUBJECT": "feat: x (#7)",
                 "CONCLUSION": "failure", "PREV_CONCLUSION": "success"}.items():
        monkeypatch.setenv(k, v)
    assert ar.decide(ar.Context.from_dict(ctxmod.build(str(r)))).action == ar.REVERT


def test_issue_body_is_valid_json_payload(monkeypatch):
    for k, v in {"SHA": "a" * 40, "ACTION": "HOLD",
                 "DECISION": '{"action":"HOLD"}', "RUN_URL": "http://x"}.items():
        monkeypatch.setenv(k, v)
    d = ctxmod.issue_body()
    json.dumps(d)
    assert d["title"].startswith("Auto-Rollback: HOLD")
    assert "HOLD" in d["body"] and "Sperren" in d["body"]


# --------------------------------------------------------------------------
# Conclusio-Allowlist (auto_rollback_ctx.ALLOWLIST / decide / from_env / CLI)
# --------------------------------------------------------------------------

SCRIPT = REPO / "scripts" / "auto_rollback_ctx.py"


def test_decide_allowlist_full_table():
    """Jede in GitHub Actions moegliche Conclusio ist abgebildet."""
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
        got = ctxmod.decide(conclusion)
        assert got == action, (
            f"decide({conclusion!r}) returned {got!r}, expected {action!r}"
        )


def test_decide_unknown_falls_back_to_hold():
    """Eine unbekannte Conclusio darf NIE REVERT ausloesen."""
    for weird in ["", "   ", "mystery", "0", "True", "OK"]:
        assert ctxmod.decide(weird) == "HOLD", (
            f"decide({weird!r}) returned {ctxmod.decide(weird)!r}; must be HOLD"
        )


def test_decide_is_case_insensitive():
    """Conclusiones werden in der Praxis in verschiedenen Cases geliefert."""
    assert ctxmod.decide("Failure") == "REVERT"
    assert ctxmod.decide("FAILURE") == "REVERT"
    assert ctxmod.decide("Cancelled") == "HOLD"


def test_from_env_without_conclusion_is_hold():
    """Ohne env-Variable: HOLD, niemals REVERT."""
    old = os.environ.pop("CONCLUSION", None)
    try:
        conclusion, action = ctxmod.from_env()
        assert conclusion == ""
        assert action == "HOLD"
    finally:
        if old is not None:
            os.environ["CONCLUSION"] = old


def test_from_env_with_failure_reverts():
    os.environ["CONCLUSION"] = "failure"
    try:
        conclusion, action = ctxmod.from_env()
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


def test_cli_legacy_subcommands_still_work(monkeypatch):
    """Der Workflow ruft `issue-body`/`prev-conclusion`/`build` auf; die
    neuen --conclusion/--json/--show-allowlist-Flags duerfen das nicht
    verdraengen."""
    for k, v in {"SHA": "a" * 40, "ACTION": "HOLD",
                 "DECISION": '{"action":"HOLD"}', "RUN_URL": "http://x"}.items():
        monkeypatch.setenv(k, v)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "issue-body"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
    )
    payload = json.loads(result.stdout.strip())
    assert payload["title"].startswith("Auto-Rollback: HOLD")
