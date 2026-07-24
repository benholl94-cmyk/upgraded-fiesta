#!/usr/bin/env python3
"""LLM-chat plugin (hm-plugins protocol) — Phase 4/5, self-sustaining.

Provider-Fallback-Kette (in Priorität):
  1. Ollama    — lokal, kein Key, kein Netzwerk-Egress, komplett frei
  2. HF        — HuggingFace Inference API, kostenloser Account reicht
  3. Groq      — 14 400 req/day gratis, kein Kredit nötig
  4. Together  — $25 Startkredit gratis, danach Free-Tier
  5. Mistral   — kostenloses Tier auf Small-Modellen
  6. Konfiguriert — HM_LLM_API_URL/KEY/MODEL (beliebiger OpenAI-kompatibler Endpoint)

Aktiver Provider wird von scripts/llm_key_manager.py in
config/llm-active.json geschrieben und stündlich (cron: llm-key-check)
geprüft. Die Kette läuft ohne physische Anwesenheit des Owners.

Disclosure-Regel gilt weiterhin: dieser Plugin sendet nichts, ohne
vorher auf stderr zu schreiben was er sendet und wohin.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ACTIVE_FILE = pathlib.Path(
    os.environ.get("HM_LLM_ACTIVE_FILE", str(REPO_ROOT / "config" / "llm-active.json"))
)


def _load_active_provider() -> dict | None:
    """Reads the provider written by llm_key_manager.py, if present and ok."""
    try:
        data = json.loads(ACTIVE_FILE.read_text())
        if data.get("ok") and data.get("url") and data.get("model"):
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def _resolve_provider(message: str) -> tuple[str, str, str] | None:
    """Returns (url, key, model) for the first available provider, or None.

    Priority:
      1. Ollama (HM_OLLAMA_ENABLE=true)
      2. llm-active.json written by key manager
      3. Explicit HM_LLM_* env vars (backwards-compatible)
    """
    # 1. Ollama — local, free, no key
    if os.environ.get("HM_OLLAMA_ENABLE", "").lower() == "true":
        base = os.environ.get("HM_OLLAMA_URL", "http://localhost:11434")
        model = os.environ.get("HM_OLLAMA_MODEL", "llama3")
        return f"{base}/v1/chat/completions", "", model

    # 2. Key-manager active provider (autonomous rotation)
    active = _load_active_provider()
    if active:
        return active["url"], active.get("key", ""), active["model"]

    # 3. Legacy explicit env vars (HM_LLM_ENABLE=true required)
    if os.environ.get("HM_LLM_ENABLE", "").lower() == "true":
        url = os.environ.get("HM_LLM_API_URL")
        key = os.environ.get("HM_LLM_API_KEY")
        model = os.environ.get("HM_LLM_MODEL")
        if url and model:
            return url, key or "", model

    return None


def _call_api(url: str, key: str, model: str, message: str) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": message}],
    }).encode("utf-8")
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_reply(parsed: dict) -> str:
    try:
        return parsed["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""


def _refuse(reason: str) -> int:
    return _respond(False, {"reason": reason}, "llm-chat plugin refused to run")


def _respond(ok: bool, result: dict, message: str) -> int:
    sys.stdout.write(json.dumps({"ok": ok, "result": result, "message": message}) + "\n")
    sys.stdout.flush()
    return 0


def main() -> int:
    line = sys.stdin.readline()
    request = json.loads(line)
    payload = request.get("payload") or {}
    message = payload.get("message") or request.get("objective") or ""

    provider = _resolve_provider(message)
    if provider is None:
        return _refuse(
            "No LLM provider available. Options: "
            "(a) set HM_OLLAMA_ENABLE=true if Ollama is running locally, "
            "(b) run scripts/llm_key_manager.py after adding keys to "
            "~/.config/hm-gateway/llm-keys.json, "
            "(c) set HM_LLM_ENABLE=true + HM_LLM_API_URL/KEY/MODEL."
        )

    url, key, model = provider
    # Disclosure: what is being sent and where, before it's sent.
    print(
        json.dumps({"disclosure": {
            "sending_to": url,
            "model": model,
            "message_chars": len(message),
            "key_present": bool(key),
        }}),
        file=sys.stderr,
    )
    sys.stderr.flush()

    try:
        parsed = _call_api(url, key, model, message)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:120] if e.fp else str(e.code)
        return _respond(False, {"http_status": e.code, "detail": detail}, "llm API returned an error status")
    except urllib.error.URLError as e:
        return _respond(False, {"reason": str(e.reason)}, "could not reach the configured LLM API URL")
    except json.JSONDecodeError:
        return _respond(False, {}, "LLM API response was not valid JSON")

    return _respond(True, {"reply": _extract_reply(parsed), "raw": parsed}, "llm-chat plugin executed")


if __name__ == "__main__":
    raise SystemExit(main())
