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


def extract_cases(commit_limit: int = 120) -> list[Case]:
    """Faelle aus Ledger und git. Gemessen, nicht gepflegt."""
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
    lex = len(st & ct) / len(st) if st else 0.0

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
    blocking = [c for sc, c in scored[:12]
                if c.kind == "invariante" and sc >= MIN_SIMILARITY
                and _FORBIDS.search(c.text)]
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
