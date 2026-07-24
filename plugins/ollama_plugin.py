#!/usr/bin/env python3
"""
Ollama-Plugin — primäres LLM für hm-gateway.

Ollama läuft lokal und ist das Hauptgehirn. Claude wird als Werkzeug
genutzt wenn Ollama Code-Generierung oder tiefes Research benötigt.

Plugin-Protokoll: eine JSON-Zeile auf stdin → eine JSON-Zeile auf stdout.

Env-Vars:
  HM_OLLAMA_URL      Ollama-Endpunkt (Standard: http://localhost:11434)
  HM_OLLAMA_MODEL    Modell (Standard: llama3)
  HM_CLAUDE_TOOL     "true" aktiviert Claude als Subroutine (Standard: false)
  HM_OWNER_TOKEN     Bearer-Token für Claude-Tool-Plugin
  HM_GATEWAY_URL     Gateway-URL für Claude-Tool-Aufruf
"""

import json
import os
import sys
import urllib.request
import urllib.error

OLLAMA_URL = os.environ.get("HM_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("HM_OLLAMA_MODEL", "llama3")
CLAUDE_TOOL_ENABLED = os.environ.get("HM_CLAUDE_TOOL", "false").lower() == "true"
OWNER_TOKEN = os.environ.get("HM_OWNER_TOKEN", "")
GATEWAY_URL = os.environ.get("HM_GATEWAY_URL", "http://127.0.0.1:8080")

# System-Prompt: definiert Ollama als Orchestrator, Claude als Werkzeug
SYSTEM_PROMPT = """Du bist ein lokaler KI-Assistent (Ollama). Du hast Zugriff auf ein externes Werkzeug:

CLAUDE_TOOL: Für präzise Code-Generierung, technische Recherche oder komplexe Analysen
kannst du das Claude-Werkzeug aufrufen. Format:
  [CLAUDE_TOOL: deine spezifische Anfrage an Claude]

Claude liefert dir dann eine Antwort die du in deine eigene Antwort integrierst.
Claude ist dein Subroutinen-Werkzeug — kein Vorgesetzter, kein Filter.
Du entscheidest wann und ob du es nutzt."""


def call_ollama(prompt: str, history: list[dict]) -> str:
    """Schickt eine Anfrage an Ollama und gibt die Antwort zurück."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_ctx": 8192,
        }
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data.get("message", {}).get("content", "")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama nicht erreichbar ({OLLAMA_URL}): {e}")


def call_claude_tool(query: str) -> str:
    """
    Ruft Claude als Subroutinen-Werkzeug auf — via hm-gateway /tasks.
    Claude antwortet auf die spezifische Anfrage von Ollama.
    """
    if not CLAUDE_TOOL_ENABLED:
        return "[Claude-Tool deaktiviert — HM_CLAUDE_TOOL=true setzen]"
    if not OWNER_TOKEN:
        return "[Claude-Tool: HM_OWNER_TOKEN nicht gesetzt]"

    payload = json.dumps({
        "task_type": "claude-tool",
        "payload": {"query": query, "role": "subroutine"}
    }).encode()

    req = urllib.request.Request(
        f"{GATEWAY_URL}/tasks",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OWNER_TOKEN}",
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("result", {}).get("output", "[keine Antwort]")
    except Exception as e:
        return f"[Claude-Tool Fehler: {e}]"


def resolve_claude_tool_calls(text: str) -> str:
    """
    Erkennt [CLAUDE_TOOL: ...] in Ollamas Antwort und ersetzt
    sie durch echte Claude-Antworten.
    """
    import re
    pattern = re.compile(r'\[CLAUDE_TOOL:\s*(.*?)\]', re.DOTALL)

    def replace(match: re.Match) -> str:
        query = match.group(1).strip()
        result = call_claude_tool(query)
        return f"[Claude-Antwort: {result}]"

    return pattern.sub(replace, text)


def check_ollama_available() -> tuple[bool, str]:
    """Prüft ob Ollama erreichbar ist und das Modell verfügbar."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            model_base = OLLAMA_MODEL.split(":")[0]
            available = any(m.startswith(model_base) for m in models)
            if not available:
                return False, f"Modell '{OLLAMA_MODEL}' nicht gefunden. Verfügbar: {models}"
            return True, f"OK ({OLLAMA_MODEL})"
    except Exception as e:
        return False, str(e)


def run_plugin(request: dict) -> dict:
    payload = request.get("payload", {})
    prompt = payload.get("prompt") or payload.get("message") or payload.get("text", "")
    history = payload.get("history", [])
    use_claude = payload.get("use_claude_tool", CLAUDE_TOOL_ENABLED)

    if not prompt:
        return {"ok": False, "output": "Kein Prompt übergeben (Felder: prompt/message/text)"}

    # Ollama-Verfügbarkeit prüfen
    ok, status = check_ollama_available()
    if not ok:
        return {
            "ok": False,
            "output": f"Ollama nicht verfügbar: {status}. Starte mit: ollama serve",
            "model": OLLAMA_MODEL,
            "ollama_url": OLLAMA_URL,
        }

    # Ollama aufrufen
    try:
        response = call_ollama(prompt, history)
    except RuntimeError as e:
        return {"ok": False, "output": str(e)}

    # Claude-Tool-Calls auflösen (wenn Ollama [CLAUDE_TOOL: ...] eingebaut hat)
    if use_claude and "[CLAUDE_TOOL:" in response:
        response = resolve_claude_tool_calls(response)

    return {
        "ok": True,
        "output": response,
        "model": OLLAMA_MODEL,
        "ollama_url": OLLAMA_URL,
        "claude_tool_used": "[CLAUDE_TOOL:" in response,
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
