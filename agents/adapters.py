"""Adapter: ein Agent, eine Schnittstelle.

Jeder Adapter implementiert `execute(task) -> AgentResult`. Der Orchestrator
kennt nur diese Signatur, nie einen Provider. Ein Providerwechsel ist damit
ein Eintrag in `config/agents.json`, kein Refactor.

Verifikationsgrad -- steht bewusst als Feld am Adapter, nicht nur in der Doku:

    VERIFIED = True    gegen die echte Gegenstelle ausgefuehrt
    VERIFIED = False   Code vollstaendig, Gegenstelle nie erreicht

`OracleCodexAdapter` ist VERIFIED = False. Er ist fertig implementiert, aber
in dieser Umgebung liegt kein OpenAI-Key, also wurde nie eine echte Antwort
von Codex durch dieses Modul geparst. Das als "integriert" zu verkaufen waere
genau die Pseudoloesung, die der Auftrag ausschliesst.
"""

from __future__ import annotations

import abc
import importlib.util
import subprocess
import sys
from pathlib import Path

from .protocol import AgentPatch, AgentResult, AgentTask, ProtocolError, parse_result

REPO = Path(__file__).resolve().parent.parent
ORACLE = REPO / "scripts" / "hugin_oracle.py"

# Skill-Scope im Oracle-Gate, unter dem Patch-Aufgaben laufen. Muss dort
# existieren -- siehe scripts/hugin_oracle.py → SKILL_SCOPES.
CODEX_SKILL = "codex-patch"


class AdapterError(RuntimeError):
    """Adapter konnte die Aufgabe nicht ausfuehren (Transport, Auth, Timeout)."""


class AgentAdapter(abc.ABC):
    name: str = "base"
    role: str = ""
    VERIFIED: bool = False

    @abc.abstractmethod
    def execute(self, task: AgentTask) -> AgentResult: ...

    def available(self) -> tuple[bool, str]:
        """(einsatzbereit, Begruendung). Nie raten -- wenn ein Key fehlt,
        sagt der Adapter das, statt beim ersten Aufruf zu explodieren."""
        return True, "bereit"


# ---------------------------------------------------------------------------
# Referenz-Adapter: beweist den Datenfluss ohne externe Gegenstelle
# ---------------------------------------------------------------------------

class LoopbackAdapter(AgentAdapter):
    """Deterministischer Referenz-Agent -- **kein Sprachmodell und keine
    Codex-Simulation.**

    Er erzeugt mechanisch ein schemakonformes Ergebnis aus der Aufgabe. Sein
    Zweck ist, Protokoll, Orchestrator, Ledger und CI ohne Netz und ohne Key
    end-to-end pruefbar zu machen. Er schreibt keinen Code und behauptet
    nicht, welchen zu schreiben: bei Patch-Aufgaben antwortet er `refused`
    mit klarer Begruendung.
    """

    name = "loopback"
    role = "reference"
    VERIFIED = True     # gegen die eigene Gegenstelle -- er IST die Gegenstelle

    def execute(self, task: AgentTask) -> AgentResult:
        if task.kind in ("implement", "fix", "refactor"):
            return AgentResult(
                task_id=task.id, agent=self.name, status="refused",
                notes="LoopbackAdapter erzeugt grundsaetzlich keinen Code. "
                      "Fuer Patch-Aufgaben einen Agenten mit echter "
                      "Codegenerierung konfigurieren (config/agents.json).",
                conflicts=(f"kind={task.kind} verlangt Codegenerierung, "
                           f"Adapter {self.name!r} leistet sie nicht",),
                raw="",
            )
        summary = (f"{task.kind}: {len(task.context_files)} Datei(en), "
                   f"{task.context_bytes} Zeichen Kontext.")
        return AgentResult(task_id=task.id, agent=self.name, status="ok",
                           notes=summary, raw="")


# ---------------------------------------------------------------------------
# Codex ueber das Oracle-Gate
# ---------------------------------------------------------------------------

