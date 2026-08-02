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

## Warum die Mutationen in einer Kopie stattfinden

Bis 2026-07-31 wurde der **Arbeitsbaum** mutiert und in `finally`
zurückgeschrieben. `finally` läuft aber nicht, wenn der Prozess stirbt — und
genau das passierte: ein abgebrochener Lauf hinterließ `.github/workflows/ci.yml`
mit kaputtem YAML und ein verändertes `hugin/icon-192.png` im Baum. Ein Commit
in diesem Moment hätte den Schaden nach git getragen.

Die Folgeschäden waren messbar: Metatests plus **irgendeine** zweite Testdatei
waren in 3 von 6 Läufen rot, weil die nächste Mutation ihre Vorlage in der
bereits veränderten Datei nicht mehr fand.

Der alte Docstring begründete das Vorgehen damit, ein Kopieren sei „langsam
genug, dass der Test in CI übersprungen würde". Das war eine Annahme, keine
Messung: **378 getrackte Dateien, 3,3 MB, 0,06 s.** Die Kopie entsteht einmal
je Sitzung.

Damit ist das Fenster nicht verkleinert, sondern weg — dieselbe Auflösung wie
beim `Text file busy`-Wettlauf in `hm-plugins`, wo `/bin/sh` mit dem Skript als
*Argument* die Ursache beseitigte, statt auf sie zu warten.
"""
from __future__ import annotations

import atexit
import contextlib
import pathlib
import shutil
import tempfile
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


# ─────────────────────────────────────────────────────────────────────────────
# Werkzeug
# ─────────────────────────────────────────────────────────────────────────────

_SANDKASTEN: pathlib.Path | None = None


def sandkasten() -> pathlib.Path:
    """Eine Kopie aller getrackten Dateien, einmal je Sitzung.

    Alles, was hier mutiert wird, ist eine Kopie. Stirbt der Prozess mitten
    im Lauf, bleibt der echte Arbeitsbaum unberührt — das ist der ganze
    Zweck. Gemessen: 378 Dateien, 3,3 MB, 0,06 s.

    Kopiert wird der **Arbeitsbaum**, nicht `HEAD`: die Wachen sollen den
    Stand prüfen, an dem gerade gearbeitet wird, nicht den zuletzt
    committeten.
    """
    global _SANDKASTEN
    if _SANDKASTEN is not None and _SANDKASTEN.is_dir():
        return _SANDKASTEN

    ziel = pathlib.Path(tempfile.mkdtemp(prefix="meta-guards-"))
    roh = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, text=True, timeout=120)
    dateien = [r for r in roh.stdout.split("\0") if r]
    if not dateien:
        pytest.fail("git ls-files lieferte nichts — ohne Kopie keine Mutation")
    for rel in dateien:
        quelle = REPO / rel
        if not quelle.is_file():
            continue
        z = ziel / rel
        z.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(quelle, z)
    _SANDKASTEN = ziel
    atexit.register(shutil.rmtree, ziel, True)
    return ziel


@contextlib.contextmanager
def mutiert(pfad: str, alt: str, neu: str):
    """Ersetzt `alt` durch `neu` **in der Kopie** und stellt sie danach her.

    Schlägt fehl, wenn `alt` nicht vorkommt — sonst würde die Mutation
    wirkungslos bleiben und der Metatest genau das prüfen, was er widerlegen
    soll: dass eine Wache auch ohne Defekt fällt.
    """
    p = sandkasten() / pfad
    if not p.is_file():
        pytest.fail(f"{pfad} liegt nicht in der Kopie — ist es getrackt?")
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
        # Auch hier zurückschreiben: sonst sähe die nächste Mutation in
        # derselben Sitzung eine bereits veränderte Vorlage. Anders als früher
        # ist ein ausgefallenes `finally` jetzt aber folgenlos.
        p.write_bytes(original)


def wache(*pytest_args: str) -> subprocess.CompletedProcess:
    """Führt die zuständige Wache **in der Kopie** aus."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", *pytest_args, "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=sandkasten(), capture_output=True, text=True, timeout=600,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Die Metatests selbst: sie duerfen den Arbeitsbaum nicht beschaedigen
# ─────────────────────────────────────────────────────────────────────────────

