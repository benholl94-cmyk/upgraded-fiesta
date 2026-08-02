"""Das Inventar — und eine Grundwache ueber *jedes* Skript des Repos.

## Zwei Dinge in einer Datei, weil sie dieselbe Frage stellen

`scripts/hugin_inventar.py` beantwortet: *ist jeder Teil erfasst*. Diese
Datei beantwortet dieselbe Frage fuer die Teile, die sonst durchfielen —
und sie tut es **parametrisiert ueber die tatsaechliche Dateiliste**, nicht
ueber eine gepflegte Aufzaehlung. Kommt morgen ein Skript dazu, ist es
automatisch mitgeprueft; eine Liste haette man vergessen.

## Warum eine Grundwache und nicht 25 Alibi-Tests

Das Inventar meldete 25 Skripte ohne Test. Fuer jedes einen eigenen
Testfall zu erfinden waere Beschaeftigung: die meisten dieser Programme
verrotten nicht an ihrer Logik, sondern daran, dass sie nach einer
Umbenennung gar nicht mehr starten. Genau das faengt eine Grundwache —
Syntax, Importierbarkeit, `--help` — und zwar fuer alle auf einmal.

Sie behauptet ausdruecklich **nicht**, dass die Programme fachlich richtig
sind. Sie behauptet, dass sie startbar sind. Das ist wenig und es ist
wahr; ein Test, der mehr verspricht als er prueft, ist schlimmer als
keiner.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import hugin_inventar as hi  # noqa: E402

SKRIPTE = sorted((REPO / "scripts").glob("*.py")) + \
          sorted((REPO / "plugins").glob("*.py")) + \
          sorted((REPO / "agents").glob("*.py"))


# ---------------------------------------------------------------------------
# Die Grundwache — ueber alles, was da ist
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pfad", SKRIPTE, ids=lambda p: p.name)
def test_every_script_parses(pfad: pathlib.Path):
    """Ein Syntaxfehler in einem selten gelaufenen Skript faellt sonst erst
    auf, wenn jemand es im Ernstfall braucht."""
    ast.parse(pfad.read_text(encoding="utf-8"), filename=str(pfad))


@pytest.mark.parametrize("pfad", SKRIPTE, ids=lambda p: p.name)
def test_every_script_explains_itself(pfad: pathlib.Path):
    """Ein Programm ohne Moduldocstring ist ein Programm, dessen Zweck nur
    sein Autor kennt. In diesem Repo ist der Docstring ausserdem Korpus —
    er traegt die Begruendung, aus der die Erdung ihre Belege zieht."""
    baum = ast.parse(pfad.read_text(encoding="utf-8"))
    d = ast.get_docstring(baum)
    assert d and len(d) > 40, f"{pfad.name} erklaert sich nicht"


@pytest.mark.parametrize("pfad", SKRIPTE, ids=lambda p: p.name)
def test_no_shell_invocation_anywhere(pfad: pathlib.Path):
    """**Die Eigenschaft, die die ganze Kette traegt: es gibt keine Shell.**

    `hm-tool-exec` waehlt aus einer Allowlist, `brain.py` aus einer festen
    Befehlstabelle, `hm-plugins` schreibt JSON auf stdin eines
    Unterprozesses. Nirgends wird ein Kommando aus Eingaben *gebaut*.
    `shell=True` waere die eine Stelle, an der das kippt — und es kippt
    still, weil der Aufruf davor und danach gleich aussieht.
    """
    text = pfad.read_text(encoding="utf-8")
    assert "shell=True" not in text, f"{pfad.name} startet eine Shell"


def _hat_argparse(pfad: pathlib.Path) -> bool:
    return "argparse" in pfad.read_text(encoding="utf-8")


def _aufruf(pfad: pathlib.Path) -> list[str]:
    """Wie dieses Programm richtig gestartet wird.

    **Nicht jedes .py ist ein Skript.** `agents/cli.py` gehoert zu einem
    Paket und benutzt relative Importe; als Datei aufgerufen stirbt es mit
    `ImportError: attempted relative import with no known parent package`.
    Das ist kein Fehler des Programms, sondern des Aufrufs — die erste
    Fassung dieses Tests machte genau den und haette zu einer Umbauaktion
    an einer intakten Datei gefuehrt.
    """
    if (pfad.parent / "__init__.py").is_file():
        modul = f"{pfad.parent.name}.{pfad.stem}"
        return [sys.executable, "-m", modul]
    return [sys.executable, str(pfad)]


@pytest.mark.parametrize("pfad", [p for p in SKRIPTE if _hat_argparse(p)],
                         ids=lambda p: p.name)
def test_scripts_with_a_cli_answer_help(pfad: pathlib.Path):
    """`--help` ist der billigste echte Lauf: er fuehrt Importe,
    Modulinitialisierung und den Parserbau aus. Genau daran scheitern
    Skripte nach einer Umbenennung — und dort faellt es sonst erst im
    Ernstfall auf."""
    r = subprocess.run([*_aufruf(pfad), "--help"],
                       cwd=REPO, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"{pfad.name}: exit {r.returncode}\n{r.stderr[-400:]}"


# ---------------------------------------------------------------------------
# Das Inventar selbst — es misst, also muss es richtig messen
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def teile():
    return hi.inventar()


def test_the_inventory_covers_every_kind(teile):
    arten = {t.art for t in teile}
    assert arten >= {"krate", "skript", "plugin", "workflow", "skill",
                     "konfig", "doku"}


def test_no_part_is_ever_unknown(teile):
    """**Der Punkt des ganzen Programms.** Ein Teil, ueber den niemand etwas
    sagen kann, ist gefaehrlicher als ein kaputter: der kaputte faellt auf.
    Deshalb gibt es nur drei Zustaende und `unbekannt` ist keiner davon."""
    for t in teile:
        assert t.zustand in (hi.GESCHLOSSEN, hi.OFFEN, hi.EXTERN), t.pfad


def test_every_open_part_names_the_command_that_closes_it(teile):
    """Ein Befund ohne Befehl ist eine Beschwerde."""
    for t in teile:
        if t.zustand == hi.OFFEN:
            assert t.grund and t.befehl, t.pfad


def test_rust_crates_are_not_reported_as_untested(teile):
    """**Erster eigener Messfehler, hier festgehalten.** Die erste Fassung
    fragte, ob eine Datei unter `tests/` die Krate nennt. Rust legt
    Modultests in `#[cfg(test)]` neben den Code — `hm-vector` hat neun,
    `hm-plugins` fuenfzehn. Gemeldet wurden trotzdem 12 von 20 Kraten als
    ungeprueft, alle falsch. Ein Befund, der keiner ist, kostet die
    Glaubwuerdigkeit der ganzen Liste."""
    kraten = [t for t in teile if t.art == "krate"]
    ungeprueft = [t.pfad for t in kraten if not t.fakten["geprueft"]]
    assert not ungeprueft, f"Kraten mit Modultests als ungeprueft: {ungeprueft}"


def test_a_script_tested_under_its_module_name_counts_as_tested(teile):
    """**Zweiter eigener Messfehler.** Ein Test schreibt `import
    hugin_keyring`, nie `hugin_keyring.py` — und die Namenssuche brach beim
    ersten Treffer ab, statt zu vereinigen. `CLAUDE.md` nennt den vollen
    Pfad, also wurde unter dem Modulnamen gar nicht mehr gesucht."""
    treffer = [t for t in teile if t.pfad == "scripts/hugin_keyring.py"]
    assert treffer and treffer[0].fakten["geprueft"], \
        "hugin_keyring hat tests/test_hugin_keyring.py und gilt als ungeprueft"


def test_the_builder_stage_copy_does_not_count_as_shipped():
    """`COPY . .` steht im Builder-Stage und sagt ueber das ausgelieferte
    Image nichts. Wer beide Stages zusammenliest, bekommt fuer jeden Pfad
    'ja' — und die Pruefung meldet gruen, waehrend das Image die Datei nicht
    hat. Genau diese Luecke hat hier die Plugin-Dispatch und den Chat
    gekostet."""
    baum = hi.Baum()
    assert not hi._dockerfile_deckt(baum, "gibt/es/nicht/im/image.txt")
    assert hi._dockerfile_deckt(baum, "corpus/faelle.jsonl")


def test_the_index_is_generated_not_maintained(tmp_path, monkeypatch):
    """Von Hand gepflegte Uebersichten veralten still — die Krate-Tabelle in
    `CLAUDE.md` nannte reale Kraten monatelang 'intentional placeholders'."""
    text = hi.index_md(hi.inventar())
    assert "Nicht von Hand" in text
    assert "| Teil |" in text


def test_the_cli_exit_code_distinguishes_open_from_clean():
    r = subprocess.run([sys.executable, "scripts/hugin_inventar.py", "--json"],
                       cwd=REPO, capture_output=True, text=True, timeout=600)
    import json
    d = json.loads(r.stdout)
    assert (r.returncode == 1) == (d["offen"] > 0)


def test_the_generated_index_is_not_counted_as_a_reference():
    """**Dritte Selbstbezugs-Falle dieser Sitzung, und die subtilste.**

    `docs/INVENTAR.md` listet jeden Teil auf. Wer den eigenen Bericht
    mitliest, findet jeden Teil "erreichbar" und "beschrieben" und misst
    nur noch sich selbst. Gemessen: Workflows sprangen von 15/18 auf 18/18
    und Doku von 12/14 auf 14/14, ohne dass sich irgendetwas geaendert
    haette — allein durch das Schreiben des Berichts.

    Ein Pruefer, der seinen eigenen Bericht mitliest, prueft nichts.
    """
    baum = hi.Baum()
    assert hi.INDEX_DATEI not in baum.dateien


def test_the_index_file_exists_and_is_current():
    """Der Index ist erzeugt und eingecheckt — er soll ohne Werkzeug lesbar
    sein, auch vom Telefon aus."""
    p = REPO / hi.INDEX_DATEI
    assert p.is_file(), f"{hi.INDEX_DATEI} fehlt — --index laufen lassen"
    assert p.read_text(encoding="utf-8") == hi.index_md(hi.inventar()), \
        f"{hi.INDEX_DATEI} veraltet — python3 scripts/hugin_inventar.py --index"


def test_the_inventory_reads_only_tracked_files():
    """**In CI aufgefallen, und zu Recht.** Lokal lagen `status/`-Protokolle,
    `vendor/llama.cpp` und ein 6,6-GB-Modell im Baum, auf dem Runner nicht.
    Nennt eine ungetrackte Logdatei ein Skript, gilt es hier als erreichbar
    und dort nicht — der eingecheckte Index wich vom gerechneten ab.

    Ein Inventar des Repos muss lesen, was **im Repo** ist, nicht was
    zufaellig im Arbeitsverzeichnis liegt. Dieselbe Regel wie im
    Metatest-Sandkasten."""
    baum = hi.Baum()
    getrackt = set(hi._getrackt())
    fremde = [rel for rel in baum.dateien if rel not in getrackt]
    assert not fremde, f"ungetrackte Dateien im Inventar: {fremde[:5]}"


def test_untracked_runtime_state_is_not_a_part(teile):
    """`Baum` allein umzustellen reichte nicht: die Teilesammlung griff
    weiter direkt aufs Dateisystem und nahm `config/knowledge-loop-state.json`
    und `config/llm-active.json` mit — ungetrackter Laufzeitzustand, der
    lokal existiert und auf dem Runner nicht. Derselbe Fehler in der anderen
    Haelfte, gefunden erst durch den Vergleich gegen einen frischen Klon."""
    getrackt = set(hi._getrackt())
    fremde = [t.pfad for t in teile if t.pfad not in getrackt
              and not (REPO / t.pfad / "Cargo.toml").is_file()
              and not (REPO / t.pfad).is_dir()]
    assert not fremde, f"ungetrackte Teile im Inventar: {fremde}"


def test_a_new_unstaged_file_is_already_visible(tmp_path):
    """**In CI aufgefallen.** `git ls-files --cached` sieht eine neue Datei
    nicht, solange sie nicht gestaged ist — der Index konnte damit nie die
    Datei enthalten, die im selben Commit dazukommt. Gemessen an
    `.github/workflows/zyklus.yml`, das als 19. Workflow fehlte.

    `--others --exclude-standard` schliesst die Luecke, ohne die
    Reproduzierbarkeit aufzugeben: auf einem frischen Checkout ist diese
    Menge leer."""
    neu = REPO / ".github" / "workflows" / "__probe_inventar.yml"
    neu.write_text("name: probe\non: workflow_dispatch\njobs:\n  a:\n"
                   "    runs-on: ubuntu-latest\n    steps:\n"
                   "      - run: 'true'\n", encoding="utf-8")
    try:
        assert str(neu.relative_to(REPO)) in hi._getrackt()
    finally:
        neu.unlink()


# ---------------------------------------------------------------------------
# Vierter Messfehler: eine Naeherung wurde fuer die Sache gehalten
# ---------------------------------------------------------------------------

def test_a_parametrized_test_counts_as_coverage():
    """**Der Befund war falsch, nicht das Repo.**

    `tests/test_inventar_und_skripte.py` spannt sich ueber
    `(REPO / "scripts").glob("*.py")` auf und prueft **jedes** Skript auf
    Syntax, Moduldocstring, `--help` und `shell=True` — im Quelltext steht
    dabei kein einziger Dateiname. Die Namenssuche fand das nicht und
    meldete 13 Skripte und 3 Workflows als ungeprueft.

    Gemessen: allein fuer `hugin_growth`, `hugin_reflect` und `hugin_tool`
    sammelt pytest 12 Testfaelle. Der Befund war jedes Mal falsch — und ein
    falscher Befund kostet die Glaubwuerdigkeit der ganzen Liste.

    Gefragt wird jetzt pytest selbst (`--collect-only`, fuehrt nichts aus).
    """
    assert hi._in_testfaellen("scripts/hugin_growth.py")
    assert hi._in_testfaellen("scripts/hugin_reflect.py")
    assert hi._in_testfaellen(".github/workflows/codeql.yml")


def test_something_genuinely_uncollected_is_still_reported():
    """**Die Gegenprobe, die zaehlt.** Waere `_in_testfaellen` einfach
    grosszuegig, meldete das Inventar nie wieder etwas — und eine Liste,
    die immer leer ist, ist kein Schutz, sondern eine Beruhigung."""
    assert not hi._in_testfaellen("scripts/gibt-es-garantiert-nicht-xyz.py")


def test_the_collection_is_measured_not_assumed():
    """`--collect-only` fuehrt nichts aus. Waere die Menge leer, wuerde das
    Inventar wieder alles als ungeprueft melden — das faellt auf, statt
    still durchzugehen."""
    assert len(hi._gesammelt()) > 500, "pytest sammelt nichts — Messung kaputt"


def test_no_part_remains_open():
    """**Das Ziel, maschinell nachgerechnet.** Jeder Teil ist geschlossen
    oder ausdruecklich extern. Faellt dieser Test, ist etwas dazugekommen,
    das niemand nennt, testet oder beschreibt — und genau dann soll er
    fallen."""
    offen = [t.pfad for t in hi.inventar() if t.zustand == hi.OFFEN]
    assert not offen, f"offene Teile: {offen}"


def test_the_shell_guard_stays_blunt_on_purpose():
    """**Die Wache hat mich selbst erwischt, und sie hatte recht.**

    Ein Grep nach dem Literal kann Prosa nicht von Code unterscheiden — ich
    hatte den verbotenen Ausdruck in einem *Docstring* stehen, der die
    Wache beschreibt. Eine AST-basierte Fassung waere klueger und
    schwaecher: sie uebersaehe den Aufruf in einem `exec`, in einer
    erzeugten Datei oder in einem Shellskript daneben.

    Blunt ist hier die richtige Wahl. Wer darueber schreiben will,
    umschreibt es — das kostet einen Satz und haelt die Wache scharf.
    """
    quelle = (REPO / "tests" / "test_inventar_und_skripte.py").read_text(encoding="utf-8")
    assert 'assert "shell=' in quelle, "die Wache prueft nicht mehr auf den Literalstring"
