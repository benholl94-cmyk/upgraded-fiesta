"""Konsensgrad — Uneinigkeit zwischen Modellen als messbares Signal.

Die übliche Bauweise behandelt mehrere Antworten als Wettlauf, den eine
gewinnt (`race`, `best`). Damit wird die wertvollste Information weggeworfen:
**ob die anderen zugestimmt hätten.**

Hier andersherum. Stimmen unabhängige Modelle überein, ist das ein starkes
Vertrauenssignal. Gehen sie auseinander, liegt entweder eine Halluzination
oder eine echt strittige Frage vor — und man weiss es, *bevor* man der Antwort
vertraut.

Kein einzelner Anbieter kann das liefern. Nicht weil es schwer ist, sondern
weil es mehrere Modelle mehrerer Häuser braucht.

## Was gemessen wird

Zwei Ebenen, weil Textähnlichkeit allein täuscht: zwei Antworten können
gleich klingen und in der einen Zahl abweichen, auf die es ankommt.

1. **Textkonsens** — paarweise Ähnlichkeit der normalisierten Antworten.
2. **Faktenkonsens** — Zahlen, Daten, Bezeichner und Zitate werden einzeln
   verglichen. Genau hier entstehen die Divergenzen, die man sehen will.

Der Gesamtwert gewichtet Fakten höher, weil eine abweichende Jahreszahl
schwerer wiegt als ein anderer Satzbau.

## Grenzen, offen benannt

Das ist ein **lexikalischer** Vergleich mit Bordmitteln, kein semantischer.
"12" und "zwölf" gelten als verschieden; "steigt" und "nimmt zu" ebenfalls.
Die Folge ist ein systematischer Fehler in Richtung *zu wenig* Konsens —
und das ist die sichere Richtung: das System behauptet nie Einigkeit, die
nicht da ist. Für semantischen Abgleich bräuchte es Embeddings, also einen
weiteren Modellaufruf, und der wäre selbst wieder eine Meinung.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import combinations

# Schwellen je Aufgabenart. Eine Faktenfrage muss hohen Konsens haben, sonst
# ist die Antwort wertlos; beim Brainstorming ist Streuung erwuenscht und
# eine hohe Schwelle waere schaedlich.
THRESHOLDS: dict[str, float] = {
    "factual": 0.75,
    "code": 0.65,
    "reasoning": 0.55,
    "summary": 0.50,
    "brainstorm": 0.20,
    "default": 0.60,
}

CONSENSUS = "KONSENS"        # Modelle sind sich einig
SPLIT = "GETEILT"            # zwei oder mehr Lager
NO_CONSENSUS = "KEIN_KONSENS"  # breite Streuung, Antwort nicht belastbar
SINGLE = "EINZELQUELLE"      # nur eine Antwort — kein Konsens messbar

# Faktentraeger. Bewusst eng: was hier landet, muss zwischen Antworten
# vergleichbar sein, ohne dass Formulierungsunterschiede durchschlagen.
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?(?:\s*%)?(?![\w])")
_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_IDENT = re.compile(r"\b[a-z_][a-z0-9_]{2,}(?:\(\)|\.[a-z_]\w*)+", re.IGNORECASE)
_QUOTED = re.compile(r"[\"'`]([^\"'`\n]{3,60})[\"'`]")
_URL = re.compile(r"https?://[^\s)>\]]+")

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s%.,:/-]")


@dataclass(frozen=True)
class Answer:
    """Eine Antwort samt Herkunft. Die Herkunft ist Teil des Signals:
    Konsens zwischen zwei Modellen desselben Hauses wiegt weniger."""

    provider: str
    text: str
    latency_ms: int = 0
    vendor: str = ""          # z.B. "openai", "google" — leer = unbekannt

    @property
    def house(self) -> str:
        return self.vendor or self.provider


@dataclass(frozen=True)
class Divergence:
    """Eine konkrete Stelle, an der die Antworten auseinandergehen."""

    kind: str                       # number | year | identifier | quote | url
    values: dict[str, str]          # provider -> abweichender Wert
    note: str = ""

    def __str__(self) -> str:
        pairs = ", ".join(f"{p}={v!r}" for p, v in sorted(self.values.items()))
        return f"{self.kind}: {pairs}" + (f"  ({self.note})" if self.note else "")


@dataclass
class ConsensusReport:
    score: float
    verdict: str
    task_kind: str
    text_score: float
    fact_score: float
    answers: tuple[Answer, ...] = ()
    divergences: tuple[Divergence, ...] = ()
    houses: int = 0

    @property
    def trustworthy(self) -> bool:
        """Erreicht der Konsens die Schwelle dieser Aufgabenart?"""
        return self.verdict == CONSENSUS

    def summary(self) -> str:
        lines = [
            f"Konsens {self.score:.0%}  [{self.verdict}]  "
            f"Aufgabe={self.task_kind} Schwelle={threshold(self.task_kind):.0%}",
            f"  {len(self.answers)} Antwort(en) aus {self.houses} unabhaengigen Haus/Haeusern",
            f"  Text {self.text_score:.0%} · Fakten {self.fact_score:.0%}",
        ]
        if self.divergences:
            lines.append(f"  {len(self.divergences)} Divergenz(en):")
            lines += [f"    - {d}" for d in self.divergences[:8]]
            if len(self.divergences) > 8:
                lines.append(f"    … {len(self.divergences) - 8} weitere")
        elif len(self.answers) > 1:
            lines.append("  keine faktischen Divergenzen gefunden")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "verdict": self.verdict,
            "task_kind": self.task_kind,
            "threshold": threshold(self.task_kind),
            "text_score": round(self.text_score, 4),
            "fact_score": round(self.fact_score, 4),
            "answers": len(self.answers),
            "houses": self.houses,
            "providers": [a.provider for a in self.answers],
            "divergences": [{"kind": d.kind, "values": d.values, "note": d.note}
                            for d in self.divergences],
        }


def threshold(task_kind: str) -> float:
    return THRESHOLDS.get(task_kind, THRESHOLDS["default"])


def normalize(text: str) -> str:
    """Formatierung entfernen, damit Satzbau nicht als Dissens zaehlt."""
    t = text.lower()
    t = re.sub(r"```.*?```", " ", t, flags=re.DOTALL)   # Codebloecke separat gewertet
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()


def extract_facts(text: str) -> dict[str, set[str]]:
    """Vergleichbare Faktentraeger je Art."""
    years = set(_YEAR.findall(text))
    numbers = {m.group(0).strip().replace(" ", "") for m in _NUMBER.finditer(text)}
    # Jahreszahlen sind auch Zahlen -- doppelt zaehlen wuerde sie ueberbewerten.
    numbers -= years
    return {
        "year": years,
        "number": numbers,
        "identifier": {m.group(0) for m in _IDENT.finditer(text)},
        "quote": {m.group(1).strip().lower() for m in _QUOTED.finditer(text)},
        "url": {m.group(0).rstrip(".,;") for m in _URL.finditer(text)},
    }


def _pairwise_text_score(answers: tuple[Answer, ...]) -> float:
    norms = [normalize(a.text) for a in answers]
    if any(not n for n in norms):
        return 0.0
    ratios = [SequenceMatcher(None, a, b).ratio() for a, b in combinations(norms, 2)]
    return statistics.fmean(ratios) if ratios else 1.0


def _fact_score_and_divergences(
    answers: tuple[Answer, ...]
) -> tuple[float | None, tuple[Divergence, ...]]:
    facts = {a.provider: extract_facts(a.text) for a in answers}
    kinds = ("year", "number", "identifier", "quote", "url")
    per_kind: list[float] = []
    divergences: list[Divergence] = []

    for kind in kinds:
        sets = {p: f[kind] for p, f in facts.items()}
        union: set[str] = set().union(*sets.values()) if sets else set()
        if not union:
            continue
        # Jaccard ueber alle Antworten: wie gross ist der gemeinsame Kern?
        common = set.intersection(*sets.values()) if sets else set()
        per_kind.append(len(common) / len(union))

        # Nur Werte melden, die mindestens eine Antwort hat und mindestens
        # eine andere nicht -- das ist die Stelle, die ein Mensch pruefen muss.
        for value in sorted(union - common):
            holders = {p: value for p, s in sets.items() if value in s}
            missing = [p for p in sets if p not in holders]
            if not missing:
                continue
            divergences.append(Divergence(
                kind=kind, values=holders,
                note=f"fehlt bei {', '.join(sorted(missing))}"))

    # Kein Faktentraeger in irgendeiner Antwort -> es gibt nichts, worin man
    # uebereinstimmen koennte. Hier 1.0 zu liefern hiesse, Faktenlosigkeit als
    # Faktenuebereinstimmung zu werten; zwei voellig verschiedene Antworten
    # ohne Zahlen kaemen so auf hohen Konsens. None heisst "nicht messbar"
    # und laesst den Aufrufer allein auf den Textwert zurueckfallen.
    score = statistics.fmean(per_kind) if per_kind else None
    return score, tuple(divergences)


def _verdict(score: float, task_kind: str, answers: int, spread: float) -> str:
    if answers < 2:
        return SINGLE
    if score >= threshold(task_kind):
        return CONSENSUS
    # Zwei Lager sehen anders aus als breite Streuung: bei einem Split liegen
    # die paarweisen Werte weit auseinander, bei Rauschen alle gleich niedrig.
    return SPLIT if spread > 0.25 else NO_CONSENSUS


def evaluate(answers: list[Answer] | tuple[Answer, ...],
             task_kind: str = "default") -> ConsensusReport:
    """Antworten -> Konsensbericht.

    Wirft nicht: eine leere Liste ergibt einen Bericht mit Score 0 und
    Verdikt EINZELQUELLE. Ein Konsensmass, das bei duennen Daten abstuerzt,
    waere im Betrieb schlimmer als eines, das ehrlich 'zu wenig' sagt.
    """
    answers = tuple(a for a in answers if a.text and a.text.strip())
    if not answers:
        return ConsensusReport(0.0, SINGLE, task_kind, 0.0, 0.0, (), (), 0)
    houses = len({a.house for a in answers})
    if len(answers) == 1:
        return ConsensusReport(1.0, SINGLE, task_kind, 1.0, 1.0, answers, (), houses)

    text_score = _pairwise_text_score(answers)
    fact_raw, divergences = _fact_score_and_divergences(answers)

    if fact_raw is None:
        # Nichts Vergleichbares gefunden -- der Textwert ist alles, was es gibt.
        # Kein kuenstlicher Bonus fuer das Fehlen von Fakten.
        fact_score = text_score
        score = text_score
    else:
        # Fakten wiegen schwerer: eine abweichende Jahreszahl ist gravierender
        # als ein anderer Satzbau.
        fact_score = fact_raw
        score = 0.35 * text_score + 0.65 * fact_raw

    norms = [normalize(a.text) for a in answers]
    ratios = [SequenceMatcher(None, a, b).ratio() for a, b in combinations(norms, 2)]
    spread = (max(ratios) - min(ratios)) if len(ratios) > 1 else 0.0

    verdict = _verdict(score, task_kind, len(answers), spread)

    # Konsens aus einem einzigen Haus ist schwaecher: gleiche Trainingsdaten,
    # gleiche blinde Flecken. Das darf nicht als unabhaengige Bestaetigung
    # durchgehen.
    if verdict == CONSENSUS and houses < 2:
        verdict = SPLIT

    return ConsensusReport(score=score, verdict=verdict, task_kind=task_kind,
                           text_score=text_score, fact_score=fact_score,
                           answers=answers, divergences=divergences, houses=houses)


__all__ = ["Answer", "Divergence", "ConsensusReport", "evaluate", "threshold",
           "extract_facts", "normalize", "THRESHOLDS",
           "CONSENSUS", "SPLIT", "NO_CONSENSUS", "SINGLE"]