def test_no_mutation_ever_touches_the_working_tree():
    """Der Vorfall, der die Kopie erzwang: ein abgebrochener Lauf hinterliess
    `.github/workflows/ci.yml` mit kaputtem YAML und ein veraendertes
    `hugin/icon-192.png` im Baum. `finally` laeuft nicht, wenn der Prozess
    stirbt.

    Geprueft wird die Eigenschaft, nicht der Vorsatz: nach einer echten
    Mutation muss der Arbeitsbaum unveraendert sein — waehrend die Kopie
    veraendert ist.
    """
    ziel = ".github/workflows/ci.yml"
    vorher = (REPO / ziel).read_bytes()
    with mutiert(ziel, "jobs:", "jobs:\n  # mutiert\n"):
        assert (REPO / ziel).read_bytes() == vorher, \
            "der Arbeitsbaum wurde veraendert — genau das soll die Kopie verhindern"
        assert (sandkasten() / ziel).read_bytes() != vorher, \
            "die Kopie wurde NICHT veraendert — dann mutiert der Test nichts"
    assert (REPO / ziel).read_bytes() == vorher


def test_the_sandbox_is_a_real_copy_of_the_working_tree():
    """Kopiert wird der Arbeitsbaum, nicht `HEAD`: die Wachen sollen den
    Stand pruefen, an dem gerade gearbeitet wird."""
    kopie = sandkasten()
    assert (kopie / "pyproject.toml").is_file()
    for noetig in ("agents/brain.py", "scripts/repo_tracker.py",
                   "config/plugins.json", "tests/test_brain.py"):
        assert (kopie / noetig).is_file(), f"{noetig} fehlt in der Kopie"
    # Bytegleich mit dem Arbeitsbaum, sonst prueften die Wachen etwas anderes.
    assert (kopie / "agents/brain.py").read_bytes() == (REPO / "agents/brain.py").read_bytes()


