"""Der erzeugte Korpus — ist er dicht, deterministisch, und trifft er?

Der Korpus ist ein **eingechecktes Veroeffentlichungsartefakt**: er liegt im
git, wird mit dem Containerimage ausgeliefert und ist die Erdung, aus der der
Kern seine Belege zieht. Damit gelten fuer ihn dieselben zwei Regeln wie fuer
das Build-Manifest — kein Geheimnis, und nichts behaupten, was nicht gemessen
wurde — plus eine dritte, die nur er hat: **er darf nicht schlechter treffen
als die Quelle, die er ersetzt.**
"""
from __future__ import annotations

import json
import math
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import build_manifest as bm  # noqa: E402
import hugin_corpus as hc  # noqa: E402

KORPUS = REPO / "corpus"


@pytest.fixture(scope="module")
def gebaut():
    """Einmal bauen, im Speicher — der Arbeitsbaum wird nicht angefasst."""
    return hc.bauen(hc.konfig())


@pytest.fixture(scope="module")
def geladen():
    if not (KORPUS / "index.json").is_file():
        pytest.skip("corpus/ nicht gebaut — `python3 scripts/hugin_corpus.py bauen`")
    return hc.laden()


# ---------------------------------------------------------------------------
# Deterministisch — sonst ist die Aktualitaetspruefung wertlos
# ---------------------------------------------------------------------------

def test_building_twice_yields_identical_bytes():
    """Ohne das kann `pruefen` nicht sagen, ob der eingecheckte Korpus
    veraltet ist: jeder Bau saehe anders aus. Deshalb steht auch kein
    Zeitstempel in den Inhaltsdateien — er lebt im Manifest."""
    a, _ = hc.bauen(hc.konfig())
    b, _ = hc.bauen(hc.konfig())
    assert a == b


def test_no_timestamp_leaks_into_the_content_files(gebaut):
    dateien, manifest = gebaut
    assert "erzeugt" in manifest
    for name, inhalt in dateien.items():
        assert manifest["erzeugt"] not in inhalt, f"Zeitstempel in {name}"


# ---------------------------------------------------------------------------
# Dichte — der eigentliche Grund fuer das Programm
# ---------------------------------------------------------------------------

#: Was `agents/kernel.py::extract_cases` am 2026-08-01 lieferte: 178 Faelle,
#: 26.544 Zeichen. Der erzeugte Korpus muss deutlich darueber liegen, sonst
#: hat das Programm keinen Zweck.
VORHER_ZEICHEN = 26_544


def test_the_corpus_is_denser_than_the_source_it_replaces(gebaut):
    _, m = gebaut
    assert m["zeichen"] > VORHER_ZEICHEN * 5, \
        f"nur {m['zeichen']} Zeichen — die Live-Extraktion lieferte {VORHER_ZEICHEN}"


def test_reasoning_prose_is_actually_included(gebaut):
    """Docstrings und Markdown-Abschnitte waren die 12-fache Menge, die
    ungenutzt danebenlag — nicht vergessen, sondern in Formaten, die eine
    Fallsuche nicht liest."""
    _, m = gebaut
    assert m["arten"].get("begruendung", 0) > 50
    assert m["arten"].get("doku", 0) > 20


def test_every_case_carries_its_source():
    """Ein Beleg ohne Fundstelle ist eine Behauptung."""
    faelle, _ = hc.alle_faelle(hc.konfig())
    for f in faelle:
        assert f.quelle, f.fid
        assert f.text.strip()


def test_case_ids_are_content_addressed_not_sequential():
    """Eine laufende Nummer waere nicht stabil: eine eingeschobene Datei
    verschoebe alle folgenden IDs, und der Diff zeigte Bewegung, wo nichts
    passiert ist."""
    a = hc._kuerzel("derselbe Text", "quelle.py")
    b = hc._kuerzel("derselbe Text", "quelle.py")
    c = hc._kuerzel("derselbe Text", "andere.py")
    assert a == b and a != c


# ---------------------------------------------------------------------------
# Die Suche — beide Fehlrichtungen sind hier schon passiert
# ---------------------------------------------------------------------------

def test_german_inflection_does_not_hide_evidence(geladen):
    """Die Frage sagt *atomarer*, der Eintrag *atomar*. Der exakte
    Mengenschnitt in `agents/kernel.py` ergab darauf ueber alle 133 Faelle
    der Historie 0,000 — der Kern antwortete auf jede Frage 'nicht belegt'."""
    idx, faelle = geladen
    treffer = hc.suchen("atomarer Schreibvorgang Datenverlust", idx, faelle, 3)
    assert treffer, "kein Treffer trotz vorhandener Belege"
    assert treffer[0][0] > 0.5


