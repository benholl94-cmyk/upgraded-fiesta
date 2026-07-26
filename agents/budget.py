"""Kostenbremse für die Entwicklungsphase.

Solange das Projekt nichts einnimmt, darf es nichts kosten. Diese Regel steht
nicht als Vorsatz in einer Doku, sondern als Sperre im Ausführungspfad: ein
Aufruf an einen abrechnungspflichtigen Provider wird **abgelehnt**, nicht
protokolliert und trotzdem ausgeführt.

## Was das ist und was nicht

Das ist eine Selbstbeschränkung: das Repo bleibt freiwillig auf Providern,
die ohne Abrechnungsverhältnis nutzbar sind — genau so, wie deren Betreiber
sie anbieten.

Das ist **kein** Werkzeug, um Gebühren zu umgehen, Kontingente zu unterlaufen
oder Gratiskontingente über mehrere Konten zu strecken. Ein Provider mit
Abrechnung wird hier nicht billiger gemacht, sondern schlicht nicht
aufgerufen. Wer ihn braucht, hebt die Sperre bewusst auf und zahlt.

## Kostenklassen

    FREE      Ohne Konto oder mit dauerhaft kostenlosem Zugang nutzbar.
    METERED   Rechnet pro Token/Aufruf ab. In der Entwicklungsphase gesperrt.
    UNKNOWN   Nicht eingeordnet. Wird wie METERED behandelt — im Zweifel
              sperren, nicht durchlassen.

Die Voreinstellung für Unbekanntes ist der eigentliche Schutz. Eine
Kostenbremse, die bei unbekannten Providern durchlässt, bremst genau dann
nicht, wenn jemand einen neuen eingetragen hat.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE_FILE = REPO / "config" / "budget.json"

FREE = "free"
METERED = "metered"
UNKNOWN = "unknown"

# Einordnung der im Repo bekannten Provider. FREE heisst: nutzbar, ohne dass
# eine Rechnung entstehen kann -- nicht "hat ein Gratiskontingent".
COST_CLASS: dict[str, str] = {
    # keylos, ohne Konto
    "pollinations": FREE,
    "pollinations_r1": FREE,
    "openrouter_free": FREE,
    "hf_free": FREE,
    "featherless": FREE,
    "hf_router": FREE,
    "novita": FREE,
    "reflex": FREE,          # lokaler Offline-Kern
    "local": FREE,           # Ollama o.ae. auf eigener Hardware
    "loopback": FREE,        # Referenz-Adapter, kein Netz

    # rechnen ab
    "openai": METERED,
    "gemini": METERED,
    "mistral": METERED,
    "anthropic": METERED,
    "groq": METERED,
    "cohere": METERED,
    "together": METERED,
    "xai": METERED,
    "cerebras": METERED,
    "github_models": METERED,
}


class BudgetBlocked(RuntimeError):
    """Aufruf abgelehnt, weil er Kosten verursacht hätte."""


@dataclass
class Budget:
    """Zustand der Kostenbremse. Liegt in config/budget.json, ist getrackt —
    der Riegel soll im Diff sichtbar sein, wenn ihn jemand löst."""

    development_phase: bool = True
    allow_metered: bool = False
    unlock_reason: str = ""
    unlocked_at: str = ""
    monthly_cap_eur: float = 0.0

    @classmethod
    def load(cls, path: Path | None = None) -> Budget:
        p = path or STATE_FILE
        if not p.is_file():
            return cls()
        d = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            development_phase=bool(d.get("development_phase", True)),
            allow_metered=bool(d.get("allow_metered", False)),
            unlock_reason=str(d.get("unlock_reason", "")),
            unlocked_at=str(d.get("unlocked_at", "")),
            monthly_cap_eur=float(d.get("monthly_cap_eur", 0.0)),
        )

    def save(self, path: Path | None = None) -> None:
        p = path or STATE_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "schema": "hugin.budget.v1",
            "development_phase": self.development_phase,
            "allow_metered": self.allow_metered,
            "unlock_reason": self.unlock_reason,
            "unlocked_at": self.unlocked_at,
            "monthly_cap_eur": self.monthly_cap_eur,
            "_hinweis": "development_phase=true sperrt jeden abrechnungs"
                        "pflichtigen Provider. Loesen nur mit Begruendung.",
        }, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    @property
    def active(self) -> bool:
        """Bremst die Sperre gerade?"""
        return self.development_phase and not self.allow_metered


def cost_class(provider: str) -> str:
    """Unbekannt wird wie kostenpflichtig behandelt — im Zweifel sperren."""
    return COST_CLASS.get(provider.lower(), UNKNOWN)


def free_providers() -> tuple[str, ...]:
    return tuple(sorted(p for p, c in COST_CLASS.items() if c == FREE))


def check(provider: str, budget: Budget | None = None) -> None:
    """Wirft BudgetBlocked, wenn der Aufruf Kosten verursachen würde.

    Kein stilles Überspringen: der Aufrufer muss den Unterschied zwischen
    "hat nichts geliefert" und "durfte nicht" erkennen können.
    """
    b = budget or Budget.load()
    if not b.active:
        return
    klass = cost_class(provider)
    if klass == FREE:
        return
    why = ("ist nicht eingeordnet und wird deshalb wie kostenpflichtig behandelt"
           if klass == UNKNOWN else "rechnet pro Aufruf ab")
    raise BudgetBlocked(
        f"Provider {provider!r} {why}. Die Kostenbremse ist aktiv "
        f"(config/budget.json → development_phase).\n"
        f"Kostenlos verfuegbar: {', '.join(free_providers())}\n"
        f"Bewusst loesen: python3 -m agents budget unlock --reason \"...\" --yes"
    )


def allowed(providers: list[str] | tuple[str, ...],
            budget: Budget | None = None) -> tuple[list[str], list[str]]:
    """Teilt eine Providerliste in (erlaubt, gesperrt)."""
    b = budget or Budget.load()
    ok, blocked = [], []
    for p in providers:
        try:
            check(p, b)
            ok.append(p)
        except BudgetBlocked:
            blocked.append(p)
    return ok, blocked


def unlock(reason: str, budget: Budget | None = None,
           path: Path | None = None) -> Budget:
    """Sperre lösen. Verlangt eine Begründung, die im Repo sichtbar bleibt."""
    if not reason.strip():
        raise ValueError("Ein Loesen ohne Begruendung ist kein Loesen, "
                         "sondern ein Vergessen.")
    b = budget or Budget.load(path)
    b.allow_metered = True
    b.unlock_reason = reason.strip()
    b.unlocked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    b.save(path)
    return b


def relock(budget: Budget | None = None, path: Path | None = None) -> Budget:
    b = budget or Budget.load(path)
    b.allow_metered = False
    b.unlock_reason = ""
    b.unlocked_at = ""
    b.save(path)
    return b


def status_lines(budget: Budget | None = None) -> list[str]:
    b = budget or Budget.load()
    out = [
        f"Kostenbremse: {'AKTIV' if b.active else 'GELOEST'}",
        f"  Entwicklungsphase : {'ja' if b.development_phase else 'nein'}",
        f"  Abrechnung erlaubt: {'ja' if b.allow_metered else 'nein'}",
    ]
    if b.unlock_reason:
        out.append(f"  Geloest am {b.unlocked_at}: {b.unlock_reason}")
    free = free_providers()
    metered = sorted(p for p, c in COST_CLASS.items() if c == METERED)
    out += [
        f"  Kostenlos ({len(free)}): {', '.join(free)}",
        f"  Kostenpflichtig ({len(metered)}): {', '.join(metered)}",
        "  Unbekannte Provider werden wie kostenpflichtig behandelt.",
    ]
    if b.active:
        blocked_env = [e for e in ("HUGIN_OPENAI_KEY", "HUGIN_GEMINI_KEY",
                                   "HUGIN_MISTRAL_KEY") if os.environ.get(e)]
        if blocked_env:
            out.append(f"  Hinweis: {', '.join(blocked_env)} ist gesetzt, wird aber "
                       f"nicht genutzt, solange die Bremse aktiv ist.")
    return out


__all__ = ["Budget", "BudgetBlocked", "cost_class", "free_providers", "check",
           "allowed", "unlock", "relock", "status_lines",
           "FREE", "METERED", "UNKNOWN", "COST_CLASS"]
