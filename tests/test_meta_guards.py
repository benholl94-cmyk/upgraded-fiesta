"""Metatests: prüfen die Wachen, oder sehen sie nur so aus?

CLAUDE.md hält als Invariante fest: *„Jede Wache braucht einen Gegentest, der
sie scheitern lässt. Eine Regel, die nur am Gutfall geprüft wird, kann fast
alles durchwinken und sieht trotzdem grün aus."* Diese Invariante stand bisher
nur als Satz da — sie wurde von Hand befolgt und von nichts nachgerechnet.

Genau das ist die Fehlerklasse, an der dieses Repo mehrfach gelitten hat:

* 511 grüne Tests, während die zentrale Dispatch-Strecke tot war
* zwei Shell-Tests, die `FAIL:` drucken und trotzdem Exit 0 melden
* ein Workflow, der nie einen Job startete und in keiner PR-Checkliste stand

Ein Test, der nicht scheitern kann, beweist nichts. Diese Datei rechnet das
nach, statt es zu glauben: sie bricht jede Invariante **absichtlich** und
verlangt, dass genau die Wache fällt, die für sie zuständig ist.

Der Nutzen ist unmittelbar und nicht theoretisch: schlägt ein Fall hier fehl,
ist die zugehörige Wache **wirkungslos geworden** — und das erfährt man hier,
statt beim nächsten Ausfall im Betrieb.

Die Mutationen werden im Arbeitsbaum vorgenommen und in `finally` aus dem
gehaltenen Original zurückgeschrieben. Ein Kopieren des Repos wäre sauberer,
aber langsam genug, dass der Test in CI übersprungen würde — und eine Wache,
die aus Zeitgründen nicht läuft, ist keine.
"""
from __future__ import annotations

import contextlib
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


# ─────────────────────────────────────────────────────────────────────────────
# Werkzeug
# ─────────────────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def mutiert(pfad: str, alt: str, neu: str):
    """Ersetzt `alt` durch `neu` und stellt die Datei danach sicher wieder her.

    Schlägt fehl, wenn `alt` nicht vorkommt — sonst würde die Mutation
    wirkungslos bleiben und der Metatest genau das prüfen, was er widerlegen
    soll: dass eine Wache auch ohne Defekt fällt.
    """
    p = REPO / pfad
    original = p.read_bytes()
    text = original.decode("utf-8")
    if alt not in text:
        pytest.fail(
            f"Mutationsvorlage nicht mehr in {pfad} gefunden.\n"
            f"Gesucht: {alt[:120]!r}\n"
            "Der Code wurde umgebaut — dieser Metatest prüft damit nichts mehr "
            "und muss nachgezogen werden."
        )
    try:
        p.write_bytes(text.replace(alt, neu, 1).encode("utf-8"))
        yield
    finally:
        p.write_bytes(original)


def wache(*pytest_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *pytest_args, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )


