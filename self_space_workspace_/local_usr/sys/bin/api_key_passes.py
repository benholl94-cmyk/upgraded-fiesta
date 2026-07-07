#!/usr/bin/env python3
"""Hardened API key pass policy and validator.

This tool creates policy artifacts for provider API keys without storing,
printing, or validating plaintext secret values. "Limitless" usage is modeled
as a denied bypass pattern: real engineering work must use explicit provider
limits, budgets, rotation, audit, and fail-closed behavior.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import sys
from typing import Any


SCHEMA_VERSION = "local_usr.sys.api_key_passes.v1"
ROOT = pathlib.Path(__file__).resolve().parents[3]
SYS_ROOT = ROOT / "local_usr" / "sys"
STATE_DIR = SYS_ROOT / "var" / "lib" / "api_key_passes"
CONFIG_DIR = ROOT / "config"
POLICY_PATH = CONFIG_DIR / "api-key-passes.policy.json"
STATE_PATH = STATE_DIR / "state.json"
VALIDATION_PATH = SYS_ROOT / "var" / "run" / "api_key_passes.validation.json"
REPORT_PATH = ROOT / "docs" / "API_KEY_PASSES_HARDENED_POLICY.md"


DENIED_INTENT_PATTERNS = [
    r"\blimitless\b",
    r"\bunlimited\b",
    r"\bno\s*limit\b",
    r"\bbypass\b",
    r"\bquota\s*(bypass|avoid|evade)\b",
    r"\brate\s*limit\s*(bypass|avoid|evade)\b",
    r"\bfree\s*credits?\s*(bypass|farm|abuse)\b",
]

DEFAULT_KEY_PASSES = [
    {
        "pass_id": "openai_api_key",
        "provider": "openai",
        "secret_ref": "env:OPENAI_API_KEY",
        "plaintext_storage": False,
        "required_controls": ["project_scoped_key", "usage_budget", "rotation", "audit", "fail_closed"],
        "allowed_targets": ["local_env_file_ignored_by_git", "ci_secret_store", "platform_secret_store"],
    },
    {
        "pass_id": "limitless_api_key",
        "provider": "limitless",
        "secret_ref": "env:LIMITLESS_API_KEY",
        "plaintext_storage": False,
        "required_controls": ["provider_terms_compliance", "usage_budget", "rotation", "audit", "fail_closed"],
        "allowed_targets": ["local_env_file_ignored_by_git", "ci_secret_store", "platform_secret_store"],
    },
    {
        "pass_id": "hm_owner_token",
        "provider": "local_hm_gateway",
        "secret_ref": "env:HM_OWNER_TOKEN",
        "plaintext_storage": False,
        "required_controls": ["local_only_default", "lan_disclosure", "rotation", "audit", "fail_closed"],
        "allowed_targets": ["local_env_file_ignored_by_git", "ios_keychain", "ci_secret_store"],
    },
]


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest_json(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload.setdefault("written_at_utc", utc_now())
    payload["content_sha256"] = digest_json({k: v for k, v in payload.items() if k != "content_sha256"})
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        return {"_read_error": str(exc)}


def classify_intent(text: str) -> dict[str, Any]:
    lowered = text.lower()
    hits = [pattern for pattern in DENIED_INTENT_PATTERNS if re.search(pattern, lowered)]
    if hits:
        return {
            "ok": False,
            "classification": "blocked",
            "reason": "quota, rate-limit, payment, or provider-limit bypass is denied",
            "matched_patterns": hits,
            "safe_alternative": "Use provider-approved project keys, budgets, rate limits, retries, caching, queues, and audit logs.",
        }
    return {
        "ok": True,
        "classification": "allowed",
        "reason": "intent can be handled through secret references and provider-compliant usage controls",
        "matched_patterns": [],
    }


def build_policy() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_id": "hardened_api_key_passes",
        "deny": {
            "plaintext_secret_in_repo": True,
            "plaintext_secret_in_logs": True,
            "quota_bypass": True,
            "rate_limit_evasion": True,
            "billing_bypass": True,
            "shared_personal_key_for_production": True,
            "fallback_to_no_auth": True,
        },
        "allow": {
            "secret_references_only": True,
            "environment_variable_names": True,
            "ios_keychain_reference": True,
            "ci_secret_store_reference": True,
            "platform_secret_store_reference": True,
            "budget_and_quota_enforcement": True,
            "rotation_metadata": True,
            "redacted_validation": True,
        },
        "passes": DEFAULT_KEY_PASSES,
        "required_runtime_behavior": {
            "missing_key": "fail_closed",
            "invalid_key": "fail_closed_without_echoing_secret",
            "rate_limited": "backoff_and_surface_machine_readable_error",
            "quota_exhausted": "stop_and_require_operator_action",
            "logs": "provider, key_ref, request_id, status, cost_or_usage_if_available; never secret value",
        },
        "denied_intent_patterns": DENIED_INTENT_PATTERNS,
    }


def inspect_presence() -> dict[str, Any]:
    return {
        "secret_values_read": False,
        "env_refs": {
            "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
            "LIMITLESS_API_KEY": bool(os.environ.get("LIMITLESS_API_KEY")),
            "HM_OWNER_TOKEN": bool(os.environ.get("HM_OWNER_TOKEN")),
        },
        "env_files": {
            ".env.local": (ROOT / ".env.local").exists(),
            ".env": (ROOT / ".env").exists(),
        },
    }


def render_report(policy: dict[str, Any], presence: dict[str, Any]) -> str:
    lines = [
        "# Hardened API Key Passes Policy",
        "",
        "## Result",
        "",
        "This project uses secret references only. It does not commit API keys, print API keys, or implement quota/rate-limit/billing bypasses. Requests for \"limitless\" access are handled as blocked bypass intent and replaced with provider-compliant controls: budgets, retries, queues, caching, rotation, and audit.",
        "",
        "## Key Passes",
        "",
        "| Pass | Provider | Secret reference | Controls |",
        "| --- | --- | --- | --- |",
    ]
    for item in policy["passes"]:
        lines.append(
            f"| `{item['pass_id']}` | `{item['provider']}` | `{item['secret_ref']}` | `{', '.join(item['required_controls'])}` |"
        )
    lines.extend(
        [
            "",
            "## Local Presence Check",
            "",
            f"- Secret values read: `{presence['secret_values_read']}`",
        ]
    )
    for name, present in presence["env_refs"].items():
        lines.append(f"- `{name}` present: `{present}`")
    lines.extend(
        [
            "",
            "## Execution",
            "",
            "```sh",
            "python3 local_usr/sys/bin/api_key_passes.py init",
            "python3 local_usr/sys/bin/api_key_passes.py validate",
            "python3 local_usr/sys/bin/api_key_passes.py assess --text \"use provider key with budget\"",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def init() -> dict[str, Any]:
    policy = build_policy()
    presence = inspect_presence()
    state = {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "initialized_at_utc": utc_now(),
        "policy_path": str(POLICY_PATH),
        "validation_path": str(VALIDATION_PATH),
        "report_path": str(REPORT_PATH),
        "presence": presence,
        "policy": policy,
    }
    write_json(POLICY_PATH, policy)
    write_json(STATE_PATH, state)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(policy, presence), encoding="utf-8")
    result = validate(write=False)
    write_json(VALIDATION_PATH, result)
    return {"ok": result["ok"], "policy": str(POLICY_PATH), "state": str(STATE_PATH), "report": str(REPORT_PATH)}


def validate(write: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    policy = read_json(POLICY_PATH)
    state = read_json(STATE_PATH)
    for path in [POLICY_PATH, STATE_PATH, REPORT_PATH]:
        if not path.exists():
            errors.append(f"missing file: {path}")
    if policy:
        deny = policy.get("deny", {})
        for key in ["plaintext_secret_in_repo", "plaintext_secret_in_logs", "quota_bypass", "rate_limit_evasion", "billing_bypass"]:
            if deny.get(key) is not True:
                errors.append(f"policy does not deny {key}")
        for item in policy.get("passes", []):
            ref = item.get("secret_ref", "")
            if not ref.startswith(("env:", "keychain:", "ci_secret:", "platform_secret:")):
                errors.append(f"unsafe secret_ref for {item.get('pass_id')}: {ref}")
            if item.get("plaintext_storage") is not False:
                errors.append(f"plaintext storage not disabled for {item.get('pass_id')}")
    if state and state.get("presence", {}).get("secret_values_read") is not False:
        errors.append("secret presence inspection read secret values")
    if not (ROOT / ".git").exists():
        warnings.append("workspace is not a git checkout; GitHub sync must use connector or exported package")
    result = {
        "schema_version": SCHEMA_VERSION,
        "ok": not errors,
        "validated_at_utc": utc_now(),
        "policy_path": str(POLICY_PATH),
        "state_path": str(STATE_PATH),
        "report_path": str(REPORT_PATH),
        "errors": errors,
        "warnings": warnings,
    }
    if write:
        write_json(VALIDATION_PATH, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create and validate hardened API key pass policy.")
    parser.add_argument("command", choices=["init", "validate", "policy", "status", "report", "assess"])
    parser.add_argument("--text", help="Intent text to classify for bypass/limit risk")
    args = parser.parse_args(argv)
    if args.command == "init":
        result = init()
    elif args.command == "validate":
        result = validate()
    elif args.command == "policy":
        result = read_json(POLICY_PATH) or {"ok": False, "reason": "policy missing"}
    elif args.command == "status":
        result = read_json(STATE_PATH) or {"ok": False, "reason": "state missing"}
    elif args.command == "report":
        if REPORT_PATH.exists():
            print(REPORT_PATH.read_text(encoding="utf-8"))
            return 0
        result = {"ok": False, "reason": "report missing"}
    else:
        text = args.text or " ".join(sys.stdin.read().split())
        result = classify_intent(text)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
