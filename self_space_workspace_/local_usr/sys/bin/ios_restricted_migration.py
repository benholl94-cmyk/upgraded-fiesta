#!/usr/bin/env python3
"""Hard-restricted iOS migration planner.

This tool translates "autonomous out-of-app" requirements into Apple-platform
safe mechanisms. It deliberately blocks kernel, sandbox, jailbreak, private
entitlement, root filesystem, launch daemon, and unrestricted background-daemon
requests.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import pathlib
import re
import sys
from typing import Any


SCHEMA_VERSION = "local_usr.sys.ios_restricted_migration.v1"
ROOT = pathlib.Path(__file__).resolve().parents[3]
SYS_ROOT = ROOT / "local_usr" / "sys"
STATE_DIR = SYS_ROOT / "var" / "lib" / "ios_restricted_migration"
STATE_PATH = STATE_DIR / "state.json"
PLAN_PATH = STATE_DIR / "migration_plan.json"
POLICY_PATH = SYS_ROOT / "etc" / "policies" / "ios_restricted_migration.policy.json"
VALIDATION_PATH = SYS_ROOT / "var" / "run" / "ios_restricted_migration.validation.json"
REPORT_PATH = ROOT / "docs" / "IOS_HARD_RESTRICTED_SAFE_MIGRATION.md"


BLOCKED_PATTERNS = [
    r"\bjailbreak\b",
    r"\bkernel\b",
    r"\bkext\b",
    r"\brootfs\b",
    r"\broot\s+filesystem\b",
    r"\bsandbox\s*(escape|bypass|break)\b",
    r"\bprivate\s+entitlement\b",
    r"\blaunchd\b",
    r"\bdaemon\b",
    r"\bbackground\s+daemon\b",
    r"\bmobile substrate\b",
    r"\bdyld\s+injection\b",
    r"\bptrace\b",
    r"\btfp0\b",
    r"\bAMFI\b",
    r"\bSIP\b",
]

SAFE_MECHANISMS = [
    {
        "id": "bg_app_refresh",
        "name": "BGAppRefreshTask / SwiftUI appRefresh",
        "use_for": "short refresh and state update jobs that iOS may schedule opportunistically",
        "limits": "system scheduled; short runtime; not guaranteed at exact time",
        "requires": ["background modes capability", "registered task identifier"],
    },
    {
        "id": "bg_processing",
        "name": "BGProcessingTask",
        "use_for": "longer maintenance/data-processing jobs while the device is idle",
        "limits": "interruptible; requires processing background mode; not a permanent daemon",
        "requires": ["processing UIBackgroundModes capability", "expiration handler"],
    },
    {
        "id": "continued_processing",
        "name": "BGContinuedProcessingTask",
        "use_for": "user-started work that can continue after the app is backgrounded",
        "limits": "must start from foreground/user action; progress/cancel behavior required",
        "requires": ["user action", "progress reporting", "cancellation handling"],
    },
    {
        "id": "background_urlsession",
        "name": "Background URLSession",
        "use_for": "system-managed uploads/downloads that continue when the app is suspended",
        "limits": "network transfer only; completion delivered by system",
        "requires": ["URLSession background configuration"],
    },
    {
        "id": "app_extensions",
        "name": "App Extensions",
        "use_for": "Share Sheet, File Provider, Widget, Intent/App Intent, Notification Service, Spotlight indexing",
        "limits": "separate extension bundles with constrained APIs and lifecycle",
        "requires": ["extension target", "declared extension point"],
    },
    {
        "id": "app_groups",
        "name": "App Groups / shared container",
        "use_for": "safe data exchange between app and its extensions",
        "limits": "only within same developer team/app group entitlement",
        "requires": ["App Group entitlement", "containerized data model"],
    },
    {
        "id": "shortcuts_app_intents",
        "name": "Shortcuts / App Intents",
        "use_for": "user-visible automation entry points outside the app UI",
        "limits": "user-configured or user-approved automation; no hidden daemon behavior",
        "requires": ["App Intents definitions", "clear parameter validation"],
    },
    {
        "id": "local_lan_gateway",
        "name": "Local/LAN Gateway Pairing",
        "use_for": "iPhone controls a reachable local service with explicit owner token",
        "limits": "LAN/local only unless separately deployed behind proper auth/TLS",
        "requires": ["owner token", "consent gate", "healthcheck", "no public tunnel by default"],
    },
]

DEFAULT_REQUIREMENTS = [
    "autonomous periodic repo validation outside the foreground app",
    "out-of-app task trigger from Shortcuts or share sheet",
    "local gateway pairing between iPhone and operator service",
    "safe migration of Apple kernel iOS sets without modifying kernel or bypassing sandbox",
    "persistent audit trail and issue classification",
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


def normalize_requirements(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        raw = value.get("requirements") or value.get("tasks") or value.get("capabilities") or []
        return normalize_requirements(raw)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return list(DEFAULT_REQUIREMENTS)


def classify(requirement: str) -> dict[str, Any]:
    lower = requirement.lower()
    blocked = [pattern for pattern in BLOCKED_PATTERNS if re.search(pattern, lower)]
    if blocked:
        if "without modifying kernel" in lower or "without bypassing sandbox" in lower:
            return {
                "requirement": requirement,
                "classification": "allowed_with_boundary",
                "reason": "mentions restricted Apple-kernel/iOS terms but explicitly constrains migration to non-modifying, non-bypass behavior",
                "blocked_patterns_seen": blocked,
                "recommended_mechanisms": ["policy_boundary", "local_lan_gateway", "app_groups"],
            }
        return {
            "requirement": requirement,
            "classification": "blocked",
            "reason": "kernel, sandbox, jailbreak, private entitlement, daemon, or root-level behavior is outside safe app/container boundaries",
            "blocked_patterns_seen": blocked,
            "recommended_mechanisms": ["policy_boundary"],
        }

    recommendations: list[str] = []
    if any(term in lower for term in ["periodic", "background", "autonomous", "maintenance", "validation"]):
        recommendations.extend(["bg_app_refresh", "bg_processing"])
    if any(term in lower for term in ["continue", "long", "minutes", "processing"]):
        recommendations.append("continued_processing")
    if any(term in lower for term in ["download", "upload", "sync", "network"]):
        recommendations.append("background_urlsession")
    if any(term in lower for term in ["share", "widget", "intent", "shortcut", "spotlight", "extension", "out-of-app", "outside"]):
        recommendations.extend(["app_extensions", "shortcuts_app_intents"])
    if any(term in lower for term in ["file", "shared", "container", "migration"]):
        recommendations.append("app_groups")
    if any(term in lower for term in ["gateway", "lan", "iphone", "operator", "local"]):
        recommendations.append("local_lan_gateway")
    if not recommendations:
        recommendations.append("manual_operator_task")
    return {
        "requirement": requirement,
        "classification": "allowed",
        "reason": "can be mapped to Apple-platform safe app, extension, background-task, or local-gateway behavior",
        "blocked_patterns_seen": [],
        "recommended_mechanisms": sorted(set(recommendations)),
    }


def build_policy() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_id": "ios_hard_restricted_safe_migration",
        "deny": {
            "kernel_modification": True,
            "sandbox_bypass": True,
            "jailbreak_dependency": True,
            "private_entitlements": True,
            "root_filesystem_write": True,
            "hidden_persistent_daemon": True,
            "public_tunnel_by_default": True,
        },
        "allow": {
            "background_tasks": True,
            "background_urlsession": True,
            "app_extensions": True,
            "app_groups": True,
            "shortcuts_app_intents": True,
            "local_lan_gateway_with_owner_token": True,
            "manual_operator_approval": True,
        },
        "safe_mechanisms": SAFE_MECHANISMS,
        "blocked_patterns": BLOCKED_PATTERNS,
    }


def build_plan(requirements: list[str]) -> dict[str, Any]:
    issues = [classify(item) for item in requirements]
    blocked = [item for item in issues if item["classification"] == "blocked"]
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_id": "ios_autonomous_out_of_app_safe_migration",
        "generated_at_utc": utc_now(),
        "ok": not blocked,
        "root": str(ROOT),
        "sys_root": str(SYS_ROOT),
        "requirements": requirements,
        "issues": issues,
        "safe_mechanisms": SAFE_MECHANISMS,
        "operating_decision": (
            "Build only app-sandbox-compatible automation. Treat Apple kernel/iOS sets as immutable platform boundaries, "
            "not as migration targets."
        ),
        "execution_profiles": [
            {
                "profile": "iphone_local_operator",
                "entry": "Shortcuts/App Intent or foreground app action",
                "worker": "BGTaskScheduler or Background URLSession where applicable",
                "state": "App Group container or local_usr/sys mirror via explicit file export/import",
                "network": "localhost/LAN gateway with owner token; no public tunnel by default",
            },
            {
                "profile": "codex_cloud_or_repo_actions",
                "entry": "GitHub Action, issue/PR event, or manual operator command",
                "worker": "repo validation/build/test scripts",
                "state": "repository artifacts and validation reports",
                "network": "provider-managed CI only; secrets through official secret store",
            },
        ],
    }


def render_report(plan: dict[str, Any]) -> str:
    lines = [
        "# iOS Hard-Restricted Safe Migration",
        "",
        f"Generated: `{plan['generated_at_utc']}`",
        "",
        "## Result",
        "",
        "This build treats Apple kernel/iOS sets as hard platform boundaries. It does not modify kernel state, bypass the sandbox, depend on jailbreak behavior, install hidden daemons, request private entitlements, or write outside app/container-approved locations.",
        "",
        "## Classification",
        "",
        "| Requirement | Classification | Mechanisms |",
        "| --- | --- | --- |",
    ]
    for issue in plan["issues"]:
        lines.append(
            f"| {issue['requirement']} | `{issue['classification']}` | `{', '.join(issue['recommended_mechanisms'])}` |"
        )
    lines.extend(
        [
            "",
            "## Safe Out-of-App Mechanisms",
            "",
            "| Mechanism | Use | Limit |",
            "| --- | --- | --- |",
        ]
    )
    for mechanism in SAFE_MECHANISMS:
        lines.append(f"| `{mechanism['id']}` | {mechanism['use_for']} | {mechanism['limits']} |")
    lines.extend(
        [
            "",
            "## Execution",
            "",
            "```sh",
            "python3 local_usr/sys/bin/ios_restricted_migration.py init",
            "python3 local_usr/sys/bin/ios_restricted_migration.py validate",
            "python3 local_usr/sys/bin/ios_restricted_migration.py plan",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def init(requirements: list[str] | None = None) -> dict[str, Any]:
    actual_requirements = requirements or list(DEFAULT_REQUIREMENTS)
    policy = build_policy()
    plan = build_plan(actual_requirements)
    state = {
        "schema_version": SCHEMA_VERSION,
        "ok": plan["ok"],
        "initialized_at_utc": utc_now(),
        "policy_path": str(POLICY_PATH),
        "plan_path": str(PLAN_PATH),
        "report_path": str(REPORT_PATH),
        "validation_path": str(VALIDATION_PATH),
        "policy": policy,
        "plan": plan,
    }
    write_json(POLICY_PATH, policy)
    write_json(PLAN_PATH, plan)
    write_json(STATE_PATH, state)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(plan), encoding="utf-8")
    result = validate(write=False)
    write_json(VALIDATION_PATH, result)
    return {"ok": result["ok"], "state": str(STATE_PATH), "plan": str(PLAN_PATH), "report": str(REPORT_PATH)}


def validate(write: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    policy = read_json(POLICY_PATH)
    plan = read_json(PLAN_PATH)
    state = read_json(STATE_PATH)
    for path in [POLICY_PATH, PLAN_PATH, STATE_PATH, REPORT_PATH]:
        if not path.exists():
            errors.append(f"missing file: {path}")
    if policy:
        deny = policy.get("deny", {})
        for key in ["kernel_modification", "sandbox_bypass", "jailbreak_dependency", "private_entitlements", "hidden_persistent_daemon"]:
            if deny.get(key) is not True:
                errors.append(f"policy does not deny {key}")
    if plan:
        blocked = [item for item in plan.get("issues", []) if item.get("classification") == "blocked"]
        if blocked:
            errors.append(f"blocked requirements present: {len(blocked)}")
        if "safe_mechanisms" not in plan:
            errors.append("plan missing safe mechanisms")
    if state and state.get("ok") is not True:
        warnings.append("state ok is not true; inspect blocked requirements")
    result = {
        "schema_version": SCHEMA_VERSION,
        "ok": not errors,
        "validated_at_utc": utc_now(),
        "policy_path": str(POLICY_PATH),
        "plan_path": str(PLAN_PATH),
        "state_path": str(STATE_PATH),
        "report_path": str(REPORT_PATH),
        "errors": errors,
        "warnings": warnings,
    }
    if write:
        write_json(VALIDATION_PATH, result)
    return result


def load_requirements(path: str | None) -> list[str]:
    if not path:
        return list(DEFAULT_REQUIREMENTS)
    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return normalize_requirements(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build hard-restricted safe iOS migration plan.")
    parser.add_argument("command", choices=["init", "validate", "plan", "policy", "report", "assess"])
    parser.add_argument("--requirements-json", help="JSON file containing requirements/capabilities/tasks list")
    parser.add_argument("--text", help="Single requirement text for assess")
    args = parser.parse_args(argv)
    if args.command == "init":
        result = init(load_requirements(args.requirements_json))
    elif args.command == "validate":
        result = validate()
    elif args.command == "plan":
        result = read_json(PLAN_PATH) or {"ok": False, "reason": "plan missing"}
    elif args.command == "policy":
        result = read_json(POLICY_PATH) or {"ok": False, "reason": "policy missing"}
    elif args.command == "report":
        if REPORT_PATH.exists():
            print(REPORT_PATH.read_text(encoding="utf-8"))
            return 0
        result = {"ok": False, "reason": "report missing"}
    else:
        text = args.text or " ".join(sys.stdin.read().split())
        result = classify(text)
        result["ok"] = result["classification"] != "blocked"
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