def verlangt_rot(ergebnis: subprocess.CompletedProcess, wache_name: str, defekt: str):
    assert ergebnis.returncode != 0, (
        f"{wache_name} blieb GRÜN, obwohl {defekt}.\n"
        "Die Wache ist wirkungslos — sie deckt ihre eigene Fehlerklasse nicht mehr ab.\n"
        f"--- Ausgabe ---\n{ergebnis.stdout[-1500:]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Die Wachen müssen bei ihrem eigenen Defekt fallen
# ─────────────────────────────────────────────────────────────────────────────

def test_guard_catches_stdout_pollution_in_the_plugin_protocol():
    """Defekt: `autonomy_core._log()` schreibt wieder in die Protokollzeile.

    Im Betrieb sichtbar geworden als `invalid type: integer` — serde las
    `[20:23:20] heal: …` als Sequenz, deren erstes Element gegen `ok: bool`
    lief. Feuert genau dann, wenn die Selbstheilung tatsächlich heilt.
    """
    with mutiert(
        "plugins/autonomy_pulse_plugin.py",
        "    with contextlib.redirect_stdout(sys.stderr):\n        pulse_state",
        "    if True:\n        pulse_state",
    ):
        # `if True:` statt der Umleitung — die Einrückung bleibt gültig,
        # die Trennung der Kanäle fällt weg.
        verlangt_rot(
            wache("tests/test_autonomy_pulse_plugin.py"),
            "tests/test_autonomy_pulse_plugin.py",
            "die stdout-Umleitung entfernt wurde",
        )


def test_guard_catches_an_unparseable_workflow_file():
    """Defekt: ein `": "` in einem unquotierten YAML-Wert.

    GitHub startet eine solche Datei nicht — `total_jobs: 0`, `failure`, bei
    jedem Push auf jeden Branch. Lag stundenlang auf `main` und stand in
    keiner PR-Checkliste.
    """
    with mutiert(
        ".github/workflows/ci.yml",
        "  rust:\n",
        "  rust:\n    # kaputt: Doppelpunkt im plain scalar\n    beschreibung: wert: mit doppelpunkt\n",
    ):
        verlangt_rot(
            wache("tests/test_workflows_parse.py"),
            "tests/test_workflows_parse.py",
            "eine Workflow-Datei ungültiges YAML wurde",
        )


def test_guard_catches_icons_drifting_from_their_generator():
    """Defekt: ein PNG im Repo entspricht nicht mehr `generate_hugin_icons.py`.

    Ein eingechecktes Binärartefakt ohne Generator veraltet stumm — genau
    deshalb prüft die Wache Datei gegen Generator statt gegen ein Abbild.
    """
    p = REPO / "hugin" / "icon-192.png"
    original = p.read_bytes()
    try:
        p.write_bytes(original[:-40] + b"\x00" * 40)
        verlangt_rot(
            wache("tests/test_hugin_icons.py"),
            "tests/test_hugin_icons.py",
            "ein Icon vom Generator abwich",
        )
    finally:
        p.write_bytes(original)


def test_guard_catches_a_command_running_without_its_artefacts():
    """Defekt: `Command.braucht` wird geleert.

    Dann läuft ein Chat-Befehl im Laufzeit-Image wieder los, dem `crates/`
    oder `tests/` fehlt — und antwortet mit einem Traceback, einem
    Schein-VIOLATION oder einer leeren, grün wirkenden Testsuite.
    """
    with mutiert(
        "agents/brain.py",
        'braucht=("Cargo.toml", "crates")),',
        "braucht=()),",
    ):
        verlangt_rot(
            wache("tests/test_brain.py"),
            "tests/test_brain.py",
            "eine Befehls-Voraussetzung entfernt wurde",
        )


def test_guard_catches_a_desynced_index_html():
    """Defekt: `index.html` weicht von `hugin.html` ab.

    Die ausgelieferte Datei auf GitHub Pages ist `index.html`; weicht sie ab,
    ist die geprüfte Fassung nicht die betriebene.
    """
    p = REPO / "hugin" / "index.html"
    original = p.read_bytes()
    try:
        p.write_bytes(original + b"\n<!-- Drift -->\n")
        ergebnis = subprocess.run(
            [sys.executable, "scripts/repo_tracker.py", "audit"],
            cwd=REPO, capture_output=True, text=True, timeout=300,
        )
        assert "hugin_index_sync" in ergebnis.stdout
        assert "✗ hugin_index_sync" in ergebnis.stdout or ergebnis.returncode != 0, (
            "Die Synergie-Regel hugin_index_sync blieb grün, obwohl index.html "
            f"abwich.\n{ergebnis.stdout[-800:]}"
        )
    finally:
        p.write_bytes(original)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Kein Test ohne lebendes Subjekt
# ─────────────────────────────────────────────────────────────────────────────
#
# Gefunden hat diese Prüfung zwei echte Waisen in `main`:
# `tests/test_codex_cloud_setup.sh` und `tests/test_validate_iphone_control_plane.sh`
# prüften Skripte, die es nicht mehr gibt — und meldeten dabei Exit 0, während
# sie `FAIL:` ausgaben. Dreifach wirkungslos: falsches Subjekt, falscher
# Exit-Code, und von `pytest` nie eingesammelt.

def _shell_tests() -> list[pathlib.Path]:
    return sorted((REPO / "tests").glob("*.sh"))


@pytest.mark.parametrize("test_datei", _shell_tests(), ids=lambda p: p.name)
def test_every_shell_test_has_a_subject_that_exists(test_datei: pathlib.Path):
    """Ein Test, dessen Subjekt fehlt, prüft nichts und sagt es nicht."""
    import re

    inhalt = test_datei.read_text(encoding="utf-8")
    subjekte = {
        m.group(1)
        for m in re.finditer(r'\$REPO_ROOT/([A-Za-z0-9_/.-]+\.(?:sh|py|mjs))', inhalt)
    }
    fehlend = sorted(s for s in subjekte if not (REPO / s).exists())
    assert not fehlend, (
        f"{test_datei.name} prüft nicht vorhandene Dateien: {fehlend}.\n"
        "Entweder wurde das Subjekt entfernt und der Test blieb liegen, oder "
        "das Subjekt fehlt versehentlich. Beides muss aufgelöst werden — ein "
        "Test ohne Subjekt ist kein Schutz, sondern ein Platzhalter, der wie "
        "einer aussieht."
    )


@pytest.mark.parametrize("test_datei", _shell_tests(), ids=lambda p: p.name)
def test_every_shell_test_reports_failure_through_its_exit_code(test_datei: pathlib.Path):
    """Ein Test, der `FAIL` druckt und 0 zurückgibt, ist schlimmer als keiner.

    Er wird von jeder Automatisierung als bestanden gewertet. Beide
    Shell-Tests dieses Repos hatten genau diesen Defekt.
    """
    inhalt = test_datei.read_text(encoding="utf-8")
    assert "exit" in inhalt, f"{test_datei.name} setzt nirgends einen Exit-Code"
    assert ("FAIL" not in inhalt) or ("exit 1" in inhalt or "exit $" in inhalt), (
        f"{test_datei.name} kennt einen FAIL-Zustand, beendet sich aber nirgends "
        "mit einem Fehlercode."
    )


def test_shell_tests_are_actually_executed_somewhere():
    """`pytest` sammelt keine `.sh`-Dateien.

    Liegt ein Shell-Test im Verzeichnis, ohne dass ihn ein Workflow aufruft,
    läuft er nie — und niemand merkt es, weil das Verzeichnis voll aussieht.
    """
    tests = _shell_tests()
    if not tests:
        pytest.skip("keine Shell-Tests vorhanden")

    workflows = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (REPO / ".github" / "workflows").glob("*.yml")
    )
    nie_gerufen = [t.name for t in tests if t.name not in workflows]
    assert not nie_gerufen, (
        f"Diese Shell-Tests ruft kein Workflow auf: {nie_gerufen}.\n"
        "pytest sammelt keine .sh-Dateien — sie laufen also nirgends. "
        "Entweder in einen Workflow aufnehmen oder entfernen."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Verbindungsrouten: was das Gateway kann, muss dokumentiert sein
# ─────────────────────────────────────────────────────────────────────────────

def test_every_gateway_route_appears_in_the_api_contract():
    """Eine Route, die niemand dokumentiert, wird von niemandem benutzt —
    oder schlimmer: falsch benutzt.

    `/sessions` war real, getestet und stand in der Routenliste von CLAUDE.md
    nicht. Gefunden wurde das von Hand; ab hier findet es diese Wache.
    """
    import re

    quelle = (REPO / "crates" / "hm-gateway" / "src" / "main.rs").read_text(encoding="utf-8")
    vertrag = (REPO / "docs" / "production-api-contract.md").read_text(encoding="utf-8")

    routen = set()
    for m in re.finditer(r'\("(GET|POST|PUT|DELETE)",\s*"(/[a-z/{}._-]*)"\)', quelle):
        pfad = m.group(2)
        wurzel = "/" + pfad.strip("/").split("/")[0] if pfad != "/" else "/"
        routen.add(wurzel)

    # Aliasse (/api/…, /gateway/…) sind dieselbe Route unter anderem Praefix.
    routen = {r for r in routen if r not in ("/", "/api", "/gateway")}
    assert routen, "keine Routen aus main.rs erkannt — Parser veraltet?"

    undokumentiert = sorted(r for r in routen if r not in vertrag)
    assert not undokumentiert, (
        f"Diese Routen bedient das Gateway, der API-Vertrag kennt sie nicht: "
        f"{undokumentiert}.\nEine undokumentierte Route ist eine Verbindung, "
        "die nur der kennt, der sie geschrieben hat."
    )


def test_every_plugin_in_the_manifest_has_an_existing_program():
    """Ein Manifest-Eintrag, dessen Programm fehlt, wird zur Laufzeit zu
    `failed to spawn` — und zwar erst dann, wenn der Task ausgelöst wird.

    `ops-tool` zeigte auf `target/release/hm-tool-exec` und scheiterte in
    jedem Debug-Build alle sechs Stunden.
    """
    import json
    import shutil

    manifest = json.loads((REPO / "config" / "plugins.json").read_text(encoding="utf-8"))
    kaputt = []
    for eintrag in manifest["plugins"]:
        programm = eintrag["command"][0]
        if "/" in programm:
            pfad = REPO / programm
            # Build-Profil-Pfade dürfen fehlen: resolve_program weicht auf das
            # Geschwisterprofil aus, und im Container liegt genau der Release-Pfad.
            if "target/" in programm:
                continue
            if not pfad.exists():
                kaputt.append((eintrag["task_type"], programm))
        elif shutil.which(programm) is None:
            kaputt.append((eintrag["task_type"], programm))

        for arg in eintrag["command"][1:]:
            if arg.endswith((".py", ".sh")) and not (REPO / arg).exists():
                kaputt.append((eintrag["task_type"], arg))

    assert not kaputt, (
        f"Diese Plugin-Einträge zeigen ins Leere: {kaputt}.\n"
        "Der Fehler tritt sonst erst auf, wenn der Task ausgelöst wird."
    )
