"""Tests der vereinheitlichten Übergabe.

Der Gegenstand ist nicht die Formatierung, sondern **die Grenze**: ableitbare
Fakten dürfen nicht im Ledger stehen, nicht-ableitbare müssen dort stehen.
Ohne durchgesetzte Grenze war die Frage „welche Übergabe gilt?" bei jeder
neuen Sitzung wieder offen — genau das soll hier aufhören.

Jede Wache braucht einen Gegentest, der sie scheitern lässt. Eine Regel, die
nur am Gutfall geprüft wird, kann fast alles durchwinken und sieht trotzdem
grün aus.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_S = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "munin_session.py"
_spec = importlib.util.spec_from_file_location("munin_session", _S)
ms = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ms
_spec.loader.exec_module(ms)

REPO = pathlib.Path(__file__).resolve().parents[1]


class FakeEntry:
    def __init__(self, eid: str, text: str, kind: str = "notiz", anchors=()):
        self.id, self.text, self.kind, self.anchors = eid, text, kind, tuple(anchors)


# --------------------------------------------------------------------------
# Die Grenze: Ableitbares gehoert nicht ins Ledger
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Der Fix steckt in 4b9c078 und wurde gemergt",
    "Nach dem Umbau: 354 passed",
    "HEAD steht auf dem Revert-Commit",
    "Aktueller Branch ist claude/foo",
    "722 getrackte Dateien im Index",
])
def test_guard_catches_derivable_facts(text, monkeypatch):
    """Alles hier kann ein Skript aus git rekonstruieren. Im Ledger ist es
    Redundanz, und Redundanz verrottet zu Drift."""
    monkeypatch.setattr(ms, "SUPERSEDED", ())
    monkeypatch.setattr(ms, "_load_continuity",
                        lambda: type("M", (), {"Ledger": type("L", (), {
                            "load": staticmethod(lambda: type("X", (), {
                                "entries": [FakeEntry("e1", text)]})())})})())
    assert [v for v in ms.guard() if v.where.startswith("ledger/")]


@pytest.mark.parametrize("text", [
    "Wir haben Axum verworfen, weil der handgerollte Server weniger Abhaengigkeiten hat",
    "Sackgasse: Embeddings fuer Konsens brauchen einen weiteren Modellaufruf",
    "Invariante: Push auf claude/* ist erlaubt, auf main nie",
    "Offen: Geraetebindung des Owner-Tokens",
])
def test_guard_leaves_genuine_memory_alone(text, monkeypatch):
    """Gegentest zum vorigen: nichts davon ist aus git ableitbar. Ein Waechter,
    der auch das meldet, wird abgeschaltet und bewacht dann gar nichts."""
    monkeypatch.setattr(ms, "SUPERSEDED", ())
    monkeypatch.setattr(ms, "_load_continuity",
                        lambda: type("M", (), {"Ledger": type("L", (), {
                            "load": staticmethod(lambda: type("X", (), {
                                "entries": [FakeEntry("e1", text)]})())})})())
    assert not [v for v in ms.guard() if v.where.startswith("ledger/")]


def test_guard_reports_surviving_predecessors(tmp_path, monkeypatch):
    alt = tmp_path / "alte_uebergabe.md"
    alt.write_text("x")
    monkeypatch.setattr(ms, "SUPERSEDED", (alt,))
    monkeypatch.setattr(ms, "REPO", tmp_path)
    monkeypatch.setattr(ms, "_load_continuity", lambda: None)
    v = ms.guard()
    assert v and "Vorgaenger" in v[0].detail


def test_predecessors_are_actually_gone():
    """Der eigentliche Auftrag: eine dritte Fassung NEBEN zwei alten waere die
    Verschlimmerung des Problems."""
    for p in ms.SUPERSEDED:
        assert not p.exists(), f"{p} existiert noch"


def test_broken_ledger_does_not_kill_the_run(monkeypatch):
    def boom():
        raise RuntimeError("kaputt")
    monkeypatch.setattr(ms, "SUPERSEDED", ())
    monkeypatch.setattr(ms, "_load_continuity",
                        lambda: type("M", (), {"Ledger": type("L", (), {
                            "load": staticmethod(boom)})})())
    v = ms.guard()
    assert any("nicht lesbar" in x.detail for x in v)


def test_guard_without_continuity_is_not_fatal(monkeypatch):
    monkeypatch.setattr(ms, "SUPERSEDED", ())
    monkeypatch.setattr(ms, "_load_continuity", lambda: None)
    assert ms.guard() == []


# --------------------------------------------------------------------------
# Die Ausgabe
# --------------------------------------------------------------------------

def test_brief_contains_both_halves():
    out = ms.brief()
    assert "## Gemessen" in out and "## Getragen" in out
    assert "## Grenzwache" in out


def test_brief_states_the_rule_so_it_survives_a_context_reset():
    """Die Regel muss IN der Uebergabe stehen. Eine Grenze, die nur im
    Quelltext dokumentiert ist, kennt die naechste Sitzung nicht."""
    out = ms.brief()
    assert "ableitbar" in out.lower()
    assert "guard" in out


def test_measured_half_is_recomputed_not_stored():
    m = ms.measured()
    assert set(m) >= {"branch", "head", "unpushed", "tracked", "findings"}
    assert isinstance(m["tracked"], int) and m["tracked"] > 0


def test_output_target_is_the_single_handoff_file():
    assert ms.OUT == REPO / "HANDOFF.md"


def test_cli_guard_exit_code_signals_violations(monkeypatch, capsys):
    monkeypatch.setattr(ms, "guard", lambda: [])
    assert ms.main(["guard"]) == 0
    monkeypatch.setattr(ms, "guard", lambda: [ms.Violation("x", "y")])
    assert ms.main(["guard"]) == 1
