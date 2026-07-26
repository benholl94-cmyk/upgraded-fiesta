"""Append-only Protokoll aller Agenten-Vorgaenge.

Warum eine eigene Datei statt Logging: die Verfassung verlangt
Nachvollziehbarkeit von Entscheidungen, und ein rotierendes Logfile ist kein
Gedaechtnis. Das Ledger ist JSONL, append-only, im Repo versionierbar --
jede Zeile ein Ereignis, nie eine Ueberschreibung.

Konflikte werden hier ausdruecklich mitgeschrieben. Ein Multi-Agent-Setup,
das Widersprueche zwischen den Agenten glaettet, verliert genau die
Information, wegen der man zwei Agenten einsetzt.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER_DIR = REPO / ".claude" / "agents"
LEDGER_FILE = LEDGER_DIR / "ledger.jsonl"

EVENTS = ("task.created", "task.dispatched", "task.result", "task.error",
          "patch.applied", "patch.rejected", "conflict.recorded")


@dataclass(frozen=True)
class Event:
    kind: str
    task_id: str
    payload: dict
    ts: str

    def to_json(self) -> str:
        return json.dumps({"ts": self.ts, "kind": self.kind,
                           "task_id": self.task_id, "payload": self.payload},
                          ensure_ascii=False, sort_keys=True)


class Ledger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else LEDGER_FILE

    def record(self, kind: str, task_id: str, payload: dict) -> Event:
        if kind not in EVENTS:
            raise ValueError(f"Ereignis {kind!r} unbekannt; erlaubt: {EVENTS}")
        ev = Event(kind=kind, task_id=task_id, payload=payload,
                   ts=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Append im Text-Modus ist auf POSIX fuer Zeilen < PIPE_BUF atomar
        # genug; ein Lock waere hier Theater, weil nur der Orchestrator
        # schreibt.
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(ev.to_json() + "\n")
        return ev

    def read(self, task_id: str | None = None) -> list[dict]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue                      # eine kaputte Zeile kippt nicht das Ledger
            if task_id is None or d.get("task_id") == task_id:
                out.append(d)
        return out

    def tasks(self) -> list[str]:
        seen, order = set(), []
        for d in self.read():
            t = d.get("task_id")
            if t and t not in seen:
                seen.add(t)
                order.append(t)
        return order

    def conflicts(self) -> list[dict]:
        return [d for d in self.read() if d.get("kind") == "conflict.recorded"]


def snapshot(path: Path, content: str) -> Path:
    """Datei vor dem Ueberschreiben sichern. Gibt den Backup-Pfad zurueck."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".bak", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return Path(tmp)


__all__ = ["Ledger", "Event", "EVENTS", "LEDGER_FILE", "snapshot"]
