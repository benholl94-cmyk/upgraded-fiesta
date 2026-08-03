"""Verlauf und Sperrklinke — vom Messen zum Schieben.

## Der Unterschied, um den es geht

Eine Kurve **zeigt**, dass etwas schlechter wurde. Eine Sperrklinke
**verbietet** es. Dieses Repo hat in einer einzigen Sitzung dreimal erlebt,
dass etwas leise zurueckfiel, ohne dass ein Test rot war:

* zwei Tests uebersprangen sich mangels Binary — die Testzahl sank, alles
  meldete gruen;
* das Inventar meldete 34 Befunde, von denen neun erfunden waren;
* der Korpus veraltete nach jedem Squash-Merge.

Keiner dieser Faelle war ein Fehlschlag. Alle drei waren **Rueckschritte
gegenueber einem Stand, der schon einmal erreicht war** — und genau das ist
die Luecke, die eine Sperrklinke schliesst.

## Warum der Umgebungs-Fingerabdruck traegt

Auf dem Runner laeuft kein Gateway, und der Klon ist flach. Ein Bestwert
aus dem vollen lokalen Klon als Massstab fuer den Runner waere eine
Forderung, die dort niemand erfuellen kann — und eine Warnung, die immer
kommt, wird weggeklickt. Verglichen wird deshalb nur Gleiches mit Gleichem.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import hugin_zyklus as hz  # noqa: E402


def _lauf(**werte) -> dict:
    d = {"ts": "2026-08-02T00:00:00+00:00", "umgebung": "lokal/voll",
         "tests_bestanden": 1469, "offene_teile": 0, "korpus_faelle": 934,
         "befunde": 0, "dauer": {"tests": 50.0}}
    d.update(werte)
    return d


def _befunde(schritte) -> list[str]:
    return [s.name for s in schritte if s.stand == hz.BEFUND]


# ---------------------------------------------------------------------------
# Die Sperrklinke — sie muss halten UND sie muss loslassen koennen
# ---------------------------------------------------------------------------

def test_a_drop_below_the_best_ever_value_is_a_finding():
    """**Der Fall, der diese Datei begruendet.** Wer 1469 Tests einmal
    erreicht hat, darf nicht unbemerkt auf 1465 zurueckfallen — genau das
    ist passiert, ohne dass ein einziger Test rot war."""
    schritte = hz.sperrklinke(_lauf(tests_bestanden=1465), [_lauf()])
    assert "rueckschritt:tests_bestanden" in _befunde(schritte)


def test_progress_is_never_reported_as_regression():
    """Die Gegenprobe, ohne die die Wache unbrauchbar waere: mehr Tests
    sind mehr Tests. Eine geratene Richtung meldete Fortschritt als
    Rueckschritt."""
    schritte = hz.sperrklinke(_lauf(tests_bestanden=1500), [_lauf()])
    assert not _befunde(schritte)


def test_the_direction_is_declared_not_guessed():
    """Bei `offene_teile` ist *weniger* besser, bei `tests_bestanden*
    *mehr*. Ohne die Tabelle muesste die Auswertung raten."""
    assert hz.KENNZAHLEN["offene_teile"] < 0
    assert hz.KENNZAHLEN["tests_bestanden"] > 0
    schritte = hz.sperrklinke(_lauf(offene_teile=3), [_lauf(offene_teile=0)])
    assert "rueckschritt:offene_teile" in _befunde(schritte)


def test_the_best_value_wins_not_the_last_one():
    """Eine Sperrklinke, die nur den Vorlauf vergleicht, laesst sich in
    kleinen Schritten unterlaufen: 1469 → 1467 → 1465, jedes Mal ohne
    Befund."""
    verlauf = [_lauf(tests_bestanden=1469), _lauf(tests_bestanden=1467)]
    schritte = hz.sperrklinke(_lauf(tests_bestanden=1466), verlauf)
    assert "rueckschritt:tests_bestanden" in _befunde(schritte)


def test_every_regression_names_the_command_that_investigates_it():
    """Ein Befund ohne Befehl ist eine Beschwerde."""
    schritte = hz.sperrklinke(_lauf(tests_bestanden=1400, offene_teile=5),
                              [_lauf()])
    for s in schritte:
        if s.stand == hz.BEFUND:
            assert s.befehl, s.name


# ---------------------------------------------------------------------------
# Der Umgebungs-Fingerabdruck — sonst waere die Klinke schaedlich
# ---------------------------------------------------------------------------

def test_a_different_environment_is_never_the_yardstick():
    """Auf dem Runner laeuft kein Gateway und der Klon ist flach. Ein
    lokaler Bestwert als Massstab dort waere eine Forderung, die niemand
    erfuellen kann."""
    schritte = hz.sperrklinke(_lauf(umgebung="ci/flach", tests_bestanden=1400),
                              [_lauf(umgebung="lokal/voll")])
    assert not _befunde(schritte)


def test_the_first_run_in_an_environment_sets_the_floor():
    schritte = hz.sperrklinke(_lauf(umgebung="neu/voll"), [])
    assert not _befunde(schritte)
    assert "Untergrenze" in schritte[0].zeilen[0]


def test_the_fingerprint_distinguishes_ci_from_local():
    marke = hz._umgebung()
    assert marke.count("/") == 1
    assert marke.split("/")[0] in ("ci", "lokal")
    assert marke.split("/")[1] in ("flach", "voll")


# ---------------------------------------------------------------------------
# Laufzeit — Effizienz, nicht nur Richtigkeit
# ---------------------------------------------------------------------------

def test_a_clear_slowdown_is_a_finding():
    schritte = hz.sperrklinke(_lauf(dauer={"tests": 80.0}),
                              [_lauf(dauer={"tests": 50.0})])
    assert any(s.name == "langsamer:tests" for s in schritte)


def test_normal_fluctuation_is_not_a_finding():
    """25 % statt 10 %: Runner schwanken, und eine Warnung, die bei jedem
    zweiten Lauf kommt, wird weggeklickt."""
    schritte = hz.sperrklinke(_lauf(dauer={"tests": 58.0}),
                              [_lauf(dauer={"tests": 50.0})])
    assert not any(s.name.startswith("langsamer") for s in schritte)


def test_short_steps_are_not_measured_for_speed():
    """Unter 5 s ist Rauschen. Eine Verdopplung von 0,4 s auf 0,9 s ist
    kein Trend, sondern Planung des Betriebssystems."""
    schritte = hz.sperrklinke(_lauf(dauer={"index": 4.0}),
                              [_lauf(dauer={"index": 1.0})])
    assert not any(s.name.startswith("langsamer") for s in schritte)


def test_the_runtime_compares_to_the_previous_run_not_the_best():
    """Ein einmal schneller Lauf (warmer Cache) waere sonst fuer immer der
    Massstab — und jeder normale Lauf ein Befund."""
    verlauf = [_lauf(dauer={"tests": 20.0}), _lauf(dauer={"tests": 50.0})]
    schritte = hz.sperrklinke(_lauf(dauer={"tests": 52.0}), verlauf)
    assert not any(s.name.startswith("langsamer") for s in schritte)


# ---------------------------------------------------------------------------
# Messwerte — fehlend heisst fehlend, nie null
# ---------------------------------------------------------------------------

def test_a_missing_measurement_is_skipped_not_counted_as_zero():
    """Eine fehlende Messung als Null zu fuehren, erzeugt einen Absturz in
    der Kurve, den es nie gegeben hat."""
    ohne = _lauf()
    del ohne["tests_bestanden"]
    schritte = hz.sperrklinke(ohne, [_lauf()])
    assert "rueckschritt:tests_bestanden" not in _befunde(schritte)


def test_the_measurements_come_from_the_steps_not_from_guesses():
    schritte = [hz.Schritt("tests", "pruefen", hz.OK, 12.0,
                           ["1469 passed in 52.65s"]),
                hz.Schritt("inventar", "messen", hz.OK, 1.0,
                           ["[OFFEN ] a", "[OFFEN ] b"])]
    w = hz._messwerte(schritte)
    assert w["tests_bestanden"] == 1469
    assert w["offene_teile"] == 2
    assert w["dauer"]["tests"] == 12.0


# ---------------------------------------------------------------------------
# Der Verlauf selbst
# ---------------------------------------------------------------------------

def test_a_broken_line_does_not_cost_the_whole_history():
    """Eine kaputte Zeile in einer angehaengten Datei ist wahrscheinlich —
    ein Absturz beim Schreiben genuegt. Sie darf die anderen nicht
    mitnehmen."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "verlauf.jsonl"
        p.write_text('{"ts":"a"}\n{kaputt\n{"ts":"b"}\n', encoding="utf-8")
        alt = hz.VERLAUF
        try:
            hz.VERLAUF = p
            assert len(hz.verlauf_lesen()) == 2
        finally:
            hz.VERLAUF = alt


def test_the_comparison_stage_runs_last():
    """Sie bewertet, was die Stufen davor gemessen haben. Davor haette sie
    den Stand von vorhin bewertet."""
    assert hz.STUFEN[-1] == "vergleichen"


def test_the_dry_run_writes_no_history():
    """Ein Vorlauf, der die Reihe fortschreibt, faelscht sie: er misst
    einen Zustand, den er nicht hergestellt hat."""
    quelle = (REPO / "scripts" / "hugin_zyklus.py").read_text(encoding="utf-8")
    block = quelle.partition('elif stufe == "vergleichen"')[2].partition("return aus")[0]
    assert "if apply else" in block, "der Vorlauf schreibt in den Verlauf"
