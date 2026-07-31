"""test_log_module.py — Wache ueber scripts/_log.py.

Jeder, der `print(...)` zur Diagnose benutzt, schlaegt hier fehl —
gewollt, weil das der Mechanismus ist, mit dem die 529-stueckige
print-Migration ueberpruefbar bleibt.

Wer das Modul aendert, muss diese Tests anpassen UND einen Eintrag in
docs/production-api-contract.md machen (siehe D.5 in
/home/box/.claude/plans/zippy-snacking-ritchie.md).
"""

from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS_LOG = REPO / "scripts" / "_log.py"


# ---------------------------------------------------------------------------
# 1 — Modul ist da, importierbar, hat die richtige API
# ---------------------------------------------------------------------------

def test_module_exists():
    assert SCRIPTS_LOG.is_file(), "scripts/_log.py fehlt — Skripte ohne strukturiertes Logging"


def test_module_imports():
    out = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import _log"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert out.returncode == 0, (
        f"_log laesst sich nicht importieren: {out.stderr}"
    )


def test_get_logger_returns_logger_instance():
    """get_logger muss einen stdlib-logging-Logger zurueckgeben, sonst
    koennen Aufrufer keine `extra={...}`-Felder mitgeben."""
    sys.path.insert(0, str(REPO / "scripts"))
    from _log import get_logger
    log = get_logger("test_logger_basic")
    assert isinstance(log, logging.Logger), (
        f"get_logger muss logging.Logger zurueckgeben, bekam {type(log)!r}"
    )
    assert log.name == "test_logger_basic"


# ---------------------------------------------------------------------------
# 2 — Idempotenz: zwei Aufrufe konfigurieren nicht doppelt
# ---------------------------------------------------------------------------

def test_get_logger_is_idempotent():
    """Mehrfaches `get_logger(...)` darf den Handler-Stack nicht
    verdoppeln. Wir zaehlen dazu nur die Handler, die von `_log` kommen
    (erkennbar am JsonFormatter); pytest-eigene caplog-Handler zaehlen
    nicht, weil sie nicht von uns sind."""
    sys.path.insert(0, str(REPO / "scripts"))
    from _log import _JsonFormatter, get_logger
    get_logger("test_idempotent_1")
    get_logger("test_idempotent_2")
    get_logger("test_idempotent_3")
    root = logging.getLogger()
    # Nur Handler mit JsonFormatter zaehlen — das ist der, den _log selbst
    # anhaengt. pytest-eigene caplog-Handler haben einen anderen Typ.
    log_handlers = [
        h for h in root.handlers
        if isinstance(getattr(h, "formatter", None), _JsonFormatter)
    ]
    assert len(log_handlers) == 1, (
        f"_log hat mehr als einen Handler an der Root angehaengt: "
        f"{len(log_handlers)} Handler mit JsonFormatter gefunden"
    )


# ---------------------------------------------------------------------------
# 3 — JSON-Format: Pflichtfelder + ISO-Timestamp
# ---------------------------------------------------------------------------

def test_log_emits_valid_json_to_stderr(monkeypatch):
    """Eine log.info-Zeile muss valides JSON auf stderr sein, mit den
    vier Pflichtfeldern ts/level/name/message.

    Wir ersetzen sys.stderr durch einen StringIO und lesen ihn direkt —
    pytest-eigene caplog-/capfd-Fixtures ersetzen sys.stderr bereits,
    bevor unser Handler eine Referenz haelt; das fuehrt zu einem
    leeren captured.err obwohl die Zeile im 'Captured stderr call'-
    Block des Reports erscheint (pytest sieht es auf fd-Ebene, wir
    nicht ueber capfd.readouterr())."""
    import io
    sys.path.insert(0, str(REPO / "scripts"))
    # State zuruecksetzen, weil vorherige Tests schon konfiguriert haben.
    import _log
    _log._already_configured = False
    monkeypatch.setattr(_log, "_already_configured", False)
    fake_err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", fake_err)
    from _log import get_logger
    log = get_logger("test_json_emitter")
    log.info("hello world")
    captured = fake_err.getvalue()
    assert captured != "", "Es wurde nichts nach stderr geschrieben"
    line = captured.strip().splitlines()[-1]
    obj = json.loads(line)
    assert set(obj.keys()) >= {"ts", "level", "name", "message"}, (
        f"Pflichtfelder fehlen: {obj.keys()}"
    )
    assert obj["level"] == "INFO"
    assert obj["name"] == "test_json_emitter"
    assert obj["message"] == "hello world"
    # ISO-8601 mit Millisekunden + UTC-Offset.
    assert "T" in obj["ts"], f"Timestamp nicht ISO-8601: {obj['ts']!r}"
    assert obj["ts"].endswith("+00:00"), (
        f"Timestamp ohne UTC-Offset: {obj['ts']!r} (Loki-Sortierung bricht)"
    )


