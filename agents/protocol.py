"""Wire-Format zwischen Orchestrator (Claude) und ausführendem Agenten (Codex).

Das Format ist bewusst eng: ein Agent, der irgendetwas zurückgeben darf, ist
nicht integrierbar. Jede Antwort ist entweder ein valides `AgentResult` oder
ein Fehler -- es gibt keinen dritten Zustand, in dem "irgendwie schon was
zurückkam" als Erfolg durchgeht.

Serialisierung ist deterministisch (sortierte Keys, feste Trennzeichen), damit
Aufgaben und Ergebnisse versionierbar und diffbar im Repo liegen können.

Sicherheitsrelevant: `AgentTask.context_files` ist eine **explizite Liste**.
Es gibt bewusst keinen Glob und kein "nimm das Repo" -- die Verfassung stellt
externe Provider unter Zero Trust (`constitution.json` → 4_ExternalProviders),
also muss jede Datei, die das Gerät verlässt, einzeln benannt und im Ledger
nachlesbar sein.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PROTOCOL_VERSION = "agents.protocol.v1"

TASK_KINDS = ("implement", "fix", "refactor", "test", "review", "explain")
RESULT_STATUS = ("ok", "partial", "refused", "error")
PATCH_ACTIONS = ("create", "replace")


class ProtocolError(ValueError):
    """Antwort oder Aufgabe verletzt das Format. Immer laut, nie stillschweigend."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FileContext:
    """Eine Datei, die dem Agenten gezeigt wird. Hash macht nachprüfbar,
    welcher Stand gesendet wurde."""

    path: str
    content: str

    @property
    def sha(self) -> str:
        return sha256(self.content)

    def to_dict(self) -> dict:
        return {"path": self.path, "sha256": self.sha, "bytes": len(self.content)}


@dataclass(frozen=True)
class AgentTask:
    id: str
    kind: str
    instruction: str
    context_files: tuple[FileContext, ...] = ()
    constraints: tuple[str, ...] = ()
    created_at: str = field(default_factory=_now)
    protocol: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.kind not in TASK_KINDS:
            raise ProtocolError(f"kind {self.kind!r} unbekannt; erlaubt: {TASK_KINDS}")
        if not self.instruction.strip():
            raise ProtocolError("instruction darf nicht leer sein")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", self.id):
            raise ProtocolError(f"id {self.id!r} verletzt [a-z0-9._-]{{3,64}}")

    @property
    def context_bytes(self) -> int:
        return sum(len(f.content) for f in self.context_files)

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "id": self.id,
            "kind": self.kind,
            "instruction": self.instruction,
            "constraints": list(self.constraints),
            "context_files": [f.to_dict() for f in self.context_files],
            "created_at": self.created_at,
        }

    def render_prompt(self) -> str:
        """Der Text, den der ausführende Agent sieht.

        Enthält das geforderte Antwortschema wörtlich -- ein Agent, der das
        Schema nicht kennt, kann es nicht einhalten, und ein Parser, der rät,
        ist kein Protokoll.
        """
        parts = [
            f"AUFGABE ({self.kind}) — id={self.id}",
            "",
            self.instruction.strip(),
        ]
        if self.constraints:
            parts += ["", "HARTE VORGABEN:"]
            parts += [f"- {c}" for c in self.constraints]
        for f in self.context_files:
            parts += ["", f"--- DATEI: {f.path} ---", f.content.rstrip()]
        parts += [
            "",
            "ANTWORTFORMAT — ausschliesslich ein JSON-Objekt, optional in einem",
            "```json-Block. Kein Fliesstext davor oder danach.",
            json.dumps({
                "task_id": self.id,
                "status": "ok | partial | refused | error",
                "patches": [{"path": "pfad/zur/datei", "action": "create | replace",
                             "content": "vollstaendiger neuer Dateiinhalt",
                             "rationale": "warum"}],
                "notes": "kurze Zusammenfassung",
                "conflicts": ["Widerspruch zur Aufgabe, falls vorhanden"],
            }, indent=2, ensure_ascii=False),
        ]
        return "\n".join(parts)


