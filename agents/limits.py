"""limits.py -- Limit-Erkennung als eigenständiges Urteil, nicht als Schalter.

Die erste Fassung in `hugin_relay.py` war ein Bool: Limit ja/nein. Damit löst
jede Limit-Art dieselbe Reaktion aus — und das ist fast immer falsch. Ein
Überlast-Hinweis ist nach Sekunden vorbei; ein Tageskontingent ist Stunden
weg; ein Kontextfehler geht durch Warten überhaupt nicht weg, sondern nur
durch kleinere Eingabe.

Diese Datei trennt das. Ausgabe ist ein **Signal mit Bewertung**: welche Art,
wie lange, welche Antwort.

## Die vier Arten

    OVERLOAD   Gegenstelle momentan ausgelastet. Sekunden. Erneut versuchen.
    RATE       Zu viele Anfragen pro Zeitfenster. Minuten. Drosseln.
    QUOTA      Kontingent aufgebraucht. Stunden bis Tage. Stufe wechseln.
    CONTEXT    Eingabe zu gross. Warten hilft nie. Eingabe verkleinern.

Die Unterscheidung QUOTA/CONTEXT ist die wichtigste: beide melden oft "limit",
aber die eine verlangt Geduld und die andere verbietet sie. Wer Kontextfehler
als Kontingent behandelt, wartet Stunden auf etwas, das nie eintritt.

## Warum Signaturen je Anbieter

Jeder Anbieter formuliert anders, und die Formulierungen aendern sich. Eine
einzelne Musterliste altert still: sie meldet dann "kein Limit" und der
Aufrufer laeuft ins Leere. Deshalb Signaturen je Anbieter **plus** eine
generische Lage, und `unknown` als eigenes Ergebnis statt als "alles gut".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OVERLOAD, RATE, QUOTA, CONTEXT, UNKNOWN = (
    "overload", "rate", "quota", "context", "unknown")

# Wartezeit-Vorschlag je Art, wenn die Gegenstelle keine nennt.
DEFAULT_WAIT_S = {OVERLOAD: 5, RATE: 60, QUOTA: 3600, CONTEXT: 0, UNKNOWN: 30}

# Was der Aufrufer tun soll. Bewusst hier und nicht beim Aufrufer: sonst
# entscheidet jede Aufrufstelle neu und sie driften auseinander.
ACTION = {
    OVERLOAD: "erneut versuchen",
    RATE: "drosseln und erneut versuchen",
    QUOTA: "Stufe wechseln (T1/T0) — Warten loest es nicht kurzfristig",
    CONTEXT: "Eingabe verkleinern — Warten hilft hier nie",
    UNKNOWN: "als Limit behandeln, aber vorsichtig: Muster nicht erkannt",
}


@dataclass(frozen=True)
class LimitSignal:
    kind: str
    provider: str
    matched: str
    wait_s: int
    raw_excerpt: str = ""

    @property
    def waiting_helps(self) -> bool:
        """Kontextfehler gehen durch Warten nie weg."""
        return self.kind != CONTEXT

    @property
    def action(self) -> str:
        return ACTION[self.kind]

    def __str__(self) -> str:
        return (f"[{self.kind.upper()}] {self.provider}  warte {self.wait_s}s  "
                f"→ {self.action}  (erkannt: {self.matched!r})")


# Reihenfolge zaehlt: CONTEXT vor QUOTA, weil "maximum context length exceeded"
# sonst als Kontingent durchginge und Stunden Wartezeit ausloest.
_SIGNATURES: tuple[tuple[str, str, re.Pattern], ...] = (
    ("anthropic", CONTEXT, re.compile(r"prompt is too long|maximum context", re.I)),
    ("openai", CONTEXT, re.compile(r"context[_ ]length[_ ]exceeded|too many tokens", re.I)),
    ("generisch", CONTEXT, re.compile(r"context (window|length).{0,20}(exceed|too)", re.I)),

    ("anthropic", QUOTA, re.compile(r"usage limit|credit balance is too low", re.I)),
    ("openai", QUOTA, re.compile(r"insufficient_quota|exceeded your current quota", re.I)),
    ("generisch", QUOTA, re.compile(r"quota (exceeded|reached)|kontingent", re.I)),
    ("generisch", QUOTA, re.compile(r"(daily|monthly) limit (reached|exceeded)", re.I)),

    ("anthropic", OVERLOAD, re.compile(r"overloaded_error|\boverloaded\b", re.I)),
    ("generisch", OVERLOAD, re.compile(r"\b(503|502)\b|service unavailable|capacity", re.I)),

    ("generisch", RATE, re.compile(r"rate[_ -]?limit", re.I)),
    ("generisch", RATE, re.compile(r"\b429\b|too many requests", re.I)),
    ("generisch", RATE, re.compile(r"limit (reached|erreicht)", re.I)),
)

# Nennt die Gegenstelle selbst eine Wartezeit, gilt sie -- sie weiss es besser.
_RETRY = (
    re.compile(r"retry[- _]?after[\"'\s:=]+(\d+)", re.I),
    re.compile(r"try again in (\d+)\s*(second|sekunde|minute|hour|stunde)", re.I),
    re.compile(r"in (\d+)\s*(minutes?|minuten|hours?|stunden)", re.I),
)
_UNIT_S = {"second": 1, "sekunde": 1, "minute": 60, "minuten": 60,
           "minutes": 60, "hour": 3600, "stunde": 3600, "hours": 3600,
           "stunden": 3600}


def extract_wait(text: str) -> int | None:
    for p in _RETRY:
        m = p.search(text)
        if not m:
            continue
        n = int(m.group(1))
        unit = m.group(2).lower() if m.lastindex and m.lastindex >= 2 else "second"
        return n * _UNIT_S.get(unit, 1)
    return None


def parse(text: str, provider: str = "") -> LimitSignal | None:
    """Text -> Signal, oder None wenn kein Limit erkennbar ist.

    None heisst 'kein Limit erkannt', nicht 'alles in Ordnung'. Wer nur auf
    None prueft, verwechselt beides -- deshalb gibt es `UNKNOWN` fuer den
    Fall, dass etwas nach Limit riecht, aber kein Muster greift.
    """
    if not text or not text.strip():
        return None

    for prov, kind, pattern in _SIGNATURES:
        if provider and prov not in ("generisch", provider.lower()):
            continue
        m = pattern.search(text)
        if m:
            wait = extract_wait(text)
            i = max(0, m.start() - 30)
            return LimitSignal(
                kind=kind, provider=provider or prov, matched=m.group(0),
                wait_s=wait if wait is not None else DEFAULT_WAIT_S[kind],
                raw_excerpt=text[i:m.end() + 40].strip())

    # Riecht nach Limit, aber kein Muster greift: als UNKNOWN melden statt zu
    # schweigen. Ein stilles "kein Limit" ist der teure Fehler -- der Aufrufer
    # laeuft dann in dieselbe Wand.
    if re.search(r"\blimit\b|\bquota\b|throttl|\b42\d\b", text, re.I):
        return LimitSignal(UNKNOWN, provider or "unbekannt", "heuristisch",
                           DEFAULT_WAIT_S[UNKNOWN], text[:120].strip())
    return None


def is_limit(text: str, provider: str = "") -> bool:
    return parse(text, provider) is not None


__all__ = ["LimitSignal", "parse", "is_limit", "extract_wait",
           "OVERLOAD", "RATE", "QUOTA", "CONTEXT", "UNKNOWN",
           "DEFAULT_WAIT_S", "ACTION"]