def test_a_question_full_of_unknown_words_collapses(geladen):
    """Die Gegenprobe. Ein unbekanntes Wort ist nicht wertlos, sondern
    maximal aussagekraeftig: es kommt im ganzen Korpus nicht vor und laesst
    die Naehe zusammenbrechen.

    **Dieser Test hat sich einmal selbst zerstoert, und das ist die
    Lehre.** Die erste Fassung fragte nach *"Rezept fuer Zwiebelkuchen mit
    Speck"* — genau dem Gegenbeispiel, das ich zur Erklaerung in den
    Docstring von `_gewicht` geschrieben hatte. Der Korpus liest
    Docstrings. Also fand die sachfremde Frage einen echten Beleg: meinen
    eigenen Text darueber, dass sie keinen finden darf. Naehe 1,000.

    Ein Korpus, der die eigene Quelle mitliest, macht jedes woertlich
    dokumentierte Gegenbeispiel wertlos. Deshalb wird hier **zuerst
    geprueft**, dass die Woerter im Index wirklich fehlen — sonst misst der
    Test nichts und meldet trotzdem gruen.
    """
    idx, faelle = geladen
    frage = "Kolibri Marzipan Wolkenkratzer Rasenmaeher"
    fehlend = [hc.stamm(w) for w in hc._WORT.findall(frage)]
    vorhanden = [s for s in fehlend if s in idx]
    assert not vorhanden, (
        f"Kontrollwoerter stehen im Korpus: {vorhanden} — der Test misst "
        "nichts mehr. Andere Woerter waehlen, nicht die Schwelle senken.")
    treffer = hc.suchen(frage, idx, faelle, 3)
    assert not treffer, f"sachfremde Frage bekam {treffer[0][0]:.3f}"


def test_the_second_number_exposes_a_low_information_question(geladen):
    """**Der Test, der zaehlt.** Eine Frage aus lauter haeufigen Woertern
    kann die Naehe 1,000 erreichen und traegt trotzdem fast nichts. Genau
    deshalb gibt `suchen` zwei Zahlen zurueck: eine absolute Schwelle
    zwischen beiden Faellen liess sich nicht belegen (Median informativer
    Staemme 6,08, 25.-Perzentil 4,83 — beide wuerden 'Plugin Dispatch' mit
    seinem staerksten Wort 3,55 mitverwerfen), also wird die zweite Zahl
    gezeigt statt eine zurechtgeschnittene Konstante eingebaut."""
    idx, faelle = geladen
    arm = hc.suchen("und mit fuer das", idx, faelle, 1)
    reich = hc.suchen("atomarer Schreibvorgang Datenverlust", idx, faelle, 1)
    assert reich, "Fachfrage ohne Treffer"
    if arm:
        assert arm[0][1] < reich[0][1], \
            "die informationsarme Frage traegt nicht weniger als die fachliche"


def test_a_query_of_only_stopwords_carries_little_information(geladen):
    """Haeufige Staemme bekommen Gewicht 0 — gerechnet, nicht gepflegt.
    Eine Stoppwortliste muesste gepflegt werden, waere sprachgebunden und
    haette dieselbe Luecke beim naechsten haeufigen Wort."""
    idx, faelle = geladen
    gesamt = len(faelle)
    haeufigster = max(idx, key=lambda s: len(idx[s]))
    assert hc._gewicht(haeufigster, idx, gesamt) == 0.0


def test_an_unknown_word_weighs_the_maximum(geladen):
    idx, faelle = geladen
    g = len(faelle)
    assert hc._gewicht("qzxvw", idx, g) == pytest.approx(math.log(g))


# ---------------------------------------------------------------------------
# Kein Geheimnis — der Korpus wird eingecheckt und ausgeliefert
# ---------------------------------------------------------------------------

def test_the_built_corpus_carries_nothing_secret(gebaut):
    dateien, manifest = gebaut
    ganz = "\n".join(dateien.values()) + json.dumps(manifest, ensure_ascii=False)
    assert bm.leckpruefung(ganz) == []