def _load_oracle():
    """hugin_oracle.py als Modul laden.

    Import statt Subprozess, damit Ausnahmen und der Audit-Log-Pfad erhalten
    bleiben. Der Fallback auf die CLI existiert, weil das Skript nicht als
    Paket installiert ist und der Import je nach Aufrufort scheitern kann.
    """
    if not ORACLE.is_file():
        raise AdapterError(f"Oracle-Gate fehlt: {ORACLE}")
    spec = importlib.util.spec_from_file_location("hugin_oracle", ORACLE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("hugin_oracle", mod)
    spec.loader.exec_module(mod)
    return mod


class OracleCodexAdapter(AgentAdapter):
    """ChatGPT-Codex, erreichbar ausschliesslich ueber `scripts/hugin_oracle.py`.

    Der direkte Weg zur OpenAI-API waere kuerzer und ist bewusst nicht gebaut:
    CLAUDE.md schreibt vor, dass **alle** externen Provider-Calls durch das
    Gate laufen. Damit greifen Prompt-Sanitizing, Response-Redaktion,
    Laengengrenzen und der Audit-Log automatisch auch fuer diesen Agenten.

    VERIFIED = False -- siehe Modul-Docstring.
    """

    name = "codex"
    role = "executor"
    VERIFIED = False

    def __init__(self, provider: str = "openai", skill: str = CODEX_SKILL,
                 timeout: int = 120) -> None:
        self.provider = provider
        self.skill = skill
        self.timeout = timeout

    def available(self) -> tuple[bool, str]:
        try:
            oracle = _load_oracle()
        except AdapterError as exc:
            return False, str(exc)
        if self.skill not in getattr(oracle, "SKILL_SCOPES", {}):
            return False, (f"Skill-Scope {self.skill!r} fehlt in hugin_oracle.py — "
                           "ohne Scope lehnt das Gate jeden Aufruf ab")
        if self.provider not in getattr(oracle, "PROVIDERS", {}):
            return False, f"Provider {self.provider!r} im Oracle unbekannt"
        adapter = oracle.PROVIDERS[self.provider]
        import os
        if not os.environ.get(adapter.env_key, ""):
            return False, (f"${adapter.env_key} nicht gesetzt — "
                           f"lokal setzen, niemals committen")
        return True, "bereit"

    def execute(self, task: AgentTask) -> AgentResult:
        ok, why = self.available()
        if not ok:
            raise AdapterError(why)
        oracle = _load_oracle()
        try:
            raw = oracle.GATE.query(self.provider, self.skill, task.render_prompt())
        except Exception as exc:                       # Gate-Ablehnung, HTTP, Timeout
            raise AdapterError(f"Oracle-Gate: {exc}") from exc
        return parse_result(raw, task, self.name)


# ---------------------------------------------------------------------------
# Codex CLI (lokal installiert), falls vorhanden
# ---------------------------------------------------------------------------

class CodexCliAdapter(AgentAdapter):
    """Codex ueber eine lokal installierte `codex`-CLI.

    Zweiter Weg fuer den Fall, dass der Operator die CLI hat statt eines
    API-Keys. VERIFIED = False: in dieser Umgebung ist keine `codex`-CLI
    installiert, der Pfad wurde nie ausgefuehrt.
    """

    name = "codex-cli"
    role = "executor"
    VERIFIED = False

    def __init__(self, binary: str = "codex", timeout: int = 300) -> None:
        self.binary = binary
        self.timeout = timeout

    def available(self) -> tuple[bool, str]:
        from shutil import which
        if which(self.binary) is None:
            return False, f"{self.binary!r} nicht im PATH"
        return True, "bereit"

    def execute(self, task: AgentTask) -> AgentResult:
        ok, why = self.available()
        if not ok:
            raise AdapterError(why)
        try:
            proc = subprocess.run(
                [self.binary, "exec", "--json", "-"],
                input=task.render_prompt(), capture_output=True,
                text=True, timeout=self.timeout, cwd=REPO,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(f"{self.binary} Timeout nach {self.timeout}s") from exc
        if proc.returncode != 0:
            raise AdapterError(f"{self.binary} exit {proc.returncode}: "
                               f"{proc.stderr.strip()[:300]}")
        return parse_result(proc.stdout, task, self.name)


ADAPTERS: dict[str, type[AgentAdapter]] = {
    "loopback": LoopbackAdapter,
    "oracle-codex": OracleCodexAdapter,
    "codex-cli": CodexCliAdapter,
}


def build(kind: str, **kw) -> AgentAdapter:
    if kind not in ADAPTERS:
        raise AdapterError(f"Adapter {kind!r} unbekannt; erlaubt: {sorted(ADAPTERS)}")
    return ADAPTERS[kind](**kw)


__all__ = ["AgentAdapter", "AdapterError", "LoopbackAdapter", "OracleCodexAdapter",
           "CodexCliAdapter", "ADAPTERS", "build", "CODEX_SKILL", "AgentPatch",
           "ProtocolError"]
