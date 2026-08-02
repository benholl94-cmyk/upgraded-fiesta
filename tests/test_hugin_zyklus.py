"""Die Kette — laeuft sie, und trennt sie Befund von Defekt?

Der Zyklus ruft die Werkzeuge auf, die dieses Repo ohnehin hat. Sein
eigener Beitrag ist genau zwei Dinge, und beide sind hier gepruefft:

1. **Die Reihenfolge** — erden vor pruefen, heilen vor pruefen. Ein
   veralteter Korpus laesst den Kern auf einen Stand antworten, den es nicht
   mehr gibt; ein Pruefen vor dem Heilen misst den Zustand von vorhin.
2. **Die Trennung von Befund und Defekt.** Ein Werkzeug, das mit 1 endet,
   hat gearbeitet und etwas gefunden. Eines, das mit 127 endet, gibt es
   nicht. Beides als Fehlschlag zu fuehren hiesse, ein defektes Thermometer
   wie Fieber zu behandeln.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import hugin_zyklus as hz  # noqa: E402


# ---------------------------------------------------------------------------
# Reihenfolge
# ---------------------------------------------------------------------------

def test_the_order_follows_dependency_not_convenience():
    """Erden vor Pruefen, Heilen vor Pruefen. Andernfalls prueft der Zyklus
    den Zustand von vorhin und meldet ihn als den von jetzt."""
    assert hz.STUFEN.index("erden") < hz.STUFEN.index("pruefen")
    assert hz.STUFEN.index("heilen") < hz.STUFEN.index("pruefen")
    assert hz.STUFEN.index("messen") == 0


def test_every_stage_is_reachable(monkeypatch):
    """**Nicht die echten Werkzeuge starten.** Die erste Fassung rief
    `zyklus()` je Stufe wirklich auf — und die Stufe `pruefen` startet
    `pytest tests/`. Ein Test, der die Suite startet, in der er selbst
    laeuft, ist eine Rekursion mit Zeitplan: der Lauf dauerte ueber zehn
    Minuten und haette in CI das Zeitfenster gesprengt.

    Geprueft wird die Verteilung, nicht die Wirkung der Werkzeuge — die
    haben ihre eigenen Tests."""
    monkeypatch.setattr(hz, "_schritt",
                        lambda name, stufe, argv, **k: hz.Schritt(name, stufe))
    for stufe in hz.STUFEN:
        schritte = hz.zyklus(apply=False, nur={stufe})
        assert schritte, f"Stufe {stufe} liefert nichts"
        assert all(s.stufe == stufe for s in schritte)


def test_the_check_stage_runs_the_suite_and_is_therefore_never_run_here():
    """Gegenprobe zur Regel oben: die Stufe `pruefen` startet wirklich
    `pytest`. Wer sie in einem Test aufruft, baut eine Rekursion — deshalb
    steht das hier als Tatsache und nicht als Vertrauenssache."""
    quelle = (REPO / "scripts" / "hugin_zyklus.py").read_text(encoding="utf-8")
    block = quelle.partition("def s_pruefen(")[2].partition("\ndef ")[0]
    assert "pytest" in block


# ---------------------------------------------------------------------------
# Befund ist nicht Defekt — der eigentliche Beitrag
# ---------------------------------------------------------------------------

def test_a_tool_that_found_something_is_a_finding_not_a_failure():
    s = hz._schritt("probe", "pruefen", ["-c", "raise SystemExit(1)"])
    assert s.stand == hz.BEFUND


def test_a_missing_tool_is_a_defect_not_a_finding():
    """**Der Unterschied, der zaehlt.** Ein offener Befund ist Arbeit, eine
    gescheiterte Kette ist ein kaputtes Messgeraet."""
    s = hz._schritt("probe", "pruefen", ["scripts/gibt-es-nicht.py"])
    assert s.stand == hz.GESCHEITERT


def test_a_switch_is_not_mistaken_for_a_missing_file():
    """**Eigener Fehler, beim ersten Lauf gefunden.** `-m pytest` ist ein
    Schalter, keine Datei — die erste Fassung hielt ihn fuer eine fehlende
    Datei und meldete den Testschritt als GESCHEITERT. Der Zyklus hat damit
    seinen eigenen Defekt korrekt als Defekt gemeldet und nicht als Befund;
    genau dafuer sind die Ausgaenge getrennt."""
    s = hz._schritt("probe", "pruefen", ["-c", "pass"])
    assert s.stand == hz.OK


def test_a_crashing_tool_is_a_defect(tmp_path, monkeypatch):
    s = hz._schritt("probe", "pruefen", ["-c", "raise SystemExit(127)"])
    assert s.stand == hz.GESCHEITERT


def test_defect_outranks_finding_in_the_exit_code(monkeypatch):
    """`2` schlaegt `1`. Wer beides zusammenwirft, behandelt ein defektes
    Thermometer wie Fieber."""
    monkeypatch.setattr(hz, "zyklus", lambda apply, nur: [
        hz.Schritt("a", "pruefen", hz.BEFUND),
        hz.Schritt("b", "pruefen", hz.GESCHEITERT),
    ])
    assert hz.main([]) == 2


def test_only_findings_yield_one(monkeypatch):
    monkeypatch.setattr(hz, "zyklus", lambda apply, nur: [
        hz.Schritt("a", "pruefen", hz.BEFUND)])
    assert hz.main([]) == 1


def test_a_clean_run_yields_zero(monkeypatch):
    monkeypatch.setattr(hz, "zyklus", lambda apply, nur: [
        hz.Schritt("a", "pruefen", hz.OK)])
    assert hz.main([]) == 0


# ---------------------------------------------------------------------------
# Ohne --apply wird nichts geschrieben
# ---------------------------------------------------------------------------

def test_the_dry_run_writes_nothing():
    """Ein Zyklus, der bei jedem Aufruf ungefragt den Baum aendert, waere in
    CI nicht einsetzbar — und einer, der nicht in CI laeuft, laeuft
    nirgends."""
    vorher = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                            capture_output=True, text=True, timeout=120).stdout
    hz.zyklus(apply=False, nur={"messen"})
    nachher = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                             capture_output=True, text=True, timeout=120).stdout
    assert vorher == nachher


def test_the_corpus_fingerprint_ignores_the_timestamp():
    """Sonst gilt jeder Lauf als 'geaendert' — und eine Meldung, die immer
    kommt, wird nicht gelesen."""
    a = hz._korpus_stand()
    b = hz._korpus_stand()
    assert a == b
    assert "erzeugt" not in a


# ---------------------------------------------------------------------------
# Bericht und CLI
# ---------------------------------------------------------------------------

def test_every_finding_names_the_command_that_closes_it():
    """Ein Befund ohne Befehl ist eine Beschwerde."""
    for s in hz.zyklus(apply=False, nur={"messen"}):
        if s.stand != hz.OK:
            assert s.befehl


def test_an_unknown_stage_is_refused_not_silently_ignored():
    assert hz.main(["--nur", "gibt-es-nicht"]) == 2


def test_the_cli_speaks_json():
    r = subprocess.run([sys.executable, "scripts/hugin_zyklus.py",
                        "--json", "--nur", "messen"],
                       cwd=REPO, capture_output=True, text=True, timeout=900)
    d = json.loads(r.stdout)
    assert d["apply"] is False
    assert d["schritte"] and "stand" in d["schritte"][0]


def test_the_report_lists_every_stage_that_ran():
    schritte = hz.zyklus(apply=False, nur={"messen"})
    text = hz.bericht(schritte)
    assert "## messen" in text
    assert "erden" not in text.split("## messen")[0]


# ---------------------------------------------------------------------------
# Der Workflow, der die Kette faehrt
# ---------------------------------------------------------------------------

WF = REPO / ".github" / "workflows" / "zyklus.yml"


def test_the_cycle_workflow_exists_and_parses():
    yaml = pytest.importorskip("yaml")
    d = yaml.safe_load(WF.read_text(encoding="utf-8"))
    ausloeser = d.get("on", d.get(True))
    assert "schedule" in ausloeser, "Kette ohne Zeitplan laeuft nur von Hand"
    assert "workflow_dispatch" in ausloeser


def test_the_cycle_never_pushes_to_the_default_branch():
    """**Die Grenze der Verfassung, maschinell nachgerechnet.** Merge und
    Push auf den Default-Branch brauchen einen Master-Befehl. Eine Routine,
    die sich diese Grenze nimmt, waere von einer legitimen Entscheidung
    nicht mehr zu unterscheiden."""
    text = WF.read_text(encoding="utf-8")
    for verboten in ("push origin main", "git push origin HEAD:main",
                     "--force", "merge_pull_request"):
        assert verboten not in text, f"Zyklus tut Verbotenes: {verboten}"
    assert "claude/" in text, "Zyklus schreibt nicht auf einen eigenen Branch"


def test_the_cycle_uses_only_the_built_in_token():
    import re
    text = WF.read_text(encoding="utf-8")
    fremde = [m.group(1) for m in re.finditer(r"secrets\.([A-Z_]+)", text)
              if m.group(1) != "GITHUB_TOKEN"]
    assert not fremde, f"fremde Secrets verlangt: {fremde}"
