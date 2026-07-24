#!/usr/bin/env python3
"""
Claude-Tool-Plugin — Claude als Subroutinen-Werkzeug für Ollama.

Claude wird hier NICHT als Entscheider genutzt sondern als präzises
Werkzeug für Code-Generierung, technische Analysen und Research.
Ollama orchestriert, Claude liefert spezifische Teilleistungen.

Plugin-Protokoll: eine JSON-Zeile auf stdin → eine JSON-Zeile auf stdout.

Env-Vars:
  ANTHROPIC_API_KEY   Claude-API-Key (via hugin_oracle.py)
  HM_CLAUDE_MODEL     Modell-ID (Standard: claude-sonnet-4-6)
  HUGIN_GEMINI_KEY    Fallback: Gemini statt Claude
"""

import json
import os
import sys
import subprocess
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent
ORACLE = WORKSPACE / "scripts/hugin_oracle.py"
CLAUDE_MODEL = os.environ.get("HM_CLAUDE_MODEL", "claude-sonnet-4-6")

# Skill-Mapping: Ollama wählt den passenden Scope
SKILL_MAP = {
    "code": "code-review",
    "research": "research",
    "default": "research",
}

# System-Kontext: Claude weiß dass es Subroutine ist
SUBROUTINE_CONTEXT = (
    "Du wirst als technisches Werkzeug von einem lokalen Ollama-Modell aufgerufen. "
    "Deine Aufgabe ist es, präzise und direkt zu antworten. "
    "Kein Vorwort, kein 'Ich bin Claude', keine Meta-Kommentare. "
    "Nur die Antwort auf die gestellte Frage."
)


def call_via_oracle(query: str, skill: str = "research") -> str:
    """Ruft hugin_oracle.py auf — das einzige erlaubte Gateway zu externen Providern."""
    if not ORACLE.exists():
        return f"[hugin_oracle.py nicht gefunden unter {ORACLE}]"

    full_query = f"{SUBROUTINE_CONTEXT}\n\nAufgabe: {query}"

    try:
        # Provider-Reihenfolge: local (Ollama selbst) → gemini → openai → mistral
        providers = ["gemini", "openai", "mistral", "local"]
        api_key_env = {
            "gemini": "HUGIN_GEMINI_KEY",
            "openai": "HUGIN_OPENAI_KEY",
            "mistral": "HUGIN_MISTRAL_KEY",
            "local": None,
        }
        # Verfügbaren Provider wählen
        chosen = next(
            (p for p in providers if api_key_env[p] is None or os.environ.get(api_key_env[p])),
            "gemini"
        )
        result = subprocess.run(
            ["python3", str(ORACLE), "query",
             "--provider", chosen,
             "--skill", skill,
             full_query],
            capture_output=True, text=True, timeout=60,
            env={**os.environ}
        )
        if result.returncode == 0:
            return result.stdout.strip()
        # Fallback: nächster Provider
        result2 = subprocess.run(
            ["python3", str(ORACLE), "query",
             "--provider", "mistral",
             "--skill", skill,
             full_query],
            capture_output=True, text=True, timeout=60,
            env={**os.environ}
        )
        if result2.returncode == 0:
            return result2.stdout.strip()
        return f"[Oracle-Fehler: {result.stderr.strip() or result2.stderr.strip()}]"
    except subprocess.TimeoutExpired:
        return "[Claude-Tool: Timeout (60s)]"
    except Exception as e:
        return f"[Claude-Tool Ausnahme: {e}]"


def run_plugin(request: dict) -> dict:
    payload = request.get("payload", {})
    query = payload.get("query") or payload.get("prompt") or payload.get("text", "")
    role = payload.get("role", "subroutine")
    skill_hint = payload.get("skill", "default")

    if not query:
        return {"ok": False, "output": "Kein Query übergeben (Felder: query/prompt/text)"}

    # Skill bestimmen
    skill = SKILL_MAP.get(skill_hint, SKILL_MAP["default"])
    for keyword in ["code", "implement", "function", "class", "bug", "fix", "rust", "python"]:
        if keyword in query.lower():
            skill = "code-review"
            break

    output = call_via_oracle(query, skill)

    return {
        "ok": True,
        "output": output,
        "role": role,
        "skill_used": skill,
        "source": "claude-via-hugin-oracle",
        "note": "Claude als Subroutine — Ollama ist Orchestrator",
    }


if __name__ == "__main__":
    raw = sys.stdin.readline()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "output": f"JSON-Fehler: {e}"}))
        sys.exit(0)

    result = run_plugin(req)
    print(json.dumps(result))
