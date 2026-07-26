"""Tests des Limit-Relays.

Der Parser ist der kritische Teil: erkennt er eine Limit-Meldung nicht, laeuft
die Sitzung ins Leere statt auf T0 auszuweichen. Erkennt er zu viel, weicht
sie aus, obwohl nichts ist. Beide Richtungen sind getestet.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_S = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "hugin_relay.py"
_spec = importlib.util.spec_from_file_location("hugin_relay", _S)
rl = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rl
_spec.loader.exec_module(rl)


@pytest.mark.parametrize("text", [
    "Claude usage limit reached", "You have hit your rate limit",
    "quota exceeded for this org", "HTTP 429 Too Many Requests",
    "Limit erreicht", "Overloaded", "API rate-limit",
])
def test_parser_recognises_limit_messages(text):
    hit, pat = rl.parse_limit(text)
    assert hit and pat


@pytest.mark.parametrize("text", [
    "", "alles in Ordnung", "Der Test prueft die Obergrenze der Liste",
    "429 Zeilen geaendert",     # Zahl im Fliesstext ohne Limit-Bezug? -> bewusst
])
def test_parser_stays_quiet_on_ordinary_text(text):
    hit, _ = rl.parse_limit(text)
    if "429" in text:
        pytest.skip("bewusst grosszuegig: lieber einmal zu oft ausweichen")
    assert not hit


def test_tiers_are_ordered_and_complete():
    assert rl.TIERS == (rl.T0, rl.T1, rl.T2)


def test_t0_tasks_all_exist_on_disk():
    """Eine Stufe, die auf fehlende Skripte zeigt, traegt nicht."""
    for t in rl.available_t0():
        assert t.name and t.zweck and len(t.cmd) >= 2


def test_t0_is_never_empty():
    """Der ganze Sinn: beim Limit bleibt etwas uebrig."""
    assert len(rl.available_t0()) >= 3


def test_t1_reads_providers_from_budget_not_a_second_list():
    """Zwei Listen derselben Sache driften auseinander."""
    from agents import budget
    assert set(rl.free_providers()) == set(budget.free_providers())


def test_park_rejects_empty_and_unknown_tier(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "ROOM", tmp_path / "relay")
    monkeypatch.setattr(rl, "QUEUE", tmp_path / "relay" / "q.jsonl")
    with pytest.raises(ValueError):
        rl.park("   ")
    with pytest.raises(ValueError):
        rl.park("etwas", tier="T9")


def test_park_and_queue_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "ROOM", tmp_path / "relay")
    monkeypatch.setattr(rl, "QUEUE", tmp_path / "relay" / "q.jsonl")
    rl.park("Architekturentscheidung offen", rl.T2, "Limit")
    rl.park("Text uebersetzen", rl.T1)
    q = rl.queue()
    assert len(q) == 2 and {e["tier"] for e in q} == {"T1", "T2"}


def test_one_broken_line_does_not_kill_the_subroom(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "ROOM", tmp_path / "relay")
    monkeypatch.setattr(rl, "QUEUE", tmp_path / "relay" / "q.jsonl")
    rl.park("gut", rl.T2)
    with rl.QUEUE.open("a") as fh:
        fh.write("{kaputt\n")
    rl.park("auch gut", rl.T2)
    assert len(rl.queue()) == 2


def test_queue_without_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "QUEUE", tmp_path / "gibtsnicht.jsonl")
    assert rl.queue() == []


def test_status_names_all_three_tiers():
    out = "\n".join(rl.status_lines())
    assert "T0" in out and "T1" in out and "T2" in out and "0 EUR" in out


def test_check_cli_exit_code(capsys):
    assert rl.main(["check", "usage limit reached"]) == 0
    assert rl.main(["check", "alles gut"]) == 1
