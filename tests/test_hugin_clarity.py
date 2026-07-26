"""Tests des Klarheits-Pruefers.

Der Pruefer existiert, weil eine Liste offener Punkte in einer Markdown-Datei
am Tag ihrer Entstehung richtig ist und danach nie wieder. Also muss er selbst
das aushalten, was er behauptet: jeder Punkt nennt einen gemessenen Wert, und
kein Zustand wird geraten.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import hugin_clarity as hc  # noqa: E402


def _alle():
    return [p for _, punkte in hc.sammle() for p in punkte]


def test_every_point_reports_a_measured_value():
    """`gemessen` ist Pflicht. Ein Punkt ohne Messung ist eine Meinung."""
    for p in _alle():
        assert p.gemessen.strip(), f"{p.id} ohne gemessenen Wert"
        assert p.frage.strip().endswith("?"), f"{p.id} stellt keine Frage"


def test_every_open_point_names_what_exactly_is_missing():
    """OFFEN ohne konkreten fehlenden Wert waere genau die Unschaerfe, die
    diese Datei beseitigen soll."""
    for p in _alle():
        if p.stand == hc.OFFEN:
            assert p.braucht.strip(), f"{p.id} ist offen, nennt aber nicht was fehlt"


def test_open_and_external_are_not_the_same_bucket():
    """OFFEN heisst 'noch nicht getan', EXTERN 'von hier aus nicht tubar'.
    Wer beides mischt, bekommt eine Liste, die nie leer wird."""
    staende = {p.stand for p in _alle()}
    assert staende <= {hc.OK, hc.OFFEN, hc.EXTERN}
    assert hc.EXTERN in staende, "ohne EXTERN waere die Trennung ungenutzt"


def test_a_failing_measurement_is_reported_as_open_not_swallowed(monkeypatch):
    """Der teure Fehler waere, eine gescheiterte Messung als 'in Ordnung' zu
    zaehlen — dann meldet der Pruefer Ruhe, weil er blind ist."""
    def kaputt():
        raise RuntimeError("Messung gescheitert")

    monkeypatch.setattr(hc, "GRUPPEN", (("Testgruppe", kaputt),))
    punkte = [p for _, ps in hc.sammle() for p in ps]
    assert punkte and punkte[0].stand == hc.OFFEN
    assert "Messung" in punkte[0].gemessen


def test_the_exit_code_distinguishes_open_from_external(monkeypatch):
    """Ein Ausgang, der immer 1 ist, wird ignoriert. EXTERN darf deshalb
    nicht rot faerben."""
    nur_extern = lambda: [hc.Punkt("x", "Frage?", hc.EXTERN, "gemessen")]  # noqa: E731
    monkeypatch.setattr(hc, "GRUPPEN", (("g", nur_extern),))
    assert hc.main([]) == 0

    mit_offen = lambda: [hc.Punkt("y", "Frage?", hc.OFFEN, "gemessen", braucht="X")]  # noqa: E731
    monkeypatch.setattr(hc, "GRUPPEN", (("g", mit_offen),))
    assert hc.main([]) == 1


def test_json_output_is_machine_readable():
    proc = subprocess.run([sys.executable, "scripts/hugin_clarity.py", "--json"],
                          cwd=REPO, capture_output=True, text=True, timeout=120)
    daten = json.loads(proc.stdout)
    assert daten and all("punkte" in g for g in daten)


def test_the_reachability_probe_is_a_real_connection_not_a_guess():
    """Ein Handshake gegen einen sicher geschlossenen Port muss False sein —
    sonst misst die Sonde nichts und jede Stufe gilt als tragend."""
    assert hc._tcp("127.0.0.1", 1, timeout=0.2) is False


def test_the_docker_check_reads_the_real_dockerfile():
    """Nachgerechnet, nicht behauptet: der Punkt muss kippen, wenn die Zeile
    im Dockerfile fehlt."""
    text = (REPO / "Dockerfile").read_text(encoding="utf-8")
    punkt = next(p for p in hc.p_kanal() if p.id == "container-gehirn")
    assert (punkt.stand == hc.OK) is ("COPY agents/" in text)
