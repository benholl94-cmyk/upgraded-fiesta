"""kernel.py -- Schliessen aus der eigenen, nachverifizierten Repo-Historie.

## Der Denkfehler, den diese Datei korrigiert

Die erste Fassung der Limit-Stufe T0 war als *Verzicht* gebaut: Skripte statt
Intelligenz. Das ist die falsche Achse. Wenn Claude nicht erreichbar ist,
braucht es nicht weniger Denken, sondern eine andere Quelle dafuer.

## Die Quelle

Dieses Repo besitzt etwas, das kein Anbieter besitzen kann: einen
fortlaufend **nachverifizierten** Kausalbericht seiner eigenen Entwicklung.
Jede Entscheidung mit ihrer verworfenen Alternative. Jede Sackgasse -- also
genau das, was nie committet wird und deshalb sonst wiederholt wird. Jede
Invariante mit einem Anker, den `munin_continuity.verify` bei jedem Lauf
nachrechnet.

Ein Sprachmodell aus dem Netz traegt statistisches Wissen ueber Code im
Allgemeinen. Dieses Repo traegt geprüfte Bodenwahrheit ueber sich selbst.
Bei Fragen ueber *dieses* Repo ist das nicht die schwaechere Quelle.

## Was der Kernel tut

Fallgestuetztes Schliessen (case-based reasoning), kein Sprachmodell:

1. **Faelle gewinnen** aus Ledger (Entscheidung, Sackgasse, Invariante) und
   git (welcher Commit beruehrte welche Subsysteme).
2. **Aehnlichkeit strukturell** messen -- ueber beruehrte Subsysteme und
   Pfade, nicht ueber Wortueberlappung. Zwei Aufgaben sind verwandt, wenn sie
   dieselben Teile des Systems anfassen, nicht wenn sie aehnlich klingen.
3. **Invarianten als harte Schranke** anwenden. Eine Invariante ist keine
   Empfehlung: verbietet sie den Weg, wird abgelehnt, egal wie aehnlich der
   beste Fall ist.
4. **Ablehnen ohne Praezedenzfall.** Unter der Schwelle gibt es keine
   Empfehlung, sondern die Auskunft, dass es keine gibt. Ein Kernel, der bei
   duenner Evidenz raet, ist schaedlicher als einer, der schweigt.

## Die Eigenschaft, die ihn von einem statischen Modell unterscheidet

Ein Fall, dessen Anker verrottet sind, **verliert automatisch Gewicht**. Die
Wissensbasis reinigt sich selbst, weil sie an nachrechenbare Punkte im Repo
gebunden ist. Ein Modell mit Stichtag kann das nicht: es weiss nie, welcher
Teil seines Wissens gerade falsch geworden ist.

Jeder versiegelte Sitzungsabschluss fuegt Faelle hinzu. Der Kernel wird
besser, ohne dass jemand ihn trainiert.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / ".claude" / "continuity" / "ledger.json"

# Unterhalb dieser Aehnlichkeit gibt es keine Empfehlung, sondern die Auskunft
# dass es keine gibt. Die Kosten einer falschen Empfehlung sind hier hoeher
# als die eines "weiss ich nicht".
#
# KALIBRIERUNG, ehrlich benannt: 0.34 war vor jeder Messung geraten und lehnte
# alles ab. Gegen den vorhandenen Bestand gemessen liegen einschlaegige Faelle
# bei ~0.33, klar unverwandte bei 0.00-0.22. Der Wert liegt in dieser Luecke.
# Das sind wenige Beobachtungen -- die Schwelle ist plausibel, nicht bewiesen,
# und gehoert nachgezogen, sobald das Ledger mehr Faelle traegt.
MIN_SIMILARITY = 0.30
TOP_K = 4

# Anker, die nicht mehr aufloesen, entwerten ihren Fall -- aber sie loeschen
# ihn nicht. Ein alter Fall kann richtig bleiben, auch wenn die Zeilennummer
# gewandert ist.
ROT_PENALTY = 0.45

_WORD = re.compile(r"[a-zA-ZäöüÄÖÜß_][\w\-.]{2,}")

# Funktionswoerter tragen keine Bedeutung, blaehen aber die Frage auf und
# senken damit jede Abdeckung.
STOP = frozenset("""
der die das ein eine einen einem eines und oder aber nicht kein keine mit ohne
fuer für von zum zur auf aus bei nach ueber über wenn dann als wie ist sind war
werden wird kann soll muss darf man sich noch nur auch schon bis statt
the and for with from that this into then than there here have has был
""".split())


def _run(*args: str) -> str:
    r = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def subsystem(path: str) -> str:
    """Grobe Zugehoerigkeit. crates/hm-gateway/src/main.rs -> crates/hm-gateway"""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return ""
    if parts[0] == "crates" and len(parts) > 1:
        return f"crates/{parts[1]}"
    if parts[0] in ("scripts", "tests", "agents", "hugin", "docs", "config", ".github"):
        return parts[0]
    return parts[0]


@dataclass(frozen=True)
class Situation:
    """Wonach gefragt wird."""

    text: str
    paths: tuple[str, ...] = ()
    kind: str = ""                 # fix | implement | refactor | decide | debug

    @property
    def subsystems(self) -> frozenset[str]:
        return frozenset(s for s in (subsystem(p) for p in self.paths) if s)

    @property
    def terms(self) -> frozenset[str]:
        return frozenset(w.lower() for w in _WORD.findall(self.text))


@dataclass
class Case:
    """Ein belegter Vorgang aus der Repo-Historie."""

    cid: str
    kind: str                      # entscheidung | sackgasse | invariante | commit
    text: str
    subsystems: frozenset[str] = field(default_factory=frozenset)
    anchors: tuple[str, ...] = ()
    rotted: bool = False

    @property
    def terms(self) -> frozenset[str]:
        return frozenset(w.lower() for w in _WORD.findall(self.text))

    @property
    def weight(self) -> float:
        """Wie stark dieser Fall zaehlt. Invarianten und Sackgassen wiegen
        schwerer: eine Invariante gilt weiter, und eine Sackgasse spart die
        teuerste Sorte Zeit -- die zweimal verlorene."""
        base = {"invariante": 1.0, "sackgasse": 0.9,
                "entscheidung": 0.8, "commit": 0.35}.get(self.kind, 0.5)
        return base * (ROT_PENALTY if self.rotted else 1.0)


def _anchor_paths(anchors) -> set[str]:
    out = set()
    for a in anchors or ():
        if a.startswith("path:"):
            rest = a[5:]
            head, _, tail = rest.rpartition(":")
            out.add(head if tail.isdigit() and head else rest)
    return out


def _anchor_rotted(anchors) -> bool:
    for a in anchors or ():
        if a.startswith("path:"):
            rest = a[5:]
            head, _, tail = rest.rpartition(":")
            p = REPO / (head if tail.isdigit() and head else rest)
            if not p.exists():
                return True
        elif a.startswith("sha:"):
            if subprocess.run(["git", "cat-file", "-e", f"{a[4:]}^{{commit}}"],
                              cwd=REPO, capture_output=True).returncode != 0:
                return True
    return False


#: Der vorgebaute Korpus. Fehlt er, wird live extrahiert -- eine fehlende
#: Datei darf die Erdung nicht abschalten.
KORPUS = REPO / "corpus" / "faelle.jsonl"


def _cases_aus_korpus() -> list[Case]:
    """Den vorgebauten Korpus lesen, statt bei jeder Frage git zu befragen.

    **Drei gemessene Gruende** (2026-08-01), und der dritte ist der teure:

    * Die Live-Extraktion las bei *jeder* Frage 120 Commits nach --
      0,58 s und ~240 Unterprozesse, pro Frage.
    * Sie sah 178 Faelle mit 26.544 Zeichen. Der gebaute Korpus hat ueber
      870 mit rund 500.000: Markdown-Abschnitte, Docstrings und
      Rust-Moduldoku, in denen dieses Repo den groessten Teil seiner
      Begruendungen ablegt.
    * **Im Laufzeitimage gibt es kein `.git`.** Dort lieferte dieselbe
      Funktion 59 statt 178 Faelle -- lautlos, und die Antwort sah
      weiterhin aus wie eine Antwort. Der eingecheckte Korpus liegt im
      Image und traegt dort, wo git fehlt.

    Faellt die Datei weg, wird live extrahiert. Ein fehlender Korpus soll
    langsamer und aermer machen, nicht stumm.
    """
    if not KORPUS.is_file():
        return []
    out: list[Case] = []
    try:
        roh = KORPUS.read_text(encoding="utf-8")
    except OSError:
        return []
    for zeile in roh.splitlines():
        if not zeile.strip():
            continue
        try:
            d = json.loads(zeile)
        except json.JSONDecodeError:
            continue
        art = str(d.get("art", ""))
        # Artnamen des Korpus auf die des Kerns abbilden: `Case.kind` steuert
        # die Gewichtung, und ein unbekannter Wert faellt sonst still in den
        # Standardfall.
        kind = art.split("-", 1)[1] if art.startswith("ledger-") else art
        anchors = tuple(d.get("anker", ()))
        subs = {subsystem(p) for p in _anchor_paths(anchors)}
        out.append(Case(cid=str(d.get("id", "")), kind=kind,
                        text=str(d.get("text", "")),
                        subsystems=frozenset(s for s in subs if s),
                        anchors=anchors, rotted=False))
    return out


def extract_cases(commit_limit: int = 120) -> list[Case]:
    """Faelle aus dem gebauten Korpus, sonst live aus Ledger und git."""
    vorgebaut = _cases_aus_korpus()
    if vorgebaut:
        return vorgebaut

    cases: list[Case] = []

    if LEDGER.is_file():
        try:
            raw = json.loads(LEDGER.read_text(encoding="utf-8"))
            entries = raw.get("entries", raw if isinstance(raw, list) else [])
        except (json.JSONDecodeError, OSError):
            entries = []
        for e in entries:
            kind = e.get("kind", "notiz")
            if kind not in ("entscheidung", "sackgasse", "invariante"):
                continue           # 'offen' ist eine Aufgabe, kein Praezedenzfall
            anchors = tuple(e.get("anchors", ()))
            subs = {subsystem(p) for p in _anchor_paths(anchors)}
            cases.append(Case(
                cid=str(e.get("id", f"led-{len(cases)}")), kind=kind,
                text=str(e.get("text", "")),
                subsystems=frozenset(s for s in subs if s),
                anchors=anchors, rotted=_anchor_rotted(anchors)))

    log = _run("git", "log", f"-{commit_limit}", "--format=%h%x1f%s")
    for line in log.splitlines():
        if "\x1f" not in line:
            continue
        sha, subj = line.split("\x1f", 1)
        files = _run("git", "show", "--name-only", "--format=", "-1", sha).split()
        subs = frozenset(s for s in (subsystem(f) for f in files) if s)
        if not subs:
            continue
        cases.append(Case(cid=sha, kind="commit", text=subj, subsystems=subs,
                          anchors=(f"sha:{sha}",)))
    return cases


#: Ab dieser Laenge gilt ein gemeinsamer Wortanfang als dasselbe Wort.
#: Kuerzer waere gefaehrlich — "ver" verbindet "verboten" mit "Verzeichnis".
_STAMM_MIN = 5


def _stamm_treffer(frage_wort: str, fall_wort: str) -> bool:
    """Deutsche Flexion darf einen Beleg nicht unsichtbar machen.

    Der exakte Mengenschnitt scheiterte an genau dem, wofuer er da ist:
    die Frage sagt *atomarer*, der Ledgereintrag sagt *atomar* — kein
    Treffer, Aehnlichkeit 0,000. Gemessen ueber alle 133 Faelle der Historie
    war **jede** Aehnlichkeit exakt null, und der lokale Kern antwortete
    darum auf jede Frage "nicht belegt". Ein Beleg, den niemand findet, ist
    kein Beleg.

    Kein Stemmer, keine Abhaengigkeit: ein gemeinsamer Wortanfang ab
    `_STAMM_MIN` Zeichen genuegt, und eines der beiden Woerter muss ein
    Praefix des anderen sein. Das faengt Flexion (atomar/atomarer,
    Datei/Dateien, Test/Tests) und laesst blosse Silbengleichheit
    ("Verzeichnis"/"verboten") aussen vor.
    """
    if frage_wort == fall_wort:
        return True
    kurz, lang = sorted((frage_wort, fall_wort), key=len)
    if len(kurz) < _STAMM_MIN:
        return False
    return lang.startswith(kurz)


def _lexical_coverage(frage_terme: frozenset[str], fall_terme: frozenset[str]) -> float:
    """Wie viel von dem, wonach gefragt wird, kommt in diesem Fall vor."""
    if not frage_terme:
        return 0.0
    getroffen = sum(1 for f in frage_terme
                    if any(_stamm_treffer(f, k) for k in fall_terme))
    return getroffen / len(frage_terme)


def similarity(s: Situation, c: Case) -> float:
    """Struktur vor Wortlaut.

    Zwei Vorgaenge sind verwandt, wenn sie dieselben Teile des Systems
    anfassen -- nicht, wenn sie aehnlich klingen. Wortueberlappung allein
    verbindet 'Test schlaegt fehl' im Gateway mit 'Test schlaegt fehl' in der
    PWA, was fast nie hilft.
    """
    struct = 0.0
    if s.subsystems and c.subsystems:
        inter = len(s.subsystems & c.subsystems)
        union = len(s.subsystems | c.subsystems)
        struct = inter / union if union else 0.0

    # Abdeckung der Frage, nicht Ueberlappung beider Mengen. Jaccard bestraft
    # hier systematisch: eine kurze Frage gegen einen langen Ledgereintrag
    # teilt vielleicht vier Woerter und bekommt 4/42, obwohl der Eintrag genau
    # diese Frage beantwortet. Gefragt ist "wie viel von dem, wonach ich frage,
    # kommt in diesem Fall vor" -- das ist asymmetrisch.
    st, ct = s.terms - STOP, c.terms - STOP
    lex = _lexical_coverage(st, ct)

    # Hat ein Fall keine Pfadanker, gibt es strukturell nichts zu vergleichen.
    # Ihn dann auf 0.35*lex zu daempfen hiesse, "keine Struktur" wie "keine
    # Uebereinstimmung" zu behandeln -- und genau die wertvollsten Eintraege
    # (Sackgassen, Entscheidungen) tragen oft nur einen sha:-Anker oder gar
    # keinen. Ohne Struktur zaehlt der Wortlaut allein.
    if not c.subsystems or not s.subsystems:
        return lex
    return 0.65 * struct + 0.35 * lex


@dataclass
class Evidence:
    case: Case
    score: float

    def line(self) -> str:
        rot = " [Anker verrottet]" if self.case.rotted else ""
        anchors = " ".join(self.case.anchors[:2])
        return (f"{self.score:.2f}  {self.case.kind:<12} {self.case.text[:96]}"
                f"{rot}" + (f"  ({anchors})" if anchors else ""))


@dataclass
class Inference:
    verdict: str                   # empfehlung | abgelehnt | verboten
    summary: str
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)
    blocking: list[Case] = field(default_factory=list)

    @property
    def actionable(self) -> bool:
        return self.verdict == "empfehlung"

    def render(self) -> str:
        L = [f"[{self.verdict.upper()}]  Vertrauen {self.confidence:.0%}",
             "", self.summary, ""]
        if self.blocking:
            L += ["Verletzte Invarianten:"]
            L += [f"  ✗ {c.text[:120]}" for c in self.blocking]
            L.append("")
        if self.evidence:
            L += ["Belege aus der eigenen Historie:"]
            L += [f"  {e.line()}" for e in self.evidence]
        return "\n".join(L)


# Signalwoerter, an denen ein Fall als Verbot statt als Hinweis gilt.
_FORBIDS = re.compile(
    r"\b(nie(mals)?|kein[e]?[rnms]?|darf nicht|verboten|niemals)\b", re.IGNORECASE)

#: Fragewoerter am Satzanfang. Die Liste ist kurz und deutsch, weil die
#: Fragen an diesen Kern es sind; ein Fragezeichen zaehlt unabhaengig davon.
_FRAGEWORT = re.compile(
    r"^\s*(warum|wieso|weshalb|was|wie|wann|wer|welche[rsnm]?|wo(her|hin|durch|fuer|für)?|"
    r"warum|ist|sind|kann|koennen|können|gibt|warum)\b", re.IGNORECASE)


def _ist_frage(text: str) -> bool:
    """Unterscheidet eine Frage von einem Vorhaben.

    Verbieten kann man ein Vorhaben, keine Frage. Ohne diese Unterscheidung
    beantwortete der Kern *„warum ist ein atomarer Schreibvorgang sicherer?"*
    mit „VERWEIGERT — eine Invariante verbietet das" und zitierte dabei genau
    die Invariante, die die Antwort enthaelt: `_FORBIDS` findet das Wort
    *kein* auch in erklaerender Prosa („Hier *kein* Randfall …").

    Nicht ueber `Situation.kind`: das Feld setzt in der Praxis niemand —
    `agents/brain.py` uebergibt es nie. Eine Schranke an ein Feld zu haengen,
    das leer bleibt, schaltet sie ab, statt sie zu schaerfen. Die Form des
    Satzes ist dagegen immer vorhanden.
    """
    t = text.strip()
    return t.endswith("?") or bool(_FRAGEWORT.match(t))


def infer(s: Situation, cases: list[Case] | None = None) -> Inference:
    """Situation -> begruendete Empfehlung, Ablehnung oder Verbot."""
    cases = cases if cases is not None else extract_cases()
    if not cases:
        return Inference("abgelehnt",
                         "Keine Faelle vorhanden — der Kernel hat nichts, worauf "
                         "er sich stuetzen koennte.", 0.0)

    scored = sorted(((similarity(s, c), c) for c in cases),
                    key=lambda t: -t[0] * t[1].weight)

    # 1. Harte Schranke: eine einschlaegige Invariante, die verbietet.
    #
    # Nur gegen einen **Vorschlag**, nie gegen eine Frage. `_FORBIDS` sucht
    # Verneinungen im Fliesstext, und eine Invariante wie "Hier *kein*
    # Randfall: MemoryStore persistiert bei jedem remember()" ist erklaerend,
    # nicht verbietend. Ohne diese Unterscheidung beantwortete der Kern die
    # Frage "warum ist ein atomarer Schreibvorgang sicherer" mit
    # "VERWEIGERT — eine Invariante verbietet das" und zitierte dabei genau
    # die Invariante, die die Antwort enthaelt. Eine Frage kann man nicht
    # verbieten; verbieten kann man nur ein Vorhaben.
    blocking = [c for sc, c in scored[:12]
                if not _ist_frage(s.text) and c.kind == "invariante"
                and sc >= MIN_SIMILARITY and _FORBIDS.search(c.text)]
    if blocking:
        return Inference(
            "verboten",
            "Eine Invariante aus der eigenen Historie schliesst diesen Weg aus. "
            "Invarianten sind keine Empfehlungen — sie werden nicht gegen "
            "Aehnlichkeit abgewogen.",
            confidence=1.0,
            evidence=[Evidence(c, sc) for sc, c in scored[:TOP_K] if sc > 0],
            blocking=blocking)

    top = [(sc, c) for sc, c in scored[:TOP_K] if sc >= MIN_SIMILARITY]
    if not top:
        best = scored[0][0] if scored else 0.0
        return Inference(
            "abgelehnt",
            f"Kein Praezedenzfall ueber der Schwelle (bester Treffer {best:.2f} < "
            f"{MIN_SIMILARITY}). Der Kernel raet nicht — hier braucht es "
            f"ein Modell oder eine Entscheidung des Masters.",
            confidence=best)

    # 2. Sackgassen zuerst nennen: eine vermiedene Wiederholung ist der
    #    groesste Einzelgewinn dieses Verfahrens.
    dead = [c for sc, c in top if c.kind == "sackgasse"]
    conf = sum(sc * c.weight for sc, c in top) / len(top)
    if dead:
        summary = ("Es gibt einschlaegige Sackgassen. Diese Wege wurden bereits "
                   "versucht und sind gescheitert — sie stehen in keinem Commit, "
                   "weil Gescheitertes nicht committet wird.")
    else:
        summary = ("Aehnliche Vorgaenge liegen vor. Die Belege unten zeigen, was "
                   "in vergleichbaren Faellen entschieden und getan wurde.")

    return Inference("empfehlung", summary, min(conf, 1.0),
                     evidence=[Evidence(c, sc) for sc, c in top])


__all__ = ["Situation", "Case", "Evidence", "Inference", "infer",
           "extract_cases", "similarity", "subsystem",
           "MIN_SIMILARITY", "ROT_PENALTY"]