def test_writing_is_refused_when_something_secret_would_be_published(monkeypatch, tmp_path):
    """Nicht 'wird gewarnt', sondern 'wird nicht geschrieben'. Dieselbe Regel
    wie beim Build-Manifest und bei der Release-Notiz."""
    monkeypatch.setattr(hc, "KORPUS", tmp_path / "corpus")
    code = hc.schreiben({"faelle.jsonl": '{"t":"ghp_' + "x" * 36 + '"}\n'}, {})
    assert code == 2
    assert not (tmp_path / "corpus").exists()


# ---------------------------------------------------------------------------
# Robust — der Container hat kein .git
# ---------------------------------------------------------------------------

def test_missing_git_is_named_not_swallowed(monkeypatch):
    """**Der teuerste der drei Befunde.** Das Laufzeitimage kopiert `agents/`,
    `scripts/`, `config/` — aber kein `.git`. Dort fielen 119 von 178
    Faellen lautlos weg, und die Antwort sah weiterhin aus wie eine
    Antwort. Jetzt steht es im Manifest."""
    monkeypatch.setattr(hc, "_run", lambda *a: "")
    k = dict(hc.konfig())
    k["quellen"] = dict(k["quellen"], markdown=[], docstrings=[], rust_moduldoc=[])
    _, m = hc.bauen(k)
    assert m["herkunft"]["commits"] == 0
    assert "hinweis_commits" in m, "fehlendes .git wird verschwiegen"


def test_a_broken_config_is_refused_not_silently_defaulted(monkeypatch, tmp_path):
    """Fail-closed: eine kaputte Konfiguration ist nicht dasselbe wie keine.
    Stillschweigend die Vorgabe zu nehmen hiesse, die Aenderung des
    Betreibers zu verwerfen."""
    kaputt = tmp_path / "corpus.json"
    kaputt.write_text("{ das ist kein json", encoding="utf-8")
    monkeypatch.setattr(hc, "KONFIG", kaputt)
    with pytest.raises(SystemExit):
        hc.konfig()


def test_a_missing_config_is_created_not_complained_about(monkeypatch, tmp_path):
    """Eine Konfiguration, die man erst schreiben muss, bevor etwas laeuft,
    ist eine Huerde und keine Einstellung."""
    ziel = tmp_path / "neu" / "corpus.json"
    monkeypatch.setattr(hc, "KONFIG", ziel)
    d = hc.konfig()
    assert ziel.is_file() and d["quellen"]["ledger"] is True


# ---------------------------------------------------------------------------
# Die Formate
# ---------------------------------------------------------------------------

def test_every_declared_format_is_produced(gebaut):
    dateien, _ = gebaut
    for name in ("faelle.jsonl", "chat.jsonl", "instruct.jsonl",
                 "index.json", "beispiele.md"):
        assert name in dateien and dateien[name].strip()


def test_the_jsonl_files_are_one_object_per_line(gebaut):
    dateien, _ = gebaut
    for name in ("faelle.jsonl", "chat.jsonl", "instruct.jsonl"):
        for zeile in dateien[name].splitlines():
            json.loads(zeile)


def test_chat_format_has_the_shape_finetuners_expect(gebaut):
    dateien, _ = gebaut
    erste = json.loads(dateien["chat.jsonl"].splitlines()[0])
    assert [m["role"] for m in erste["messages"]] == ["user", "assistant"]
    assert erste["messages"][1]["content"].strip()


def test_instruct_format_carries_instruction_and_output(gebaut):
    dateien, _ = gebaut
    erste = json.loads(dateien["instruct.jsonl"].splitlines()[0])
    assert erste["instruction"].strip() and erste["output"].strip()


def test_the_cli_runs_end_to_end():
    r = subprocess.run([sys.executable, "scripts/hugin_corpus.py", "pruefen"],
                       cwd=REPO, capture_output=True, text=True, timeout=600)
    assert "determin: ja" in r.stdout, r.stdout[-500:] + r.stderr[-500:]


# ---------------------------------------------------------------------------
# Der Korpus muss den Kern auch wirklich erreichen
# ---------------------------------------------------------------------------

def test_the_kernel_reads_the_prebuilt_corpus():
    """**Ohne diesen Test waere der Korpus Zierde.** Live gemessen: das
    lokale Modell antwortete auf eine dokumentierte Frage 'nicht belegt',
    weil die Erdung weiter die alte Extraktion las. Eine Pipeline, die das
    Modell nicht erreicht, ist keine."""
    sys.path.insert(0, str(REPO))
    from agents.kernel import extract_cases
    faelle = extract_cases()
    assert len(faelle) > 500, f"nur {len(faelle)} Faelle — Korpus nicht gelesen"


