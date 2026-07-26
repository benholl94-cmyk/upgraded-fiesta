"""Multi-Agent-Schicht: Orchestrator (Claude) + ausfuehrender Agent (Codex).

Konfiguration in `config/agents.json`, Protokoll in `protocol.py`, Adapter in
`adapters.py`, Ausfuehrung in `orchestrator.py`, Nachweis in `ledger.py`.

Verifikationsgrad je Adapter steht als `VERIFIED`-Feld an der Klasse --
`agents status` zeigt ihn an. Nichts hier behauptet eine Faehigkeit, die
nicht ausgefuehrt wurde.
"""

from .adapters import AdapterError, AgentAdapter, build
from .ledger import Ledger
from .orchestrator import Orchestrator, OrchestratorError
from .protocol import (
    AgentPatch, AgentResult, AgentTask, FileContext, ProtocolError, parse_result,
)

__all__ = [
    "AgentTask", "AgentResult", "AgentPatch", "FileContext", "ProtocolError",
    "parse_result", "AgentAdapter", "AdapterError", "build",
    "Orchestrator", "OrchestratorError", "Ledger",
]
