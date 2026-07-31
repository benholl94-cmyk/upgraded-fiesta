#!/usr/bin/env python3
"""auto_rollback.py — Entscheidet, ob ein Commit auf main zurückgenommen wird.

Zweck: `main` bleibt jederzeit lauffähig, ohne dass jemand nachts eingreift.
Bricht ein Commit die CI, nimmt der Workflow ihn zurück, statt den Branch
kaputt liegen zu lassen.

## Warum die Entscheidung hier liegt und nicht im YAML

Ein Rollback, das falsch auslöst, richtet mehr Schaden an als der Fehler, den
es beheben soll — es kann gute Arbeit verwerfen oder sich in eine Schleife
revertieren. Die Logik gehört deshalb in eine reine Funktion, die man testen
kann, nicht in Shell-Zeilen eines Workflows, die man nur im Ernstfall sieht.

## Die vier Sperren

1. **Kein Revert eines Reverts.** Sonst entsteht eine Endlosschleife aus
   Rücknahme und Rücknahme der Rücknahme.
2. **Kein Revert, wenn der Vorgänger nicht nachweislich unbedenklich war.**
   Wiederverwendet die Conclusio-Allowlist aus `auto_rollback_ctx.py` (dort
   die einzige Quelle für „was heißt dieser CI-Status"): nur ein Vorgänger,
   den die Allowlist als `NOOP` einstuft (`success`/`skipped`/`neutral`),
   gilt als sicher. `unknown`, `cancelled`, `timed_out` und jeder andere
   nicht als `NOOP` eingestufte Status werden nie wie ein sicherer Vorgänger
   behandelt — sonst liegt der Bruch womöglich nicht an diesem Commit, oder
   es ist schlicht nicht feststellbar, und die Rücknahme verwirft Arbeit
   statt zu heilen.
3. **Sicherung (Circuit Breaker).** Mehr als `MAX_REVERTS_PER_WINDOW`
   Rücknahmen im Zeitfenster heisst: etwas Grundsätzlicheres ist kaputt.
   Dann hält das System an und meldet, statt weiter zu revertieren.
4. **Nur ganze Merge-/Squash-Commits.** Einzelne Commits innerhalb eines
   Merges zurückzunehmen hinterlässt einen Zwischenzustand, den niemand
   geprüft hat.

Fällt eine Sperre, ist das Ergebnis `HOLD` mit Begründung — nie stilles
Nichtstun.

    python3 scripts/auto_rollback.py decide --json '<kontext>'
    python3 scripts/auto_rollback.py explain
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# Dynamisch geladen statt `import auto_rollback_ctx`, damit dieses Skript
# unveraendert laeuft, egal von wo es aufgerufen wird (der Workflow ruft es
# als `python3 scripts/auto_rollback.py ...` vom Repo-Root, nicht als
# Paket) -- gleiche Technik wie in tests/test_auto_rollback.py.
_CTX_PATH = pathlib.Path(__file__).resolve().parent / "auto_rollback_ctx.py"
_CTX_SPEC = importlib.util.spec_from_file_location("auto_rollback_ctx", _CTX_PATH)
_ctx = importlib.util.module_from_spec(_CTX_SPEC)
_CTX_SPEC.loader.exec_module(_ctx)

REVERT = "REVERT"
HOLD = "HOLD"
NOOP = "NOOP"

MAX_REVERTS_PER_WINDOW = 2
WINDOW_HOURS = 6

_REVERT_SUBJECT = re.compile(r'^\s*Revert\s+"', re.IGNORECASE)
_MERGE_SUBJECT = re.compile(r"\(#\d+\)\s*$|^Merge pull request #\d+", re.IGNORECASE)


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    sha: str = ""

    @property
    def should_revert(self) -> bool:
        return self.action == REVERT

    def to_dict(self) -> dict:
        return {"action": self.action, "reason": self.reason, "sha": self.sha}

    def __str__(self) -> str:
        return f"[{self.action}] {self.sha[:7] + ' ' if self.sha else ''}{self.reason}"


@dataclass(frozen=True)
class Context:
    """Alles, was die Entscheidung braucht. Bewusst als Datenobjekt, damit
    der Workflow nur einsammelt und diese Datei allein entscheidet."""

    sha: str
    subject: str
    branch: str
    conclusion: str                      # success | failure | cancelled | ...
    previous_conclusion: str = "unknown"  # CI-Ergebnis des Vorgaengercommits
    recent_reverts: tuple[str, ...] = ()  # ISO-Zeitstempel bisheriger Reverts
    now: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> Context:
        return cls(
            sha=str(d.get("sha", "")),
            subject=str(d.get("subject", "")),
            branch=str(d.get("branch", "")),
            conclusion=str(d.get("conclusion", "")),
            previous_conclusion=str(d.get("previous_conclusion", "unknown")),
            recent_reverts=tuple(d.get("recent_reverts", ())),
            now=str(d.get("now", "")),
        )


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def decide(ctx: Context) -> Decision:
    """Reine Entscheidung. Kein Netz, kein git, keine Nebenwirkung."""
    if ctx.branch != "main":
        return Decision(NOOP, f"Branch {ctx.branch!r} ist nicht main", ctx.sha)

    if ctx.conclusion != "failure":
        return Decision(NOOP, f"CI-Ergebnis {ctx.conclusion!r}, kein Bruch", ctx.sha)

    if not ctx.sha:
        return Decision(HOLD, "Kein Commit-SHA im Kontext — nichts identifizierbar")

    # Sperre 1 -- Schleifenschutz
    if _REVERT_SUBJECT.match(ctx.subject):
        return Decision(
            HOLD,
            "Der fehlschlagende Commit ist selbst eine Ruecknahme. Ein weiterer "
            "Revert erzeugt eine Endlosschleife; hier muss ein Mensch schauen.",
            ctx.sha)

    # Sperre 2 -- war der Vorgaenger nachweislich unbedenklich?
    #
    # Wiederverwendet auto_rollback_ctx.ALLOWLIST statt eine eigene,
    # zwangslaeufig abweichende Liste zu fuehren: previous_conclusion gilt
    # nur dann als sicher, wenn die geteilte Allowlist ihn als NOOP einstuft
    # (success/skipped/neutral). Alles, was die Allowlist als REVERT
    # (failure) oder HOLD (cancelled/timed_out/action_required/
    # startup_failure/stale/unbekannt) einstuft, blockiert auch hier. Eine
    # eigene Blockliste auf '== "failure"' liess 'unknown' durchrutschen und
    # hat den einfuehrenden Merge-Commit dieses Moduls selbst revertiert.
    prev_action = _ctx.decide(ctx.previous_conclusion)
    if prev_action != NOOP:
        return Decision(
            HOLD,
            f"Vorgaengercommit-Status ist {ctx.previous_conclusion!r} "
            f"(Allowlist-Einstufung {prev_action!r}, nicht NOOP). Ein "
            "unbestimmter oder nicht nachweislich unbedenklicher Vorgaenger "
            "darf nie wie ein sicherer behandelt werden — der Bruch koennte "
            "am Vorgaenger liegen, oder es ist schlicht nicht feststellbar, "
            "ob die Ruecknahme heilt statt Arbeit zu verwerfen.",
            ctx.sha)

    # Sperre 3 -- Sicherung
    now = _parse(ctx.now) or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=WINDOW_HOURS)
    recent = [t for t in (_parse(x) for x in ctx.recent_reverts) if t and t >= cutoff]
    if len(recent) >= MAX_REVERTS_PER_WINDOW:
        return Decision(
            HOLD,
            f"{len(recent)} Ruecknahmen in {WINDOW_HOURS}h — die Sicherung haelt. "
            "Wiederholte Rollbacks heissen, dass etwas Grundsaetzlicheres kaputt "
            "ist als der letzte Commit.",
            ctx.sha)

    # Sperre 4 -- nur ganze Merges
    if not _MERGE_SUBJECT.search(ctx.subject):
        return Decision(
            HOLD,
            "Kein Merge-/Squash-Commit. Einen Einzelcommit aus einem Merge "
            "zurueckzunehmen hinterlaesst einen Zwischenstand, den niemand "
            "geprueft hat.",
            ctx.sha)

    return Decision(
        REVERT,
        "CI rot, Vorgaenger gruen, kein Revert, Sicherung offen, ganzer "
        "Merge-Commit — Ruecknahme ist sicher.",
        ctx.sha)


def cmd_decide(a: argparse.Namespace) -> int:
    raw = json.loads(a.json if a.json != "-" else sys.stdin.read())
    d = decide(Context.from_dict(raw))
    print(json.dumps(d.to_dict(), ensure_ascii=False) if a.machine else str(d))
    return 0 if d.should_revert else 1


def cmd_explain(_a: argparse.Namespace) -> int:
    print(__doc__)
    print(f"MAX_REVERTS_PER_WINDOW = {MAX_REVERTS_PER_WINDOW} in {WINDOW_HOURS}h")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decide", help="Kontext als JSON bewerten")
    d.add_argument("--json", default="-", help="JSON-String oder '-' fuer stdin")
    d.add_argument("--machine", action="store_true", help="JSON ausgeben")
    d.set_defaults(func=cmd_decide)
    e = sub.add_parser("explain", help="Regeln anzeigen")
    e.set_defaults(func=cmd_explain)
    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
