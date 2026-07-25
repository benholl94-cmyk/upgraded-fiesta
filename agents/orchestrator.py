"""Orchestrator -- die Claude-Seite der Multi-Agent-Architektur.

Rollentrennung (config/agents.json ist die Quelle, nicht dieser Docstring):

    Claude       Orchestrierung, Review, Architektur, Sicherheitspruefung.
                 Entscheidet, WAS gefragt wird und OB ein Ergebnis angewendet
                 wird. Schreibt selbst keine Patches ueber diesen Weg.

    Codex        Codegenerierung, Aufgabenbearbeitung, Patch-Erstellung.
                 Bekommt strukturierte Aufgaben, liefert strukturierte
                 Ergebnisse. Hat keinen Schreibzugriff auf das Repo -- Patches
                 sind Vorschlaege, bis der Orchestrator sie anwendet.

Das Anwenden von Patches schreibt echte Dateien. Dafuer gilt die im Repo
etablierte Regel (siehe `ghm_core.cli.cmd_report_diagnostics`): offenlegen,
was passiert, und ohne explizite Zustimmung laut verweigern statt still zu
handeln oder still nichts zu tun.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import adapters as _adapters
from .ledger import Ledger, snapshot
from .protocol import AgentResult, AgentTask, FileContext, ProtocolError

REPO = Path(__file__).resolve().parent.parent
CONFIG_FILE = REPO / "config" / "agents.json"


class OrchestratorError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentSpec:
    id: str
    adapter: str
    role: str
    responsibilities: tuple[str, ...]
    options: dict
    enabled: bool = True


def load_config(path: Path | None = None) -> dict[str, AgentSpec]:
    p = Path(path) if path else CONFIG_FILE
    if not p.is_file():
        raise OrchestratorError(f"Agenten-Konfiguration fehlt: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, AgentSpec] = {}
    for entry in raw.get("agents", []):
        try:
            spec = AgentSpec(
                id=entry["id"], adapter=entry["adapter"], role=entry["role"],
                responsibilities=tuple(entry.get("responsibilities", ())),
                options=dict(entry.get("options", {})),
                enabled=bool(entry.get("enabled", True)),
            )
        except KeyError as exc:
            raise OrchestratorError(f"Agent-Eintrag ohne Feld {exc}") from exc
        out[spec.id] = spec
    if not out:
        raise OrchestratorError(f"{p} enthaelt keine Agenten")
    return out


class Orchestrator:
    def __init__(self, config: Path | None = None, ledger: Ledger | None = None,
                 repo: Path | None = None) -> None:
        self.specs = load_config(config)
        self.ledger = ledger or Ledger()
        self.repo = Path(repo) if repo else REPO

    # -- Aufgaben -------------------------------------------------------
    def build_task(self, task_id: str, kind: str, instruction: str,
                   files: tuple[str, ...] = (), constraints: tuple[str, ...] = ()) -> AgentTask:
        """Aufgabe bauen. `files` ist eine explizite Liste -- kein Glob.

        Jede Datei, die hier landet, verlaesst potenziell das Geraet. Die
        Verfassung stellt externe Provider unter Zero Trust, also wird der
        Umfang benannt und im Ledger festgehalten, nie erraten.
        """
        ctx = []
        for rel in files:
            f = (self.repo / rel).resolve()
            if not str(f).startswith(str(self.repo.resolve())):
                raise OrchestratorError(f"{rel!r} liegt ausserhalb des Repos")
            if not f.is_file():
                raise OrchestratorError(f"Kontextdatei fehlt: {rel}")
            ctx.append(FileContext(path=rel, content=f.read_text(encoding="utf-8",
                                                                 errors="replace")))
        task = AgentTask(id=task_id, kind=kind, instruction=instruction,
                         context_files=tuple(ctx), constraints=constraints)
        self.ledger.record("task.created", task.id, task.to_dict())
        return task

    # -- Ausfuehrung ----------------------------------------------------
    def adapter_for(self, agent_id: str) -> _adapters.AgentAdapter:
        spec = self.specs.get(agent_id)
        if spec is None:
            raise OrchestratorError(f"Agent {agent_id!r} nicht konfiguriert; "
                                    f"bekannt: {sorted(self.specs)}")
        if not spec.enabled:
            raise OrchestratorError(f"Agent {agent_id!r} ist deaktiviert")
        return _adapters.build(spec.adapter, **spec.options)

    def dispatch(self, task: AgentTask, agent_id: str) -> AgentResult:
        adapter = self.adapter_for(agent_id)
        ok, why = adapter.available()
        if not ok:
            self.ledger.record("task.error", task.id,
                               {"agent": agent_id, "reason": why})
            raise OrchestratorError(f"Agent {agent_id!r} nicht einsatzbereit: {why}")

        self.ledger.record("task.dispatched", task.id, {
            "agent": agent_id, "adapter": spec_name(adapter),
            "verified": adapter.VERIFIED,
            "context_files": [f.path for f in task.context_files],
            "context_bytes": task.context_bytes,
        })
        try:
            result = adapter.execute(task)
        except (_adapters.AdapterError, ProtocolError) as exc:
            self.ledger.record("task.error", task.id,
                               {"agent": agent_id, "error": str(exc)})
            raise OrchestratorError(str(exc)) from exc

        self.ledger.record("task.result", task.id, result.to_dict())
        for c in result.conflicts:
            # Konflikte werden nicht geglaettet -- sie sind das Signal, dass
            # die Agenten sich uneinig sind, und genau dafuer gibt es zwei.
            self.ledger.record("conflict.recorded", task.id,
                               {"agent": agent_id, "conflict": c})
        return result

    # -- Anwenden -------------------------------------------------------
    def describe_apply(self, result: AgentResult) -> str:
        if not result.patches:
            return "Keine Patches — nichts anzuwenden."
        lines = [f"{len(result.patches)} Patch(es) von Agent {result.agent!r}:"]
        for p in result.patches:
            target = self.repo / p.path
            state = "neu" if not target.exists() else f"ueberschreibt {target.stat().st_size} B"
            lines.append(f"  {p.action:8} {p.path}  ({len(p.content)} B, {state})")
            if p.rationale:
                lines.append(f"           ↳ {p.rationale}")
        return "\n".join(lines)

    def apply(self, result: AgentResult, consent: bool) -> list[str]:
        """Patches schreiben. Ohne `consent` wird laut verweigert.

        Kein stilles No-Op: der Aufrufer muss den Unterschied zwischen
        "nichts zu tun" und "durfte nicht" am Rueckgabewert bzw. an der
        Ausnahme erkennen koennen.
        """
        if not result.ok:
            raise OrchestratorError(
                f"Ergebnis hat status={result.status} — wird nicht angewendet")
        if not result.patches:
            return []
        if not consent:
            self.ledger.record("patch.rejected", result.task_id,
                               {"agent": result.agent, "reason": "keine Zustimmung"})
            raise OrchestratorError(
                "Zustimmung fehlt. Patches wuerden echte Dateien ueberschreiben.\n"
                + self.describe_apply(result))

        written: list[str] = []
        for p in result.patches:
            target = (self.repo / p.path).resolve()
            if not str(target).startswith(str(self.repo.resolve())):
                raise OrchestratorError(f"Patch verlaesst das Repo: {p.path}")
            backup = None
            if target.exists():
                backup = snapshot(target, target.read_text(encoding="utf-8",
                                                           errors="replace"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(p.content, encoding="utf-8")
            written.append(p.path)
            self.ledger.record("patch.applied", result.task_id, {
                "agent": result.agent, "path": p.path, "sha256": p.sha,
                "backup": str(backup.relative_to(self.repo)) if backup else None,
            })
        return written

    def status(self) -> list[dict]:
        out = []
        for spec in self.specs.values():
            try:
                adapter = _adapters.build(spec.adapter, **spec.options)
                ok, why = adapter.available()
                verified = adapter.VERIFIED
            except _adapters.AdapterError as exc:
                ok, why, verified = False, str(exc), False
            out.append({"id": spec.id, "role": spec.role, "adapter": spec.adapter,
                        "enabled": spec.enabled, "available": ok, "reason": why,
                        "verified": verified,
                        "responsibilities": list(spec.responsibilities)})
        return out


def spec_name(adapter: _adapters.AgentAdapter) -> str:
    return getattr(adapter, "name", adapter.__class__.__name__)


__all__ = ["Orchestrator", "OrchestratorError", "AgentSpec", "load_config"]