def test_the_sandbox_lives_outside_the_repository():
    """Laege sie im Repo, taeuchte sie in `git status` auf und koennte
    versehentlich committet werden."""
    assert REPO not in sandkasten().parents, "Kopie liegt innerhalb des Repos"


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
    # In die Kopie, wie jede andere Mutation. `mutiert()` arbeitet auf Text;
    # ein PNG wird byteweise verstuemmelt, deshalb hier von Hand — aber am
    # selben Ort.
    p = sandkasten() / "hugin" / "icon-192.png"
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
    p = sandkasten() / "hugin" / "index.html"
    original = p.read_bytes()
    try:
        p.write_bytes(original + b"\n<!-- Drift -->\n")
        # Der Audit muss dort laufen, wo die Mutation liegt. Mit `cwd=REPO`
        # pruefte er den unveraenderten Baum und blieb zwangslaeufig gruen —
        # der Metatest haette dann seine eigene Wirkungslosigkeit gemeldet.
        ergebnis = subprocess.run(
            [sys.executable, "scripts/repo_tracker.py", "audit"],
            cwd=sandkasten(), capture_output=True, text=True, timeout=300,
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


def test_no_shell_test_is_a_silent_no_op():
    """Shell-Tests, sofern welche existieren, muessen echte Tests sein.

    **Warum diese Wache nicht mehr parametrisiert ist.** Die vorige Fassung
    spannte sich ueber `tests/*.sh` auf — und dort liegt seit dem Entfernen
    der beiden Waisen (`test_codex_cloud_setup.sh`,
    `test_validate_iphone_control_plane.sh`) keine Datei mehr. pytest meldete
    dreimal `got empty parameter set` bzw. `keine Shell-Tests vorhanden`:
    drei uebersprungene Tests, die aussahen wie Schutz und keiner waren.

    Ein Skip ist eine Spur, kein Ergebnis. Diese Fassung faellt nie aus: sie
    prueft die Eigenschaft fuer jede vorhandene Datei und stellt fest, dass
    es keine gibt, wenn es keine gibt — beides ist eine Aussage.

    Die drei Fehler, gegen die sie gerichtet bleibt, sind real gewesen:
    falsches Subjekt (das geprueefte Skript existierte nie in `main`),
    falscher Exit-Code (`FAIL:` gedruckt, `0` zurueckgegeben — jede
    Automatisierung wertete das als bestanden), und von pytest nie
    eingesammelt, weil es keine `.sh`-Dateien sammelt.
    """
    dateien = _shell_tests()
    if not dateien:
        # Eine Aussage, kein Ausweichen: es gibt keine, also ist nichts
        # verletzt. Faellt spaeter eine hinein, greifen die Pruefungen unten.
        assert True
        return

    import re as _re
    befunde = []
    workflows = "\n".join(
        q.read_text(encoding="utf-8")
        for q in (REPO / ".github" / "workflows").glob("*.yml"))
    for d in dateien:
        inhalt = d.read_text(encoding="utf-8")
        subjekte = {m for m in _re.findall(r"(?:scripts|tests)/[\w./-]+", inhalt)}
        for s in subjekte:
            if not (REPO / s).exists():
                befunde.append(f"{d.name}: Subjekt {s} existiert nicht")
        if "FAIL" in inhalt and "exit 1" not in inhalt:
            befunde.append(f"{d.name}: druckt FAIL, gibt aber nie exit 1")
        if d.name not in workflows:
            befunde.append(f"{d.name}: kein Workflow ruft ihn auf — laeuft nie")
    assert not befunde, befunde

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


def test_the_suite_contains_no_unconditional_skip():
    """**Ein Skip ist eine Spur, kein Ergebnis.**

    Vier Skips standen in dieser Suite, und jeder war ein Rest:

    * drei Metatest-Wachen spannten sich ueber `tests/*.sh` auf, wo seit
      dem Entfernen zweier Waisen keine Datei mehr liegt — `got empty
      parameter set`, dreimal.
    * ein Relay-Test fuehrte einen Fall in der Liste der unauffaelligen
      Texte und uebersprang ihn dann. Wer die Liste las, hielt ihn fuer
      abgedeckt.

    Beides sah aus wie Schutz und war keiner. Diese Wache verlangt, dass
    eine Entscheidung als Zusicherung dasteht, nicht als Ausweichen.

    Erlaubt bleibt `importorskip` fuer eine echte fehlende Abhaengigkeit
    (ohne PyYAML ist eine YAML-Pruefung nicht durchfuehrbar — das ist eine
    Aussage ueber die Umgebung, nicht ueber den Code) und ein Skip, der an
    eine *gemessene* Bedingung gebunden ist, etwa ein nicht laufender
    Dienst.
    """
    import re as _re
    befunde = []
    for datei in sorted((REPO / "tests").glob("test_*.py")):
        for nr, zeile in enumerate(datei.read_text(encoding="utf-8").splitlines(), 1):
            s = zeile.strip()
            if not s.startswith(("pytest.skip(", "@pytest.mark.skip")):
                continue
            # An eine Bedingung gebunden? Dann steht davor ein `if`.
            umfeld = datei.read_text(encoding="utf-8").splitlines()[max(0, nr - 4):nr]
            if any(z.strip().startswith(("if ", "elif ")) for z in umfeld):
                continue
            befunde.append(f"{datei.name}:{nr} {s[:70]}")
    assert not befunde, (
        "unbedingte Skips — eine Entscheidung gehoert als Zusicherung "
        f"formuliert: {befunde}")


def test_the_python_ci_job_builds_the_gateway_it_needs():
    """**Zwei Tests liefen in CI nie, und niemand sah es.**

    `test_ghm_core_cli_smoke.py` und `test_hm_gateway_watchdog.py` starten
    einen echten `target/debug/hm-gateway` als Unterprozess. Fehlte die
    Datei, uebersprangen sie sich still — und im Python-Job fehlte sie
    *immer*: der Job hat keinen Rust-Schritt. `cargo test --workspace` im
    Nachbarjob baut Testbinaries, nicht dieses Binary.

    Aufgefallen ist es nur, weil die Suite in einem frischen
    `--depth 1`-Klon gefahren wurde: dort erschienen 2 Skips, die lokal nie
    auftreten, weil im Arbeitsbaum ein Build herumliegt.

    Diese Wache haelt beides fest: der Job baut das Binary, und die Tests
    verlangen es, statt auszuweichen.
        **Und die zweite Fassung dieser Wache war ebenfalls zu eng.** Sie
    verlangte den Bau-Befehl im Workflow *und* im Testtext. Beides war die
    Formulierung von damals, nicht die Sache: seit `tests/conftest.py` die
    Fixture `gateway_binary` traegt, stellt die Suite die Voraussetzung
    selbst her — in jedem Workflow, auch in dem, den morgen jemand
    hinzufuegt. Der erste echte Kettenlauf hatte gezeigt, warum das
    noetig war: `zyklus.yml` faehrt ebenfalls pytest und wusste nichts vom
    Bau.

    Geprueft wird jetzt die Eigenschaft: es gibt eine Fixture, die baut,
    beide Tests benutzen sie, und keiner weicht mehr aus.
    """
    conftest = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "def gateway_binary" in conftest, "keine Fixture, die das Binary stellt"
    assert "cargo" in conftest and "build" in conftest, \
        "die Fixture baut nicht — dann bleibt die Voraussetzung ungedeckt"
    assert "pytest.skip" not in conftest, "die Fixture weicht aus statt zu bauen"

    for datei in ("tests/test_ghm_core_cli_smoke.py",
                  "tests/test_hm_gateway_watchdog.py"):
        text = (REPO / datei).read_text(encoding="utf-8")
        assert "hm-gateway debug binary not built" not in text, \
            f"{datei} weicht wieder aus, statt das Binary zu verlangen"
        assert "gateway_binary" in text, \
            f"{datei} benutzt die Fixture nicht"
