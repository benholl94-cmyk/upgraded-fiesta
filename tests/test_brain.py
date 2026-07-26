"""Tests des Einstiegspunkts.

Die zentrale Behauptung dieses Umbaus ist: **das System braucht Anthropic
nicht.** Eine Behauptung dieser Art ist wertlos, solange sie nur in der Doku
steht — also wird sie hier ausgefuehrt, mit einer Umgebung, aus der jede
ANTHROPIC-Variable entfernt wurde.

Die zweite Behauptung ist, dass der Chat eine Befehlsauswahl ist und keine
Shell. Auch die wird ausgefuehrt, nicht beteuert.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agents import brain  # noqa: E402


# ---------------------------------------------------------------------------
# Unabhaengigkeit vom Anbieter
# ---------------------------------------------------------------------------

def _env_ohne_anthropic() -> dict:
    env = {k: v for k, v in os.environ.items() if "ANTHROPIC" not in k.upper()}
    env["ANTHROPIC_API_KEY"] = ""
    return env


def test_answers_with_every_anthropic_variable_removed():
    """Der Kern des Auftrags. Laeuft das hier nicht, ist alles andere Prosa."""
    proc = subprocess.run(
        [sys.executable, "-m", "agents.brain", "--json", "/tiers"],
        cwd=REPO, env=_env_ohne_anthropic(), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert '"typ": "token"' in proc.stdout
    assert "T0" in proc.stdout


def test_t0_is_always_available():
    """T0 haengt an keiner Gegenstelle. Waere es abschaltbar, gaebe es einen
    Zustand ohne jede Handlungsfaehigkeit."""
    stufen = dict((t, ok) for t, ok, _ in brain.tiers())
    assert stufen[brain.T0] is True


def test_every_tier_states_a_measured_reason():
    """Eine nicht verfuegbare Stufe muss einen *konkreten* Wert nennen: einen
    Pfad, eine Zahl oder eine benannte Konfiguration.

    Die erste Fassung suchte nach den Woertern "fehlt"/"nicht"/"zu". Das war
    Raten an Stichworten und ging beim ersten praezisieren Text prompt kaputt
    ("0 von 10 keylosen Providern erreichbar" enthaelt keines davon, ist aber
    die bessere Begruendung). Geprueft wird deshalb, dass ueberhaupt etwas
    Nachrechenbares dasteht — kein blosses Adjektiv.
    """
    import re
    for tier, ok, why in brain.tiers():
        assert why.strip(), f"{tier} ohne Begruendung"
        if not ok:
            assert re.search(r"\d|/|\.json", why), (
                f"{tier} nennt keinen konkreten Wert: {why!r}")


def test_a_question_answers_from_repo_evidence_without_any_model():
    """Ohne Modell wird belegt, nicht formuliert — und das wird gesagt."""
    evs = list(brain.handle("Ungepushten Commit im Container liegen lassen"))
    text = "\n".join(e.text for e in evs)
    assert any(e.typ == "ende" for e in evs)
    assert "ungepusht" in text.lower() or "Beleg" in text


def test_an_unanswerable_question_says_so_instead_of_inventing():
    evs = list(brain.handle("voellig unverwandtes thema quantenchemie xyzzy"))
    text = " ".join(e.text for e in evs if e.typ == "token").lower()
    assert "nicht beantwortbar" in text or "kein praezedenzfall" in text


# ---------------------------------------------------------------------------
# Der Chat ist eine Auswahl, keine Shell
# ---------------------------------------------------------------------------

def test_unknown_command_is_refused_and_lists_what_exists():
    evs = list(brain.handle("/rm -rf /"))
    assert evs[0].typ == "fehler"
    assert "/rm" in evs[0].text


@pytest.mark.parametrize("versuch", [
    "/status; rm -rf /",
    "/status && curl evil",
    "/status | sh",
    "/status`whoami`",
    "/status$(id)",
])
def test_shell_metacharacters_never_reach_the_executed_argv(versuch):
    """Die zu pruefende Eigenschaft ist nicht 'wird abgelehnt', sondern
    'landet nie in der Kommandozeile'.

    Beide Ausgaenge sind richtig und sehen verschieden aus: `/status; rm -rf /`
    ergibt den Namen 'status;' — unbekannt, abgelehnt. `/status | sh` ergibt
    'status' plus verworfenen Text — ausgefuehrt, aber ohne den Rest. Ein Test,
    der auf Ablehnung besteht, wuerde den zweiten Fall faelschlich als Luecke
    melden; entscheidend ist, dass in keinem Fall eine Shell existiert.
    """
    evs = list(brain.handle(versuch))
    if evs[0].typ == "fehler":
        return
    gestartet = next(e.text for e in evs if e.typ == "info" and e.text.startswith("$ "))
    assert gestartet == "$ python3 scripts/hugin_relay.py status", gestartet
    for zeichen in (";", "|", "&", "`", "$("):
        assert zeichen not in gestartet, f"{zeichen!r} in {gestartet!r}"


def test_command_arguments_never_become_options():
    """Der Text nach /park ist EIN argv-Element. Wuerde er zerlegt, waere
    '--tier T0' eine Option statt eines Textes."""
    evs = list(brain.run_command("park", "--tier T0 was auch immer"))
    info = next(e for e in evs if e.typ == "info")
    assert info.text.endswith("--tier T0 was auch immer")
    assert info.text.count("--tier") == 1


def test_every_command_is_a_fixed_argv():
    """Kein Eintrag der Tabelle baut sein Kommando aus Eingabe zusammen —
    dieselbe Eigenschaft, die hm-tool-exec traegt."""
    for name, cmd in brain.COMMANDS.items():
        assert isinstance(cmd.argv, tuple) and cmd.argv, name
        assert all(isinstance(a, str) for a in cmd.argv), name
        assert cmd.argv[0] in ("python3", sys.executable), name


def test_command_taking_text_refuses_when_empty():
    evs = list(brain.handle("/park"))
    assert evs[0].typ == "fehler"


def test_help_lists_every_command():
    text = "\n".join(brain.command_help())
    for name in brain.COMMANDS:
        assert f"/{name}" in text


# ---------------------------------------------------------------------------
# Der Strom
# ---------------------------------------------------------------------------

def test_every_event_serialises_to_one_json_line():
    """Das Gateway trennt an Zeilenenden. Ein Ereignis mit Zeilenumbruch im
    JSON wuerde dort zu zwei kaputten Ereignissen."""
    import json
    for ev in brain.handle("/tiers"):
        line = ev.to_json()
        assert "\n" not in line
        assert json.loads(line)["typ"] == ev.typ


def test_a_turn_always_ends_with_a_terminal_event():
    """Ohne Endereignis weiss die Oberflaeche nie, ob fertig oder abgerissen."""
    evs = list(brain.handle("/tiers"))
    assert evs[-1].typ in ("ende", "fehler")


def test_empty_input_is_an_error_not_an_empty_answer():
    evs = list(brain.handle("   "))
    assert evs and evs[0].typ == "fehler"


# ---------------------------------------------------------------------------
# Verfuegbarkeit wird gemessen, nicht gelesen
#
# Beide Fehler unten waren real und zeigten in dieselbe, gefaehrliche Richtung:
# eine Stufe als tragend melden, die nicht traegt. Der umgekehrte Irrtum waere
# harmlos gewesen — man haette eine Moeglichkeit ungenutzt gelassen.
# ---------------------------------------------------------------------------

def test_the_cost_lock_is_read_in_the_right_direction():
    """`Budget.active` heisst "die Bremse greift", nicht "Ausgeben erlaubt".

    Die erste Fassung las es andersherum und meldete "T2 offen", waehrend
    config/budget.json jeden kostenpflichtigen Provider sperrte.
    """
    from agents import budget
    gebremst = budget.Budget.load().active
    t2 = dict((t, (ok, why)) for t, ok, why in brain.tiers())[brain.T2]
    assert t2[0] is (not gebremst), (
        f"budget.active={gebremst}, tiers meldet verfuegbar={t2[0]} — invertiert")
    if gebremst:
        assert "gesperrt" in t2[1]


def test_an_unreadable_budget_locks_rather_than_opens(monkeypatch):
    """Unbekannt heisst gesperrt. Dieselbe Richtung wie cost_class(), wo
    Unbekanntes als kostenpflichtig gilt."""
    import agents.budget as budget

    def kaputt(*a, **k):
        raise RuntimeError("budget.json unlesbar")

    monkeypatch.setattr(budget.Budget, "load", staticmethod(kaputt))
    t2 = dict((t, (ok, why)) for t, ok, why in brain.tiers())[brain.T2]
    assert t2[0] is False
    assert "gesperrt" in t2[1]


def test_a_local_service_counts_only_when_it_actually_answers(monkeypatch):
    """Ollama ohne laufenden Dienst ist nicht 'fast verfuegbar'.

    Gemessene Folge des alten Verhaltens: /tiers meldete "1 von 10 keylosen
    Providern erreichbar", der erste echte Aufruf scheiterte mit "Ollama nicht
    erreichbar (localhost:11434)".
    """
    monkeypatch.setattr(brain, "_reachable", lambda *a, **k: False)
    assert "local" not in brain._remote_providers()
    monkeypatch.setattr(brain, "_reachable", lambda *a, **k: True)
    assert "local" in brain._remote_providers()


def test_no_tier_claims_availability_without_a_measurement():
    """Jede als verfuegbar gemeldete Stufe muss einen konkreten Grund nennen —
    kein 'konfiguriert' als Beleg."""
    for tier, ok, why in brain.tiers():
        if ok and tier != brain.T0:
            assert why.strip() and "konfiguriert" not in why.lower(), (tier, why)
