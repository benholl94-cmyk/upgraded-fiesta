#!/usr/bin/env python3
"""LLM Key Manager — autonomer Provider-Health-Checker und Fallback-Rotator.

Läuft als Cron-Job (task_type: llm-key-check) oder direkt via CLI.
Testet jeden konfigurierten Provider mit einem Minimal-Call, schreibt
den ersten funktionierenden Provider in config/llm-active.json.
Gateway und llm_chat_plugin.py lesen diese Datei automatisch.

Schlüssel werden NIEMALS committed. Sie kommen aus:
  1. HM_LLM_KEYS_FILE  — Pfad zu einer lokalen JSON-Datei (Standard: ~/.config/hm-gateway/llm-keys.json)
  2. Individuelle Env-Vars laut config/llm-providers.json (z.B. GROQ_API_KEY)
  3. Ollama braucht keinen Key.

Usage:
  python3 scripts/llm_key_manager.py          # check + rotate
  python3 scripts/llm_key_manager.py status   # nur lesen, nicht schreiben
  python3 scripts/llm_key_manager.py reset    # llm-active.json löschen
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROVIDERS_FILE = REPO_ROOT / "config" / "llm-providers.json"
ACTIVE_FILE = REPO_ROOT / "config" / "llm-active.json"
LOG_FILE = REPO_ROOT / "logs" / "llm-key-manager.json"

PROBE_MESSAGE = "ping"
PROBE_TIMEOUT = 8


def _load_providers() -> list[dict]:
    with open(PROVIDERS_FILE) as f:
        return json.load(f)


def _load_keys_file() -> dict[str, str]:
    """Reads the local keys file (gitignored). Returns empty dict if absent."""
    keys_path = os.environ.get(
        "HM_LLM_KEYS_FILE",
        os.path.expanduser("~/.config/hm-gateway/llm-keys.json"),
    )
    try:
        with open(keys_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _resolve_key(provider: dict, keys_file: dict[str, str]) -> str:
    """Resolves the API key for a provider. Providers with no key_env need none."""
    if not provider.get("key_env"):
        # No key required (Ollama, Pollinations, etc.)
        return ""
    key_env = provider["key_env"]
    # 1. Keys file (preferred — never in env on production)
    if provider["name"] in keys_file:
        return keys_file[provider["name"]]
    # 2. Individual env var
    if key_env and os.environ.get(key_env):
        return os.environ[key_env]
    return ""


def _resolve_url(provider: dict) -> str:
    if provider["name"] == "ollama":
        base = os.environ.get("HM_OLLAMA_URL", "http://localhost:11434")
        return f"{base}/v1/chat/completions"
    return provider["url"]


def _resolve_model(provider: dict) -> str:
    if provider["name"] == "ollama":
        return os.environ.get("HM_OLLAMA_MODEL", "llama3")
    return provider["model"]


def _probe(url: str, key: str, model: str) -> tuple[bool, str]:
    """Sends a minimal chat completions call. Returns (ok, detail)."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": PROBE_MESSAGE}],
        "max_tokens": 8,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
            reply = parsed.get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, f"ok — reply preview: {reply[:40]!r}"
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:120] if e.fp else str(e.code)
        return False, f"HTTP {e.code}: {detail}"
    except urllib.error.URLError as e:
        return False, f"URLError: {e.reason}"
    except Exception as e:
        return False, f"error: {e}"


def _write_active(provider_name: str, url: str, key: str, model: str) -> None:
    ACTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": True,
        "provider": provider_name,
        "url": url,
        "key": key,
        "model": model,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(ACTIVE_FILE, "w") as f:
        json.dump(payload, f, indent=2)


def _write_inactive(reason: str) -> None:
    ACTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": False,
        "reason": reason,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(ACTIVE_FILE, "w") as f:
        json.dump(payload, f, indent=2)


def _append_log(results: list[dict]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = []
    if LOG_FILE.exists():
        try:
            log = json.loads(LOG_FILE.read_text())
        except json.JSONDecodeError:
            log = []
    # Keep last 50 entries
    log.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results": results})
    log = log[-50:]
    LOG_FILE.write_text(json.dumps(log, indent=2))


def check_and_rotate(*, dry_run: bool = False) -> Optional[dict]:
    """Tests all providers in order, writes the first working one as active.
    Returns the winning provider dict or None if all failed."""
    providers = _load_providers()
    keys_file = _load_keys_file()
    results = []
    winner = None

    for provider in providers:
        url = _resolve_url(provider)
        key = _resolve_key(provider, keys_file)
        model = _resolve_model(provider)

        # Skip only when a key IS required (key_env set) but not found.
        # Providers with key_env=="" need no key (Ollama, Pollinations, etc.).
        if not key and provider.get("key_env"):
            results.append({"provider": provider["name"], "ok": False, "detail": "no key configured"})
            continue

        ok, detail = _probe(url, key, model)
        results.append({
            "provider": provider["name"],
            "ok": ok,
            "url": url,
            "model": model,
            "detail": detail,
        })

        if ok and winner is None:
            winner = {"provider": provider["name"], "url": url, "key": key, "model": model}
            if not dry_run:
                _write_active(provider["name"], url, key, model)
                break  # No need to test remaining providers

    if winner is None and not dry_run:
        _write_inactive("all providers failed or have no key configured")

    if not dry_run:
        _append_log(results)

    return winner


def status() -> None:
    """Prints current active config and last log entry."""
    if ACTIVE_FILE.exists():
        active = json.loads(ACTIVE_FILE.read_text())
        print(f"Active provider: {active.get('provider', 'none')}")
        print(f"  ok:      {active.get('ok')}")
        print(f"  url:     {active.get('url', '—')}")
        print(f"  model:   {active.get('model', '—')}")
        print(f"  checked: {active.get('checked_at', '—')}")
    else:
        print("No active provider file found.")

    if LOG_FILE.exists():
        log = json.loads(LOG_FILE.read_text())
        if log:
            last = log[-1]
            print(f"\nLast check ({last['ts']}):")
            for r in last["results"]:
                icon = "✓" if r["ok"] else "✗"
                print(f"  {icon} {r['provider']}: {r['detail']}")


def reset() -> None:
    if ACTIVE_FILE.exists():
        ACTIVE_FILE.unlink()
        print("Cleared llm-active.json")
    else:
        print("Nothing to reset.")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"

    if cmd == "status":
        status()
        return 0

    if cmd == "reset":
        reset()
        return 0

    if cmd in ("check", "rotate"):
        winner = check_and_rotate()
        if winner:
            print(f"Active: {winner['provider']} / {winner['model']} @ {winner['url']}")
            return 0
        else:
            print("No working provider found. Configure keys in ~/.config/hm-gateway/llm-keys.json")
            return 1

    # Called as hm-plugins protocol (stdin line)
    if cmd == "plugin":
        line = sys.stdin.readline()
        _request = json.loads(line)
        winner = check_and_rotate()
        ok = winner is not None
        result = {"provider": winner["provider"], "model": winner["model"]} if winner else {}
        sys.stdout.write(json.dumps({"ok": ok, "result": result, "message": "llm-key-check complete"}) + "\n")
        sys.stdout.flush()
        return 0

    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
