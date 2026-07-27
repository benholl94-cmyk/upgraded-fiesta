"""stdout gehört dem hm-plugins-Protokoll, nicht dem Logging.

`scripts/autonomy_core._log()` schreibt mit `print()`, also nach stdout, und
wird aus `heal()` und `reflect()` heraus gerufen — beide ruft das Plugin auf.
Ohne Trennung landet die Log-Zeile VOR der Antwort, und hm-plugins liest genau
die erste Zeile.

Der Fehler ist zustandsabhängig und feuert genau dann, wenn die Selbstheilung
tatsächlich etwas heilt oder ein Alert eskaliert — also im wichtigsten Moment.
Live beobachtet als::

    task 'autonomy-pulse' dispatched: ok=false
      message=plugin 'autonomy-pulse' returned invalid JSON: invalid type: integer

„integer" deshalb, weil serde aus ``[20:23:20] heal: …`` eine Sequenz macht,
deren erstes Element ``20`` gegen ``ok: bool`` läuft.

Sichtbar wurde er überhaupt erst, als der `taskType`-Vertragsbruch behoben war:
vorher erreichte kein Cron-Job je ein Plugin.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugins" / "autonomy_pulse_plugin.py"
REQUEST = json.dumps({"task_type": "autonomy-pulse", "objective": "", "payload": {}}) + "\n"

# `heal()` legt dieses Verzeichnis an, wenn es fehlt — und protokolliert das.
# Das ist der deterministische Auslöser für eine Log-Zeile während des Laufs.
HEAL_TRIGGER_DIR = REPO / "diagnostics"


def _run_plugin() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PLUGIN)],
        input=REQUEST,
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=180,
    )


@pytest.fixture
def heal_will_log():
    """Erzwingt, dass `heal()` etwas tut und dabei nach stdout protokolliert."""
    existed = HEAL_TRIGGER_DIR.exists()
    backup = None
    if existed:
        backup = HEAL_TRIGGER_DIR.with_name("diagnostics.pytest-backup")
        if backup.exists():
            shutil.rmtree(backup)
        HEAL_TRIGGER_DIR.rename(backup)
    try:
        yield
    finally:
        if HEAL_TRIGGER_DIR.exists():
            shutil.rmtree(HEAL_TRIGGER_DIR)
        if backup is not None:
            backup.rename(HEAL_TRIGGER_DIR)


def test_stdout_carries_exactly_one_line_even_while_healing(heal_will_log):
    """Die Regression: genau eine Zeile auf stdout, und die ist die Antwort."""
    proc = _run_plugin()
    assert proc.returncode == 0, proc.stderr

    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, (
        "stdout muss genau die Protokollzeile tragen, enthielt aber:\n"
        + "\n".join(lines[:5])
    )

    response = json.loads(lines[0])
    assert set(response) >= {"ok", "result", "message"}
    assert isinstance(response["ok"], bool), (
        "hm-plugins deserialisiert `ok` als bool; alles andere ist genau der "
        "beobachtete 'invalid type'-Fehler"
    )
    assert response["message"] == "autonomy-pulse complete"


def test_the_log_line_is_not_lost_but_moved_to_stderr(heal_will_log):
    """Gegenprobe: der Fix darf das Logging nicht entfernen, nur umleiten.

    Wäre `_log` einfach stillgelegt, ginge im Dauerbetrieb von
    `autonomy_core` die Nachvollziehbarkeit verloren — das wäre eine andere
    Art, dieselbe Information zu verlieren.
    """
    proc = _run_plugin()
    assert proc.returncode == 0, proc.stderr
    assert "heal:" in proc.stderr, (
        "die Heilungsmeldung muss auf stderr erscheinen, nicht verschwinden; "
        f"stderr war: {proc.stderr!r}"
    )


def test_response_is_parseable_without_any_heal_activity():
    """Der Gutfall — ohne ihn sagt die Regression nichts über den Normalbetrieb."""
    proc = _run_plugin()
    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    json.loads(lines[0])
