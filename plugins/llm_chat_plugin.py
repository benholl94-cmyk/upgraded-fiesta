#!/usr/bin/env python3
"""LLM-chat plugin scaffold (hm-plugins protocol) -- Phase 4 of
docs/xcloud-platform-plan.md ("close the AI loop").

Unlike echo_plugin.py and hm-tool-exec, this plugin sends the task's message
off this machine to a third-party LLM API, so it follows the same
disclosure/consent rule the rest of this codebase enforces for anything with
that property (see ghm_core/cli.py's cmd_report_diagnostics): it must state
exactly what it is about to send, and refuse loudly -- not silently no-op,
not silently fabricate a response -- when it isn't fully and explicitly
configured.

NOT LIVE-VERIFIED: this environment has no LLM API credentials and no
network egress to a real completions endpoint to test against. The request
is written for a generic OpenAI-compatible /chat/completions-shaped API
(the most portable choice -- it works unmodified against many hosted
providers and self-hosted gateways without hardcoding one vendor; picking a
specific provider/model is the human decision docs/xcloud-platform-plan.md
flags). The code paths are exercised by tests/test_llm_chat_plugin.py
against a hermetic local mock HTTP server, not a real provider -- that is
NOT the same as a live round-trip and must never be described as one.

Required env vars to actually run for real (all deliberately opt-in, no
defaults that silently enable a network call):
  HM_LLM_ENABLE     "true" exactly -- refuses to run without it even if
                    everything else below is set
  HM_LLM_API_URL    full URL of an OpenAI-compatible chat completions endpoint
  HM_LLM_API_KEY    bearer token/API key for that endpoint
  HM_LLM_MODEL      model name/id to request (no usable default -- the
                    operator must choose one)
"""

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    line = sys.stdin.readline()
    request = json.loads(line)
    payload = request.get("payload") or {}
    message = payload.get("message") or request.get("objective") or ""

    if os.environ.get("HM_LLM_ENABLE", "").lower() != "true":
        return _refuse(
            "HM_LLM_ENABLE is not set to 'true' -- this plugin refuses to "
            "make any network call by default"
        )

    api_url = os.environ.get("HM_LLM_API_URL")
    api_key = os.environ.get("HM_LLM_API_KEY")
    model = os.environ.get("HM_LLM_MODEL")

    if not api_url or not api_key or not model:
        return _refuse(
            "HM_LLM_API_URL, HM_LLM_API_KEY, and HM_LLM_MODEL must all be "
            "set -- refusing rather than silently no-opping or guessing a model"
        )

    # Disclosure: exactly what is being sent, and to where, before it's sent.
    print(
        json.dumps({"disclosure": {"sending_to": api_url, "model": model, "message_chars": len(message)}}),
        file=sys.stderr,
    )
    sys.stderr.flush()

    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": message}]}
    ).encode("utf-8")
    http_request = urllib.request.Request(
        api_url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(http_request, timeout=30) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace") if error.fp else ""
        return _respond(False, {"http_status": error.code, "detail": detail}, "llm API returned an error status")
    except urllib.error.URLError as error:
        return _respond(False, {"reason": str(error.reason)}, "could not reach the configured LLM API URL")
    except json.JSONDecodeError:
        return _respond(False, {}, "LLM API response was not valid JSON")

    return _respond(True, {"reply": _extract_reply(parsed), "raw": parsed}, "llm-chat plugin executed")


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


if __name__ == "__main__":
    raise SystemExit(main())