@dataclass(frozen=True)
class AgentPatch:
    path: str
    action: str
    content: str
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.action not in PATCH_ACTIONS:
            raise ProtocolError(f"action {self.action!r}; erlaubt: {PATCH_ACTIONS}")
        p = Path(self.path)
        if p.is_absolute() or ".." in p.parts:
            raise ProtocolError(f"Pfad {self.path!r} verlaesst das Repo")
        if not self.path.strip():
            raise ProtocolError("Patch ohne Pfad")

    @property
    def sha(self) -> str:
        return sha256(self.content)


@dataclass(frozen=True)
class AgentResult:
    task_id: str
    agent: str
    status: str
    patches: tuple[AgentPatch, ...] = ()
    notes: str = ""
    conflicts: tuple[str, ...] = ()
    raw: str = ""
    finished_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.status not in RESULT_STATUS:
            raise ProtocolError(f"status {self.status!r}; erlaubt: {RESULT_STATUS}")

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "partial")

    def to_dict(self, include_raw: bool = False) -> dict:
        d = {
            "protocol": PROTOCOL_VERSION,
            "task_id": self.task_id,
            "agent": self.agent,
            "status": self.status,
            "notes": self.notes,
            "conflicts": list(self.conflicts),
            "patches": [{"path": p.path, "action": p.action,
                         "sha256": p.sha, "bytes": len(p.content),
                         "rationale": p.rationale} for p in self.patches],
            "finished_at": self.finished_at,
        }
        if include_raw:
            d["raw"] = self.raw
        return d


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_result(raw: str, task: AgentTask, agent: str) -> AgentResult:
    """Rohtext eines Agenten -> AgentResult. Wirft ProtocolError statt zu raten.

    Akzeptiert das JSON blank oder in einem ```json-Block, weil Sprachmodelle
    fast immer einrahmen. Alles andere ist ein Formatfehler, kein Sonderfall,
    der stillschweigend geheilt wird.
    """
    text = raw.strip()
    if not text:
        raise ProtocolError("leere Antwort")

    payload = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_FENCE.search(text)
        if m:
            try:
                payload = json.loads(m.group(1))
            except json.JSONDecodeError as exc:
                raise ProtocolError(f"JSON im Codeblock ist ungueltig: {exc}") from exc
    if payload is None:
        raise ProtocolError("Antwort enthaelt kein JSON-Objekt")
    if not isinstance(payload, dict):
        raise ProtocolError(f"Antwort ist {type(payload).__name__}, erwartet Objekt")

    got_id = payload.get("task_id")
    if got_id != task.id:
        raise ProtocolError(f"task_id {got_id!r} passt nicht zu {task.id!r}")

    status = payload.get("status", "error")
    if status not in RESULT_STATUS:
        raise ProtocolError(f"status {status!r} unbekannt")

    patches = []
    for i, p in enumerate(payload.get("patches") or []):
        if not isinstance(p, dict):
            raise ProtocolError(f"patches[{i}] ist kein Objekt")
        try:
            patches.append(AgentPatch(
                path=str(p["path"]), action=str(p.get("action", "replace")),
                content=str(p["content"]), rationale=str(p.get("rationale", "")),
            ))
        except KeyError as exc:
            raise ProtocolError(f"patches[{i}] fehlt Feld {exc}") from exc

    if status == "ok" and not patches and task.kind in ("implement", "fix", "refactor"):
        raise ProtocolError(
            f"status=ok ohne Patch bei kind={task.kind} — "
            "ein Erfolg ohne Ergebnis ist kein Erfolg")

    conflicts = tuple(str(c) for c in (payload.get("conflicts") or []))
    return AgentResult(
        task_id=task.id, agent=agent, status=status, patches=tuple(patches),
        notes=str(payload.get("notes", "")), conflicts=conflicts, raw=raw,
    )


def dumps(obj: dict) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)


__all__ = [
    "PROTOCOL_VERSION", "TASK_KINDS", "RESULT_STATUS", "PATCH_ACTIONS",
    "ProtocolError", "FileContext", "AgentTask", "AgentPatch", "AgentResult",
    "parse_result", "sha256", "dumps", "asdict",
]
