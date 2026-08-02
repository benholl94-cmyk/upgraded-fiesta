"""Das Session-Band und die zwei dispatchbaren Plugins.

Drei Teile, die das Inventar als ungeprueft fuehrte und die **tragend**
sind: `munin_bridge.py` ist der erste Befehl, den `CLAUDE.md` jeder Sitzung
vorschreibt, und die beiden Plugins stehen in `config/plugins.json` — ein
`POST /tasks` erreicht sie.

Was hier **nicht** steht: Alibi-Tests fuer die uebrigen offenen Skripte.
`hugin_growth.py` (36 Funktionen), `hugin_reflect.py` (44) und
`hugin_tool.py` (27) brauchen eigene Sitzungen; sie stehen weiter offen im
Inventar, mit Befehl. Ein Test, der nur die Zahl senkt, macht die Liste
unwahr statt kuerzer.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

PLUGINS = ["plugins/claude_tool_plugin.py", "plugins/ollama_plugin.py"]


def _leiten(pfad: str, huelle: dict, timeout: int = 60) -> dict:
    r = subprocess.run([sys.executable, pfad], input=json.dumps(huelle) + "\n",
                       cwd=REPO, capture_output=True, text=True, timeout=timeout)
    erste = (r.stdout or "").splitlines()[0] if r.stdout.strip() else ""
    assert erste, f"{pfad} schrieb nichts auf stdout: {r.stderr[-300:]}"
    return json.loads(erste)


# ---------------------------------------------------------------------------
# Das Protokoll: eine Zeile rein, eine Zeile raus
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pfad", PLUGINS)
def test_the_plugin_answers_exactly_one_json_line(pfad):
    """hm-plugins liest die **erste** stdout-Zeile. Wer daneben etwas
    ausgibt, zerstoert seine eigene Antwort — genau das ist hier schon
    passiert (`autonomy_pulse_plugin.py` schrieb sein Log nach stdout, und
    serde las `[20:23:20] …` als Sequenz)."""
    d = _leiten(pfad, {"task_type": "probe", "payload": {}})
    assert isinstance(d, dict)
    assert isinstance(d.get("ok"), bool), "ok fehlt oder ist kein Boolean"


@pytest.mark.parametrize("pfad", PLUGINS)
def test_a_missing_input_is_refused_loudly_not_silently(pfad):
    """Fail-closed: ohne Eingabe gibt es keine erfundene Antwort, sondern
    ein `ok: false` mit Begruendung. Ein Plugin, das still nichts tut, ist
    schlimmer als eines, das fehlt."""
    d = _leiten(pfad, {"task_type": "probe", "payload": {}})
    assert d["ok"] is False
    assert d.get("message"), "Absage ohne Begruendung"


@pytest.mark.parametrize("pfad", PLUGINS)
def test_the_refusal_names_the_fields_it_expected(pfad):
    """Ein Befund ohne Handlungsanweisung ist eine Beschwerde — dieselbe
    Regel wie im Inventar."""
    d = _leiten(pfad, {"task_type": "probe", "payload": {}})
    assert any(f in d["message"] for f in ("query", "prompt", "text"))


@pytest.mark.parametrize("pfad", PLUGINS)
def test_garbage_on_stdin_does_not_crash_the_protocol(pfad):
    """Ein Absturz auf stdout waere fuer hm-plugins ununterscheidbar von
    einer kaputten Antwort."""
    r = subprocess.run([sys.executable, pfad], input="{kein json\n",
                       cwd=REPO, capture_output=True, text=True, timeout=60)
    if r.stdout.strip():
        json.loads(r.stdout.splitlines()[0])


@pytest.mark.parametrize("pfad", PLUGINS)
def test_the_plugin_is_registered_and_reachable(pfad):
    """Ein Plugin, das keine `task_type` nennt, kann nie dispatcht werden —
    und faellt sonst niemandem auf."""
    reg = json.loads((REPO / "config" / "plugins.json").read_text(encoding="utf-8"))
    befehle = [" ".join(e["command"]) for e in reg["plugins"]]
    assert any(pfad in b for b in befehle), f"{pfad} steht in keiner Registry"


# ---------------------------------------------------------------------------
# Das Session-Band
# ---------------------------------------------------------------------------

BRIDGE = "scripts/munin_bridge.py"


def test_the_bridge_survives_a_missing_state_file(tmp_path, monkeypatch):
    """**Der Fall, der einmal jede Sitzung sofort abbrach.**
    `.claude/persona/munin-state.json` steht in `.gitignore`; in einem
    frischen Container existiert die Datei nicht, und `wakeup` — der erste
    Befehl, den `CLAUDE.md` vorschreibt — starb mit `FileNotFoundError`."""
    r = subprocess.run([sys.executable, BRIDGE, "wakeup"], cwd=REPO,
                       capture_output=True, text=True, timeout=180)
    assert "FileNotFoundError" not in r.stderr, r.stderr[-400:]
    assert r.returncode == 0, r.stderr[-400:]


def test_the_bridge_explains_itself_without_arguments():
    """Ohne Argument eine Uebersicht, kein Traceback."""
    r = subprocess.run([sys.executable, BRIDGE], cwd=REPO,
                       capture_output=True, text=True, timeout=120)
    assert "Traceback" not in r.stderr
    assert (r.stdout + r.stderr).strip()


def test_the_bridge_never_writes_a_secret_into_the_state():
    """Der Zustand wird zwar nicht committet, liegt aber im Klartext auf der
    Platte und wird von jeder Sitzung gelesen."""
    sys.path.insert(0, str(REPO / "scripts"))
    import build_manifest as bm
    p = REPO / ".claude" / "persona" / "munin-state.json"
    if not p.is_file():
        pytest.skip("kein Zustand vorhanden")
    assert bm.leckpruefung(p.read_text(encoding="utf-8")) == []