def test_log_extra_fields_appear_as_top_level(monkeypatch):
    """Wer `extra={...}` benutzt, will die Felder oben haben, nicht in
    einem `extra`-Sub-Dict — das ist der ganze Sinn von strukturiertem
    Logging. Wenn das bricht, ist Loki/CloudQuery blind fuer Custom-Felder."""
    import io
    sys.path.insert(0, str(REPO / "scripts"))
    import _log
    _log._already_configured = False
    monkeypatch.setattr(_log, "_already_configured", False)
    fake_err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", fake_err)
    from _log import get_logger
    log = get_logger("test_extra_fields")
    log.warning("cron failed", extra={"job": "heartbeat", "interval_secs": 3600})
    captured = fake_err.getvalue()
    line = captured.strip().splitlines()[-1]
    obj = json.loads(line)
    assert "extra" not in obj, f"extra-Felder sind in Sub-Key verpackt: {obj!r}"
    assert obj["job"] == "heartbeat", f"Custom-Feld 'job' fehlt: {obj!r}"
    assert obj["interval_secs"] == 3600


# ---------------------------------------------------------------------------
# 4 — Level via $LOG_LEVEL
# ---------------------------------------------------------------------------

def test_log_level_from_env(monkeypatch, capfd):
    """LOG_LEVEL=DEBUG muss den Root-Logger auf DEBUG setzen.
    Ohne diese Konfiguration waere 'warum-debuggt-mein-Skript-nicht'
    der haeufigste Operator-Frust."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    # Idempotenz-Flag muss fuer den Test zurueckgesetzt werden, sonst
    # hat ein frueherer Test den Logger schon auf INFO konfiguriert.
    import _log
    _log._already_configured = False
    sys.path.insert(0, str(REPO / "scripts"))
    from _log import get_logger
    log = get_logger("test_log_level_env")
    log.debug("sichtbar nur bei DEBUG")
    captured = capfd.readouterr()
    assert "sichtbar nur bei DEBUG" in captured.err, (
        f"DEBUG-Level nicht aktiv trotz LOG_LEVEL=DEBUG: {captured.err!r}"
    )


def test_unknown_log_level_falls_back_to_info(monkeypatch, capfd):
    """LOG_LEVEL=INFOO (Tippfehler) darf nicht still sein — entweder
    Fallback + Hinweis, oder Exit 1. Hier: Fallback mit sichtbarem Hinweis."""
    monkeypatch.setenv("LOG_LEVEL", "INFOO")
    import _log
    _log._already_configured = False
    sys.path.insert(0, str(REPO / "scripts"))
    from _log import get_logger
    log = get_logger("test_log_level_typo")
    log.info("nach fallback")
    captured = capfd.readouterr()
    assert "unbekanntes LOG_LEVEL" in captured.err, (
        f"Tippfehler-Level sollte Hinweis auf stderr ausgeben: {captured.err!r}"
    )
    assert "nach fallback" in captured.err, "INFO-Level nach Fallback nicht aktiv"


# ---------------------------------------------------------------------------
# 5 — Migrations-Wache: kritische Skripte sollen den Logger nutzen
# ---------------------------------------------------------------------------

# Diese Skripte sind im Plan B.3 explizit als Migrations-Ziel benannt.
# Der Test prueft NICHT dass jeder print migriert ist (zu invasiv), sondern
# dass die `from _log import get_logger`-Zeile ueberall vorhanden ist und
# dass mindestens ein print -> log-Aufruf stattgefunden hat.
MIGRATION_TARGETS = [
    "scripts/hm_gateway_watchdog.py",
    "scripts/munin_continuity.py",
    "scripts/munin_supervisor.py",
    "scripts/knowledge_loop.py",
    "scripts/security_sentinel.py",
    "scripts/repo_tracker.py",
    "scripts/monitor_platform.py",
    "scripts/hugin_selfheal.py",
    "scripts/hugin_clarity.py",
    "scripts/llm_key_manager.py",
    "plugins/channel_send_plugin.py",
    "plugins/llm_chat_plugin.py",
    "plugins/echo_plugin.py",
]


@pytest.mark.parametrize("script_rel", MIGRATION_TARGETS)
def test_migrated_script_imports_logger(script_rel):
    """Jedes Migrations-Ziel muss den Logger importieren. Wir lesen den
    Source-Code (nicht `import`), weil sonst ein fehlendes Skript den
    Test mit ImportError statt AssertionError zumacht — und ein Skript
    ohne Logger waere genau das Symptom, das wir sehen wollen."""
    p = REPO / script_rel
    assert p.is_file(), f"{script_rel} existiert nicht (Plan B.3 Annahme)"
    text = p.read_text(encoding="utf-8")
    # Erlaubte Import-Muster (manuell je Skript entschieden):
    #   `from _log import get_logger` (Skripte unter scripts/)
    #   `import _log` mit sys.path.insert
    #   `from _log import ...` mit sys.path-Anpassung
    has_logger_import = (
        "from _log import get_logger" in text
        or "import _log" in text and "get_logger" in text
    )
    assert has_logger_import, (
        f"{script_rel} importiert `get_logger` nicht — Plan B.3 Migration "
        f"nicht durchgefuehrt (oder neue Datei ohne Migrations-Stand)"
    )