def test_the_kernel_still_works_without_the_corpus(monkeypatch):
    """Ein fehlender Korpus soll langsamer und aermer machen, nicht stumm.
    Die Live-Extraktion bleibt der Rueckfall."""
    sys.path.insert(0, str(REPO))
    from agents import kernel
    monkeypatch.setattr(kernel, "KORPUS", REPO / "corpus" / "gibt-es-nicht.jsonl")
    assert kernel.extract_cases() != []


def test_evidence_is_found_for_a_documented_question():
    """Die Gegenprobe zur Live-Messung: dieselbe Frage, die 'nicht belegt'
    ergab, muss Belege finden."""
    sys.path.insert(0, str(REPO))
    from agents.kernel import Situation, infer
    r = infer(Situation(text="Warum schreibt LocalFsStorage::put nicht direkt mit fs::write?"))
    assert r.evidence, "keine Belege fuer eine dokumentierte Frage"


def test_binaries_are_replaced_not_overwritten_in_place():
    """`shutil.copy2` ueber eine laufende Binaerdatei scheitert mit
    `Text file busy` — live gesehen: `setup` brach ab, obwohl Modell und
    Dienst in Ordnung waren. Dieselbe Regel wie bei `LocalFsStorage::put`."""
    quelle = (REPO / "scripts" / "hugin_local_model.py").read_text(encoding="utf-8")
    block = quelle.partition("BIN_DIR.mkdir")[2].partition("\ndef ")[0]
    assert "os.replace" in block
    assert "shutil.copy2(datei, ziel)" not in block


def test_control_questions_never_appear_verbatim_in_the_corpus(geladen):
    """**Zweimal in einer Sitzung passiert, deshalb eine Wache.**

    Der Korpus liest Docstrings und Markdown. Wer ein Gegenbeispiel
    woertlich in eine solche Datei schreibt — sei es zur Erklaerung, sei es
    im Test selbst —, macht daraus einen echten Beleg und zerstoert damit
    genau die Kontrolle, die er dokumentieren wollte.

    Gemessen: die sachfremde Kontrollfrage traf ihren eigenen
    Erklaerungstext mit Naehe 1,000; die Kontrollfrage aus
    `test_kernel.py` traf mit 0,350 den Docstring, der ihren Fehlalarm
    beschrieb, und liess `test_real_corpus_refuses_an_unrelated_question`
    weiter fallen.

    Die Regel lautet deshalb: Kontrollfragen werden umschrieben, nicht
    zitiert. Diese Wache rechnet sie nach.
    """
    idx, _ = geladen
    # Die Fachwoerter, auf denen die Kontrollfragen dieses Repos beruhen.
    # Steht eines im Index, ist die zugehoerige Kontrolle wirkungslos.
    # Diese Liste muss den TATSAECHLICHEN Kontrollfragen folgen. Sie fuehrte
    # eine Zeit lang `bildverarbeitung` mit — ein Wort, das seit der
    # Umstellung von `test_real_corpus_refuses_an_unrelated_question` keine
    # Kontrolle mehr traegt und nur noch in dem Docstring vorkommt, der
    # erklaert, warum es untauglich war. Ein Eintrag fuer eine
    # abgeschaffte Kontrolle ist kein Schutz, sondern ein Fehlalarm.
    kontrollwoerter = ["kolibri", "marzipan", "wolkenkratzer", "rasenmaeher"]
    gefunden = [w for w in kontrollwoerter if hc.stamm(w) in idx]
    assert not gefunden, (
        f"Kontrollwoerter im Korpus: {gefunden}. Der zugehoerige Test misst "
        "nichts mehr. Den Text umschreiben — nicht die Schwelle senken.")


def test_the_runtime_image_carries_the_corpus():
    """**Die Luecke, die dieses Repo dreimal gekostet hat.** Das
    Laufzeitimage kopiert einzelne Verzeichnisse, nicht den Baum. Fehlte
    `corpus/`, waere die Erdung im Container halbiert — gemessen 59 statt
    178 Faelle, lautlos, waehrend die Antwort weiter aussah wie eine
    Antwort. Vorher traf es die Plugin-Dispatch, dann den Chat: beide gruen
    im Checkout, tot im Container."""
    text = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY corpus/" in text, "Laufzeitimage ohne Korpus"
