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


def test_start_check_ignores_what_only_limits_capability(monkeypatch):
    """Der Fehler, den diese Betriebsart behebt: die uebergebene Startzeile

        python3 scripts/hugin_clarity.py --offen && cargo run -p hm-gateway

    startete das Gateway NIE, weil ein nicht heruntergeladenes 6,6-GB-Modell
    den Ausgang auf 1 setzte. Ein Vorschalt-Check, der bei jeder
    Unvollstaendigkeit den Start verweigert, wird umgangen — und ist dann
    schlechter als keiner.
    """
    nur_begrenzend = lambda: [                                   # noqa: E731
        hc.Punkt("modell", "Lokales Modell da?", hc.OFFEN, "fehlt", braucht="gguf")]
    monkeypatch.setattr(hc, "GRUPPEN", (("g", nur_begrenzend),))
    assert hc.main(["--start"]) == 0, "Begrenzung darf den Start nicht verweigern"
    assert hc.main([]) == 1, "als Befund bleibt es offen"


def test_start_check_still_stops_a_real_blocker(monkeypatch):
    """Gegentest: ohne ihn wuerde --start alles durchwinken."""
    blocker = lambda: [                                          # noqa: E731
        hc.Punkt("token", "Token da?", hc.EXTERN, "HM_OWNER_TOKEN fehlt",
                 befehl="eval ...", blockiert_start=True)]
    monkeypatch.setattr(hc, "GRUPPEN", (("g", blocker),))
    assert hc.main(["--start"]) == 1


def test_only_a_genuine_startup_blocker_carries_the_flag():
    """Das Gateway startet ohne Owner-Token absichtlich nicht — das ist die
    einzige Sperre dieser Art. Waechst die Menge unbemerkt, ist die
    Unterscheidung wieder verloren."""
    markiert = {p.id for _, ps in hc.sammle() for p in ps if p.blockiert_start}
    assert markiert <= {"owner-token"}, f"unerwartete Startsperre: {markiert}"
