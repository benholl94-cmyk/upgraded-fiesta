#!/usr/bin/env python3
"""router plugin — skill-aware multi-model router.

Classifies the incoming message into a skill (code/research/reasoning/general),
picks the best available provider for that skill, and routes the call there.

Free-tier provider priority (no key needed):
  1. Ollama      — local, completely free if running
  2. Pollinations — https://text.pollinations.ai — free, no key, no signup
                   Models: openai (GPT-4o-mini), llama (Llama-3.1-70B), mistral
  3. llm-active  — whatever llm_key_manager.py found last
  4. HuggingFace — anonymous inference (rate-limited, no key for public models)

Skill routing config: config/router-skills.json
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ROUTER_SKILLS_FILE = REPO_ROOT / "config" / "router-skills.json"
ACTIVE_FILE = REPO_ROOT / "config" / "llm-active.json"

# Pollinations AI — legitimately free, OpenAI-compatible, no key required.
POLLINATIONS_URL = "https://text.pollinations.ai/openai/chat/completions"

# HuggingFace anonymous inference (works for many public models without a token)
HF_ANON_URL = "https://api-inference.huggingface.co/v1/chat/completions"
HF_ANON_MODEL = "meta-llama/Llama-3.2-3B-Instruct"


def _load_skills() -> dict:
    try:
        return json.loads(ROUTER_SKILLS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "skills": {
                "code":     {"keywords": ["code", "function", "bug", "error", "python", "rust",
                                          "javascript", "def ", "class ", "import ", "implement",
                                          "debug", "refactor", "snippet", "sql", "bash", "script"],
                             "providers": ["ollama", "pollinations-llama", "active"]},
                "research": {"keywords": ["what is", "explain", "research", "summary", "article",
                                          "news", "latest", "recent", "find", "search", "who",
                                          "when", "where", "history"],
                             "providers": ["pollinations-openai", "active", "pollinations-llama"]},
                "reasoning":{"keywords": ["analyze", "compare", "evaluate", "plan", "strategy",
                                          "decision", "should", "why", "how", "pros", "cons",
                                          "trade-off", "recommend"],
                             "providers": ["pollinations-openai", "ollama", "active"]},
                "general":  {"keywords": [],
                             "providers": ["active", "pollinations-openai", "ollama"]},
            },
            "default_skill": "general",
        }


def _detect_skill(message: str, skills_config: dict) -> str:
    msg_lower = message.lower()
    for skill_name, conf in skills_config["skills"].items():
        if skill_name == skills_config.get("default_skill", "general"):
            continue
        for kw in conf.get("keywords", []):
            if kw in msg_lower:
                return skill_name
    return skills_config.get("default_skill", "general")


def _try_ollama() -> tuple[str, str, str] | None:
    if os.environ.get("HM_OLLAMA_ENABLE", "").lower() != "true":
        return None
    base = os.environ.get("HM_OLLAMA_URL", "http://localhost:11434")
    model = os.environ.get("HM_OLLAMA_MODEL", "llama3")
    return f"{base}/v1/chat/completions", "", model


def _try_active() -> tuple[str, str, str] | None:
    try:
        data = json.loads(ACTIVE_FILE.read_text())
        if data.get("ok") and data.get("url") and data.get("model"):
            return data["url"], data.get("key", ""), data["model"]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def _try_pollinations(model: str) -> tuple[str, str, str]:
    return POLLINATIONS_URL, "", model


def _try_hf_anon() -> tuple[str, str, str]:
    return HF_ANON_URL, "", HF_ANON_MODEL


def _resolve_provider(provider_name: str) -> tuple[str, str, str] | None:
    if provider_name == "ollama":
        return _try_ollama()
    if provider_name == "active":
        return _try_active()
    if provider_name == "pollinations-openai":
        return _try_pollinations("openai")
    if provider_name == "pollinations-llama":
        return _try_pollinations("llama")
    if provider_name == "pollinations-mistral":
        return _try_pollinations("mistral")
    if provider_name == "hf-anon":
        return _try_hf_anon()
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
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_reply(parsed: dict) -> str:
    try:
        return parsed["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""


def _respond(ok: bool, result: dict, message: str) -> None:
    sys.stdout.write(json.dumps({"ok": ok, "result": result, "message": message}) + "\n")
    sys.stdout.flush()


def main() -> int:
    request = json.loads(sys.stdin.readline())
    payload = request.get("payload") or {}
    message: str = (payload.get("message")
                    or request.get("objective")
                    or "")
    skill_override: str = payload.get("skill", "")

    if not message:
        _respond(False, {"reason": "no message in payload"}, "router: no message")
        return 0

    skills_config = _load_skills()
    skill = skill_override if skill_override in skills_config["skills"] else _detect_skill(message, skills_config)
    providers_order = skills_config["skills"].get(skill, {}).get("providers", ["active", "pollinations-openai"])

    winner: tuple[str, str, str] | None = None
    for provider_name in providers_order:
        candidate = _resolve_provider(provider_name)
        if candidate is not None:
            winner = candidate
            break

    # Last resort: Pollinations is always available, no key needed.
    if winner is None:
        winner = _try_pollinations("openai")

    url, key, model = winner
    print(json.dumps({
        "disclosure": {
            "skill": skill,
            "provider_url": url,
            "model": model,
            "key_present": bool(key),
            "message_chars": len(message),
        }
    }), file=sys.stderr)
    sys.stderr.flush()

    try:
        parsed = _call_api(url, key, model, message)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:200] if e.fp else str(e.code)
        # Fallback to Pollinations on any upstream error.
        if (url, key, model) != _try_pollinations("openai"):
            winner = _try_pollinations("openai")
            try:
                parsed = _call_api(*winner, message)
            except Exception as e2:
                _respond(False, {"reason": str(e2)}, "router: all providers failed")
                return 0
        else:
            _respond(False, {"http_status": e.code, "detail": detail}, "router: API error")
            return 0
    except urllib.error.URLError as e:
        # Fallback to Pollinations on network error.
        if url != POLLINATIONS_URL:
            winner = _try_pollinations("openai")
            try:
                parsed = _call_api(*winner, message)
            except Exception as e2:
                _respond(False, {"reason": str(e2)}, "router: fallback also failed")
                return 0
        else:
            _respond(False, {"reason": str(e.reason)}, "router: URL error")
            return 0

    url, key, model = winner
    reply = _extract_reply(parsed)
    _respond(True, {
        "reply": reply,
        "skill": skill,
        "provider": url,
        "model": model,
        "raw": parsed,
    }, "router ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
