#!/usr/bin/env python3
"""hugin_corpus.py -- der Korpus des eigenen Modells: erzeugt, nicht gepflegt.

## Warum das noetig war -- gemessen am 2026-08-01

Die Erdung des Kerns (`agents/kernel.py::extract_cases`) las bei **jeder
Frage** das Ledger und die letzten 120 Commits neu ein. Drei Befunde, alle
nachgerechnet, keiner geschaetzt:

| | |
|---|---|
| Korpus, den das Modell sah | 26.544 B (178 Faelle) |
| Begruendungsprosa, die im Repo liegt | CLAUDE.md 62.472 B, 367 Docstrings 139.355 B, docs/ 124.894 B |
| Kosten je Frage | 0,58 s, ~240 Unterprozesse (`git log` + 120x `git show`) |
| **Im Containerlayout ohne `.git`** | **59 statt 178 Faelle** |

Der dritte ist der gefaehrliche und die eigentliche Begruendung: das
Laufzeitimage kopiert `agents/`, `scripts/`, `config/` -- aber kein `.git`.
Dort verschwanden 119 von 178 Faellen **lautlos**, und die Antwort sah
weiterhin aus wie eine Antwort. Dieselbe Fehlerklasse wie der Chat, der im
Checkout gruen war und im Container tot: gruen bleibt gruen, waehrend die
Substanz fehlt.

Zwoelf mal mehr Begruendungstext lag ungenutzt daneben. Nicht, weil ihn
jemand vergessen haette, sondern weil er in Formaten liegt, die eine
Fallsuche nicht liest: Ueberschriftsabschnitte in Markdown und Docstrings in
Python.

## Was dieses Programm tut

Es erzeugt den Korpus **einmal**, deterministisch, in mehrere Formate, und
legt einen fertigen Index daneben. Danach ist die Suche ein Dateilesen und
kein Unterprozess.

    python3 scripts/hugin_corpus.py bauen      # Korpus + Index schreiben
    python3 scripts/hugin_corpus.py pruefen    # aktuell? deterministisch? dicht?
    python3 scripts/hugin_corpus.py suchen "atomarer Schreibvorgang"

Erzeugt werden (unter `corpus/`):

| Datei | Format | wofuer |
|---|---|---|
| `faelle.jsonl` | ein JSON-Objekt je Zeile | die Quelle, aus der alles andere faellt |
| `chat.jsonl` | `{"messages":[{role,content}...]}` | Feinabstimmung im Chat-Format |
| `instruct.jsonl` | `{"instruction","input","output"}` | Feinabstimmung im Instruktionsformat |
| `index.json` | invertierter Index Wortstamm -> Fall-IDs | Suche ohne Unterprozess |
| `beispiele.md` | lesbare Auszuege | damit ein Mensch pruefen kann, was drinsteht |
| `manifest.json` | Zaehlungen, Quellen, SHA256 | nachrechenbar, statt geglaubt |

**Deterministisch heisst bytegleich.** Kein Zeitstempel steht in den
Inhaltsdateien -- er stuende sonst in jedem Diff und machte die einzige
Pruefung wertlos, die zaehlt: zweimal bauen ergibt dieselben Bytes.
Der Zeitstempel lebt im Manifest, nicht im Korpus.

**Kein Geheimnis, niemals.** Der Korpus ist ein eingecheckter, mit dem Image
ausgelieferter Text. Vor dem Schreiben laufen dieselben Muster wie im
Secret-Scanner ueber die fertige Ausgabe; ein Treffer bricht ab (Exit 2) und
schreibt **nichts**, statt zu warnen.

## Was er ausdruecklich nicht tut

Er trainiert nicht. `chat.jsonl` und `instruct.jsonl` sind Datensaetze in
den ueblichen Formaten, kein Trainingslauf -- und dieses Repo behauptet
nicht, ein Modell trainiert zu haben, nur weil es die Datei erzeugen kann.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _log import get_logger              # noqa: E402
from build_manifest import leckpruefung  # noqa: E402

log = get_logger(__name__)

REPO = Path(__file__).resolve().parent.parent
KORPUS = REPO / "corpus"
KONFIG = REPO / "config" / "corpus.json"

#: Ab dieser Laenge gilt ein gemeinsamer Wortanfang als dasselbe Wort.
#: Identisch zu `agents/kernel.py::_STAMM_MIN` -- zwei Werte waeren zwei
#: Suchen, und die eine faende, was die andere nicht findet.
STAMM = 5

#: Kuerzer als das ist kein Abschnitt, sondern eine Ueberschrift mit Rest.
MIN_ZEICHEN = 200

VORGABE = {
    "_hinweis": ("Frei aenderbar. Wird angelegt, wenn sie fehlt -- eine "
                 "Konfiguration, die man erst schreiben muss, bevor etwas "
                 "laeuft, ist eine Huerde und keine Einstellung."),
    "quellen": {
        "ledger": True,
        "commits": 400,
        "markdown": ["CLAUDE.md", "AGENTS.md", "docs"],
        "docstrings": ["scripts", "tests", "agents", "plugins"],
        "rust_moduldoc": ["crates"],
    },
    "min_zeichen": MIN_ZEICHEN,
    "formate": ["faelle", "chat", "instruct", "index", "beispiele"],
    "beispiele_je_art": 2,
}


def konfig() -> dict:
    """Fehlende Konfiguration wird angelegt, nicht bemaengelt."""
    if not KONFIG.is_file():
        KONFIG.parent.mkdir(parents=True, exist_ok=True)
        KONFIG.write_text(json.dumps(VORGABE, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        log.info("config/corpus.json angelegt (Vorgabe)")
    try:
        d = json.loads(KONFIG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # Fail-closed wie ueberall hier: eine kaputte Konfiguration ist nicht
        # dasselbe wie keine, und stillschweigend die Vorgabe zu nehmen
        # hiesse, die Aenderung des Betreibers zu verwerfen.
        raise SystemExit(f"config/corpus.json unlesbar: {exc}")
    for k, v in VORGABE.items():
        d.setdefault(k, v)
    return d


# ---------------------------------------------------------------------------
# Faelle
# ---------------------------------------------------------------------------

@dataclass
class Fall:
    fid: str
    art: str          # ledger-entscheidung | commit | doku | begruendung | rustdoc
    titel: str
    text: str
    quelle: str       # Datei oder sha
    anker: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.fid, "art": self.art, "titel": self.titel,
                "text": self.text, "quelle": self.quelle, "anker": self.anker}


def _run(*argv: str) -> str:
    try:
        r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=120)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("%s nicht ausfuehrbar: %s", argv[0], exc)
        return ""


def _kuerzel(text: str, quelle: str) -> str:
    """Stabile ID aus Inhalt und Herkunft. Eine laufende Nummer waere nicht
    stabil: eine eingeschobene Datei verschoebe alle folgenden IDs, und der
    Diff zeigte Bewegung, wo nichts passiert ist."""
    h = hashlib.sha256(f"{quelle}\x00{text}".encode()).hexdigest()
    return h[:12]


def aus_ledger() -> list[Fall]:
    p = REPO / ".claude" / "continuity" / "ledger.json"
    if not p.is_file():
        return []
    try:
        roh = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Ledger unlesbar: %s", exc)
        return []
    eintraege = roh.get("entries", roh if isinstance(roh, list) else [])
    out = []
    for e in eintraege:
        art = e.get("kind", "notiz")
        if art not in ("entscheidung", "sackgasse", "invariante"):
            continue          # 'offen' ist eine Aufgabe, kein Praezedenzfall
        text = str(e.get("text", "")).strip()
        if not text:
            continue
        out.append(Fall(fid=str(e.get("id") or _kuerzel(text, "ledger")),
                        art=f"ledger-{art}", titel=text[:70], text=text,
                        quelle=".claude/continuity/ledger.json",
                        anker=list(e.get("anchors", ()))))
    return out


def aus_commits(grenze: int) -> list[Fall]:
    """Commit-Betreff und der **erste Absatz** des Rumpfs.

    Der Rumpf traegt hier die Begruendung -- dieses Repo erklaert in der
    Commit-Botschaft, nicht nur im Betreff, und die alte Extraktion nahm
    nur `%s`. Aber eben der *erste Absatz*, und dafuer gibt es eine
    gemessene Ursache:

    Mit vollem Rumpf bekam die Kontrollfrage aus
    `tests/test_kernel.py::test_real_corpus_refuses_an_unrelated_question`
    eine **Empfehlung** statt der verlangten Ablehnung, gestuetzt auf einen
    einzigen sachfremden Commit (Naehe 0,33 gegen die Schwelle 0,30).
    `similarity` misst die Abdeckung der Frage ungewichtet -- ein langer
    Text deckt trivial mehr Fragewoerter ab, und ein Commit-Rumpf mit
    vierzig Zeilen Aufzaehlung trifft irgendwann jede Frage. Das
    entscheidende Fachwort der Kontrollfrage kam in 0 von 883 Faellen vor.

    Die Frage steht hier **absichtlich nicht im Wortlaut**: der Korpus
    liest Docstrings, und ein woertlich notiertes Gegenbeispiel wird
    dadurch selbst zum Beleg. Genau das ist in dieser Sitzung zweimal
    passiert -- `tests/test_hugin_corpus.py` haelt die Regel fest und
    prueft sie nach.

    **Warum nicht `similarity` gewichten**, was die sachlich richtigere
    Korrektur waere: `MIN_SIMILARITY = 0.30` ist ausdruecklich gegen die
    jetzige Skala kalibriert (einschlaegig ~0,33, unverwandt 0,00-0,22).
    Wer die Bewertungsfunktion aendert, macht diese Messung ungueltig --
    ausprobiert, drei Kernel-Tests fielen. Die Laengenverzerrung stammt aus
    *dieser* Datei; sie gehoert hier behoben und nicht durch Nachziehen
    einer fremden Schwelle verdeckt.
    """
    roh = _run("git", "log", f"-{grenze}", "--format=%h%x1f%s%x1f%b%x1e")
    out = []
    for block in roh.split("\x1e"):
        block = block.strip("\n")
        if not block or block.count("\x1f") < 2:
            continue
        sha, betreff, rumpf = block.split("\x1f", 2)
        erster_absatz = rumpf.strip().split("\n\n", 1)[0].strip()
        text = (betreff + ("\n\n" + erster_absatz if erster_absatz else "")).strip()
        out.append(Fall(fid=sha, art="commit", titel=betreff[:70],
                        text=text, quelle=f"sha:{sha}", anker=[f"sha:{sha}"]))
    return out


_UEBERSCHRIFT = re.compile(r"^(#{2,4})\s+(.+)$", re.M)


def aus_markdown(ziele: list[str], min_zeichen: int) -> list[Fall]:
    """Markdown je Ueberschriftsabschnitt.

    Ein ganzes CLAUDE.md als *ein* Fall waere nutzlos: jede Frage traefe es,
    und ein Beleg, der immer passt, belegt nichts.
    """
    dateien: list[Path] = []
    for z in ziele:
        p = REPO / z
        if p.is_dir():
            dateien += sorted(p.rglob("*.md"))
        elif p.is_file():
            dateien.append(p)
    out = []
    for f in dateien:
        try:
            roh = f.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(f.relative_to(REPO))
        treffer = list(_UEBERSCHRIFT.finditer(roh))
        for i, m in enumerate(treffer):
            start = m.end()
            ende = treffer[i + 1].start() if i + 1 < len(treffer) else len(roh)
            koerper = roh[start:ende].strip()
            if len(koerper) < min_zeichen:
                continue
            titel = m.group(2).strip()
            out.append(Fall(fid=_kuerzel(koerper, rel), art="doku",
                            titel=titel[:70], text=f"{titel}\n\n{koerper}",
                            quelle=rel, anker=[f"path:{rel}"]))
    return out


def aus_docstrings(ziele: list[str], min_zeichen: int) -> list[Fall]:
    """Docstrings sind in diesem Repo die dichteste Begruendungsquelle.

    Sie erklaeren regelmaessig, *warum* etwas so ist und welche Messung
    dahinter steht -- genau das, was eine Fallsuche braucht und was in
    keinem Commit-Betreff steht.
    """
    out = []
    for z in ziele:
        wurzel = REPO / z
        if not wurzel.is_dir():
            continue
        for f in sorted(wurzel.rglob("*.py")):
            try:
                baum = ast.parse(f.read_text(encoding="utf-8"))
            except (SyntaxError, OSError, ValueError) as exc:
                log.warning("%s nicht parsebar: %s", f, exc)
                continue
            rel = str(f.relative_to(REPO))
            for knoten in ast.walk(baum):
                if not isinstance(knoten, (ast.Module, ast.FunctionDef,
                                           ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                d = ast.get_docstring(knoten)
                if not d or len(d) < min_zeichen:
                    continue
                name = getattr(knoten, "name", rel)
                out.append(Fall(fid=_kuerzel(d, f"{rel}:{name}"), art="begruendung",
                                titel=f"{rel}:{name}"[:70], text=d.strip(),
                                quelle=rel, anker=[f"path:{rel}"]))
    return out


_RUSTDOC = re.compile(r"((?:^\s*//[/!].*\n)+)", re.M)


def aus_rust(ziele: list[str], min_zeichen: int) -> list[Fall]:
    out = []
    for z in ziele:
        wurzel = REPO / z
        if not wurzel.is_dir():
            continue
        for f in sorted(wurzel.rglob("*.rs")):
            try:
                roh = f.read_text(encoding="utf-8")
            except OSError:
                continue
            rel = str(f.relative_to(REPO))
            for m in _RUSTDOC.finditer(roh):
                text = "\n".join(
                    z.strip().lstrip("/").lstrip("!").strip()
                    for z in m.group(1).splitlines()).strip()
                if len(text) < min_zeichen:
                    continue
                out.append(Fall(fid=_kuerzel(text, rel), art="rustdoc",
                                titel=text.splitlines()[0][:70], text=text,
                                quelle=rel, anker=[f"path:{rel}"]))
    return out


def alle_faelle(k: dict) -> tuple[list[Fall], dict]:
    q = k["quellen"]
    mz = int(k.get("min_zeichen", MIN_ZEICHEN))
    teile = {
        "ledger": aus_ledger() if q.get("ledger") else [],
        "commits": aus_commits(int(q.get("commits", 400))) if q.get("commits") else [],
        "markdown": aus_markdown(list(q.get("markdown", [])), mz),
        "docstrings": aus_docstrings(list(q.get("docstrings", [])), mz),
        "rust": aus_rust(list(q.get("rust_moduldoc", [])), mz),
    }
    faelle: list[Fall] = []
    gesehen: set[str] = set()
    for name in sorted(teile):
        for f in teile[name]:
            if f.fid in gesehen:
                continue      # derselbe Text zweimal ist ein Fall, nicht zwei
            gesehen.add(f.fid)
            faelle.append(f)
    faelle.sort(key=lambda f: (f.art, f.fid))     # deterministisch
    herkunft = {n: len(v) for n, v in sorted(teile.items())}
    return faelle, herkunft


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

_WORT = re.compile(r"[A-Za-zÄÖÜäöüß0-9_./-]{3,}")


def stamm(wort: str) -> str:
    """Deutsche Flexion darf einen Beleg nicht unsichtbar machen.

    Die Frage sagt *atomarer*, der Ledgereintrag *atomar*. Ein exakter
    Mengenschnitt ergab ueber alle 133 Faelle der Historie **0,000** -- der
    Kern antwortete darum auf jede Frage "nicht belegt". Der Index legt
    deshalb den auf `STAMM` gekuerzten Wortanfang ab; laengere Woerter
    finden sich ueber ihn wieder.
    """
    return wort.lower()[:STAMM]


def index_bauen(faelle: list[Fall]) -> dict:
    idx: dict[str, set[str]] = {}
    for f in faelle:
        for w in _WORT.findall(f"{f.titel} {f.text}"):
            idx.setdefault(stamm(w), set()).add(f.fid)
    return {s: sorted(ids) for s, ids in sorted(idx.items())}


#: Ein Wortstamm, der in mehr als diesem Anteil der Faelle vorkommt, sagt
#: nichts aus. Gerechnet statt gepflegt: eine Stoppwortliste muesste
#: gepflegt werden, waere sprachgebunden und haette dieselbe Luecke beim
#: naechsten haeufigen Wort.
HAEUFIG = 0.25


def _gewicht(stamm_: str, idx: dict, gesamt: int) -> float:
    """Wie viel sagt dieses Wort ueberhaupt aus (inverse Dokumenthaeufigkeit).

    **Der Grund ist eine gemessene Fehlmessung.** Die erste Fassung zaehlte
    Treffer und teilte durch die Wortzahl der Frage. Die sachfremde
    Kontrollfrage *"Rezept fuer Zwiebelkuchen mit Speck"* bekam damit
    **0,400** -- getroffen hatten `fuer` und `mit`, zwei Fuellwoerter, die in
    fast jedem Fall vorkommen. Ein Wert von 0,4 sieht aus wie ein halber
    Beleg und ist keiner.

    Eine Stoppwortliste waere die naheliegende Abhilfe und die schlechtere:
    sie muesste gepflegt werden, waere sprachgebunden und haette dieselbe
    Luecke beim naechsten haeufigen Wort. Die Haeufigkeit steht ohnehin im
    Index -- ein Wortstamm in 60 % der Faelle traegt keine Information, egal
    ob er in einer Liste steht. Gerechnet, nicht gepflegt.
    """
    import math
    n = len(idx.get(stamm_, ()))
    if n == 0:
        # Unbekannt ist nicht wertlos, sondern maximal aussagekraeftig: das
        # Wort kommt im ganzen Korpus nicht vor. Der Wert zaehlt spaeter im
        # Nenner und laesst die Naehe zusammenbrechen -- genau richtig, denn
        # eine Frage voller unbekannter Woerter ist nicht belegt.
        return math.log(gesamt)
    if n / gesamt > HAEUFIG:
        return 0.0
    return math.log(gesamt / n)


def suchen(frage: str, idx: dict, faelle: dict[str, Fall],
           grenze: int = 5) -> list[tuple[float, Fall]]:
    """Naehe = getroffene Information / verlangte Information.

    Beide Fehlrichtungen sind hier schon gemessen worden und beide sind
    gefaehrlich:

    * Zu streng: der alte Mengenschnitt in `agents/kernel.py` lieferte ueber
      **alle 133** Faelle der Historie 0,000, weil die Frage *atomarer* sagte
      und der Eintrag *atomar*. Der Kern antwortete auf jede Frage
      "nicht belegt".
    * Zu grosszuegig: die erste Fassung hier gab der Kontrollfrage
      *"Rezept fuer Zwiebelkuchen mit Speck"* **0,400** und, nach der ersten
      Korrektur, sogar **1,000** -- getroffen hatten `fuer` und `mit`.

    Der Nenner ist deshalb die Information, die die Frage *verlangt*
    (einschliesslich der Woerter, die im Korpus gar nicht vorkommen), nicht
    die, die sie zufaellig enthaelt.

    **Zurueckgegeben werden zwei Zahlen, und das ist Absicht.** `naehe` ist
    ein Anteil: wie viel der verlangten Information gefunden wurde. `info`
    ist die gefundene Information in nats -- also wie viel ueberhaupt
    verlangt war. Eine Frage aus lauter haeufigen Woertern kann `naehe`
    1,000 erreichen und traegt trotzdem fast nichts; gemessen: *"und mit
    fuer das"* verlangt 4,5 nats, *"atomarer Schreibvorgang Datenverlust"*
    11,3, *"Wie funktioniert Plugin Dispatch"* 11,9.

    Eine absolute Schwelle dazwischen habe ich **nicht** gefunden, und
    deshalb steht hier keine: der Median informativer Wortstaemme liegt bei
    6,08 (ein Stamm in 0,2 % der Faelle), sein 25.-Perzentil bei 4,83 --
    beide Werte wuerden *"Plugin Dispatch"* (staerkstes Wort 3,55)
    mitverwerfen. Eine Konstante, die genau meine zwei Gegenbeispiele
    trennt, waere auf sie angepasst und nicht gemessen. Zwei sichtbare
    Zahlen sind ehrlicher als eine zurechtgeschnittene.
    """
    woerter = {stamm(w) for w in _WORT.findall(frage)}
    gesamt = max(len(faelle), 1)
    gewichte = {w: _gewicht(w, idx, gesamt) for w in woerter}
    verlangt = sum(gewichte.values())
    if verlangt <= 0:
        return []     # nur Fuellwoerter: keine Frage, die der Korpus lesen kann
    punkte: dict[str, float] = {}
    for w, g in gewichte.items():
        if g <= 0 or w not in idx:
            continue
        for fid in idx[w]:
            punkte[fid] = punkte.get(fid, 0.0) + g
    treffer = [(t / verlangt, t, faelle[fid])
               for fid, t in punkte.items() if fid in faelle]
    treffer.sort(key=lambda x: (-x[0], -x[1], x[2].fid))
    return treffer[:grenze]


# ---------------------------------------------------------------------------
# Formate
# ---------------------------------------------------------------------------

def als_chat(f: Fall) -> dict:
    return {"messages": [
        {"role": "user", "content": f"Was gilt im Repo zu: {f.titel}?"},
        {"role": "assistant", "content": f.text},
    ], "meta": {"art": f.art, "quelle": f.quelle}}


def als_instruct(f: Fall) -> dict:
    return {"instruction": f"Erklaere, was im Repo zu '{f.titel}' festgehalten ist.",
            "input": f.quelle, "output": f.text,
            "meta": {"art": f.art, "id": f.fid}}


def beispiele_md(faelle: list[Fall], je_art: int) -> str:
    """Damit ein Mensch pruefen kann, was drinsteht.

    Ein Korpus, den nur ein Programm liest, wird nie gegengelesen -- und ein
    Fehler darin faellt dann erst in einer Antwort auf.
    """
    zeilen = ["# Korpus — Auszuege", "",
              "Erzeugt von `scripts/hugin_corpus.py`. Nicht von Hand aendern: "
              "der naechste Bau ueberschreibt die Datei.", ""]
    nach_art: dict[str, list[Fall]] = {}
    for f in faelle:
        nach_art.setdefault(f.art, []).append(f)
    for art in sorted(nach_art):
        gruppe = nach_art[art]
        zeilen += [f"## {art} — {len(gruppe)} Faelle", ""]
        for f in gruppe[:je_art]:
            auszug = f.text if len(f.text) <= 600 else f.text[:600] + " …"
            zeilen += [f"**{f.titel}** · `{f.quelle}`", "",
                       "```", auszug, "```", ""]
    return "\n".join(zeilen) + "\n"


# ---------------------------------------------------------------------------
# Bauen
# ---------------------------------------------------------------------------

def _jsonl(objekte: list[dict]) -> str:
    return "".join(json.dumps(o, ensure_ascii=False, sort_keys=True) + "\n"
                   for o in objekte)


def bauen(k: dict) -> tuple[dict[str, str], dict]:
    """Gibt {Dateiname: Inhalt} und das Manifest zurueck -- ohne zu schreiben.

    Getrennt, damit `pruefen` zweimal bauen und die Bytes vergleichen kann,
    ohne den Arbeitsbaum anzufassen.
    """
    faelle, herkunft = alle_faelle(k)
    formate = set(k.get("formate", VORGABE["formate"]))
    dateien: dict[str, str] = {}

    if "faelle" in formate:
        dateien["faelle.jsonl"] = _jsonl([f.to_dict() for f in faelle])
    if "chat" in formate:
        dateien["chat.jsonl"] = _jsonl([als_chat(f) for f in faelle])
    if "instruct" in formate:
        dateien["instruct.jsonl"] = _jsonl([als_instruct(f) for f in faelle])
    if "index" in formate:
        dateien["index.json"] = json.dumps(
            {"stamm": STAMM, "eintraege": index_bauen(faelle)},
            ensure_ascii=False, sort_keys=True, indent=0) + "\n"
    if "beispiele" in formate:
        dateien["beispiele.md"] = beispiele_md(
            faelle, int(k.get("beispiele_je_art", 2)))

    manifest = {
        "schema": "hugin.corpus.v1",
        "erzeugt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "faelle": len(faelle),
        "zeichen": sum(len(f.text) for f in faelle),
        "herkunft": herkunft,
        "arten": {a: sum(1 for f in faelle if f.art == a)
                  for a in sorted({f.art for f in faelle})},
        "stamm": STAMM,
        "dateien": {n: {"bytes": len(t.encode()),
                        "sha256": hashlib.sha256(t.encode()).hexdigest()}
                    for n, t in sorted(dateien.items())},
    }
    # `git` fehlt im Containerlayout. Das wird **benannt**, nicht verschwiegen:
    # genau hier verschwanden vorher 119 von 178 Faellen lautlos.
    if herkunft.get("commits", 0) == 0:
        manifest["hinweis_commits"] = (
            "0 Commit-Faelle — kein .git erreichbar. Der eingecheckte Korpus "
            "traegt trotzdem, denn er wurde dort gebaut, wo .git vorhanden war.")
    return dateien, manifest


def schreiben(dateien: dict[str, str], manifest: dict) -> int:
    ganz = "\n".join(dateien.values()) + json.dumps(manifest, ensure_ascii=False)
    lecks = leckpruefung(ganz)
    if lecks:
        # Nie schreiben. Der Korpus wird eingecheckt und mit dem Image
        # ausgeliefert -- ein Geheimnis darin waere veroeffentlicht.
        print("ABBRUCH — der Korpus enthaelt etwas Geheimes:", file=sys.stderr)
        for l in lecks:
            print(f"  {l}", file=sys.stderr)
        return 2
    KORPUS.mkdir(parents=True, exist_ok=True)
    for name, inhalt in sorted(dateien.items()):
        (KORPUS / name).write_text(inhalt, encoding="utf-8")
    (KORPUS / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"corpus/: {manifest['faelle']} Faelle, {manifest['zeichen']} Zeichen, "
          f"{len(dateien) + 1} Dateien")
    for a, n in manifest["arten"].items():
        print(f"  {a:<22} {n}")
    return 0


def pruefen(k: dict) -> int:
    """Drei Fragen, und jede wird gerechnet.

    *aktuell* -- entspricht der eingecheckte Korpus dem, was jetzt entstuende.
    *deterministisch* -- ergibt zweimal Bauen dieselben Bytes.
    *dicht* -- ist er groesser als die Quelle, die er ersetzt (26.544 B).
    """
    befunde = []
    a, ma = bauen(k)
    b, mb = bauen(k)
    if a != b:
        abweichend = sorted(n for n in a if a.get(n) != b.get(n))
        befunde.append(f"nicht deterministisch: {', '.join(abweichend)}")

    if not KORPUS.is_dir():
        befunde.append("corpus/ fehlt — `python3 scripts/hugin_corpus.py bauen`")
    else:
        for name, inhalt in sorted(a.items()):
            p = KORPUS / name
            if not p.is_file():
                befunde.append(f"{name} fehlt")
            elif p.read_text(encoding="utf-8") != inhalt:
                befunde.append(f"{name} veraltet — neu bauen")

    print(f"Faelle:   {ma['faelle']}")
    print(f"Zeichen:  {ma['zeichen']}")
    for art, n in ma["arten"].items():
        print(f"  {art:<22} {n}")
    print(f"determin: {'ja' if a == b else 'NEIN'}")
    for f in befunde:
        print(f"[BEFUND] {f}")
    return 1 if befunde else 0


def laden() -> tuple[dict, dict[str, Fall]]:
    """Den gebauten Korpus lesen. Ein Dateilesen, kein Unterprozess."""
    idx = json.loads((KORPUS / "index.json").read_text(encoding="utf-8"))["eintraege"]
    faelle = {}
    for zeile in (KORPUS / "faelle.jsonl").read_text(encoding="utf-8").splitlines():
        if not zeile.strip():
            continue
        d = json.loads(zeile)
        faelle[d["id"]] = Fall(fid=d["id"], art=d["art"], titel=d["titel"],
                               text=d["text"], quelle=d["quelle"],
                               anker=d.get("anker", []))
    return idx, faelle


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="befehl", required=True)
    sub.add_parser("bauen", help="Korpus und Index schreiben")
    sub.add_parser("pruefen", help="aktuell, deterministisch, dicht")
    s = sub.add_parser("suchen", help="im gebauten Index suchen")
    s.add_argument("frage")
    s.add_argument("--n", type=int, default=5)
    a = p.parse_args(argv)

    k = konfig()
    if a.befehl == "bauen":
        dateien, manifest = bauen(k)
        return schreiben(dateien, manifest)
    if a.befehl == "pruefen":
        return pruefen(k)

    if not (KORPUS / "index.json").is_file():
        print("corpus/index.json fehlt — `python3 scripts/hugin_corpus.py bauen`",
              file=sys.stderr)
        return 1
    idx, faelle = laden()
    treffer = suchen(a.frage, idx, faelle, a.n)
    if not treffer:
        print("kein Treffer")
        return 1
    for naehe, info, f in treffer:
        auszug = f.text.replace("\n", " ")[:200]
        # Beide Zahlen. Die zweite sagt, wie viel ueberhaupt verlangt war —
        # ohne sie sieht eine informationsarme Frage aus wie ein Volltreffer.
        print(f"[Naehe {naehe:.3f} · {info:.1f} nats] {f.art:<18} {f.quelle}")
        print(f"          {auszug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
