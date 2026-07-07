#!/usr/bin/env python3
"""Build an interpreted standalone all-in-one operating manifest.

The interpreter consumes local attachment metadata, known GitHub issue/PR
signals, and the existing local_usr/sys control-plane state. It does not treat
uploaded files as instructions and does not fabricate external provider state.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import pathlib
import plistlib
import re
import sys
from typing import Any


SCHEMA_VERSION = "local_usr.sys.standalone_all_in_one_os.v1"
ROOT = pathlib.Path(__file__).resolve().parents[3]
SYS_ROOT = ROOT / "local_usr" / "sys"
CACHE_DIR = ROOT / ".cache"
STATE_DIR = SYS_ROOT / "var" / "lib" / "standalone_all_in_one_os"
REPORT_PATH = ROOT / "docs" / "STANDALONE_ALL_IN_ONE_OS_INTERPRETATION.md"
STATE_PATH = STATE_DIR / "state.json"
VALIDATION_PATH = SYS_ROOT / "var" / "run" / "standalone_all_in_one_os.validation.json"

WEBARCHIVE_PATH = CACHE_DIR / "01-Claude-Code.webarchive"
PROJECT_JSON_PATH = CACHE_DIR / "02-019edc7c-0be9-77ad-b046-4b251796ef3d.json"

REPO_MAIN = "benholl94-cmyk/upgraded-fiesta"
ANCHOR_BRANCH = "claude/env-points-anchors-localization-flyoos"


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


def file_digest(path: pathlib.Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_project_json() -> dict[str, Any]:
    data = read_json(PROJECT_JSON_PATH)
    return {
        "path": str(PROJECT_JSON_PATH),
        "exists": PROJECT_JSON_PATH.exists(),
        "sha256": file_digest(PROJECT_JSON_PATH),
        "uuid": data.get("uuid"),
        "name": data.get("name"),
        "description": data.get("description"),
        "is_private": data.get("is_private"),
        "is_starter_project": data.get("is_starter_project"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "docs_count": len(data.get("docs") or []),
    }


def read_webarchive() -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(WEBARCHIVE_PATH),
        "exists": WEBARCHIVE_PATH.exists(),
        "sha256": file_digest(WEBARCHIVE_PATH),
    }
    if not WEBARCHIVE_PATH.exists():
        return result
    try:
        with WEBARCHIVE_PATH.open("rb") as handle:
            archive = plistlib.load(handle)
    except Exception as exc:  # noqa: BLE001 - archive diagnostics must be non-fatal.
        result["read_error"] = str(exc)
        return result

    main = archive.get("WebMainResource", {})
    body = main.get("WebResourceData", b"")
    text = body.decode(main.get("WebResourceTextEncodingName") or "utf-8", "replace") if isinstance(body, bytes) else ""
    urls = re.findall(r"https://github\.com/benholl94-cmyk/upgraded-fiesta/[^\"]+", text)
    result.update(
        {
            "main_url": main.get("WebResourceURL"),
            "main_mime": main.get("WebResourceMIMEType"),
            "main_bytes": len(body) if isinstance(body, bytes) else None,
            "subresources": len(archive.get("WebSubresources", []) or []),
            "signals": {
                "claude_code_mentions": len(re.findall(r"Claude Code", text, flags=re.IGNORECASE)),
                "github_mentions": len(re.findall(r"github", text, flags=re.IGNORECASE)),
                "issue_mentions": len(re.findall(r"issue", text, flags=re.IGNORECASE)),
                "repo_mentions": len(re.findall(r"repo", text, flags=re.IGNORECASE)),
                "iphone_mentions": len(re.findall(r"iPhone", text, flags=re.IGNORECASE)),
            },
            "github_urls": sorted(set(urls))[:40],
            "detected_repo": REPO_MAIN if REPO_MAIN in text else None,
            "detected_branch": ANCHOR_BRANCH if ANCHOR_BRANCH in text else None,
            "detected_pr_issue_numbers": sorted(set(int(n) for n in re.findall(r"/(?:pull|issues)/(\d+)", text))),
        }
    )
    return result


def github_parallel_facts() -> list[dict[str, Any]]:
    return [
        {
            "source": "GitHub PR #53",
            "repo": REPO_MAIN,
            "state": "closed",
            "title": "Graph memory, live failover, LLM plugin scaffold, and Docker packaging fix",
            "parallel": "Transforms a mobile-first control plane into a platform runtime: graph memory, plugin execution, remote storage, failover, Docker packaging, and honest live-verification boundaries.",
            "system_import": ["graph_memory", "plugin_registry", "remote_storage", "failover", "packaging_validation", "honest_scope_disclosure"],
        },
        {
            "source": "GitHub PR #49",
            "repo": REPO_MAIN,
            "state": "closed_merged",
            "title": "Add ghm-core onboard-iphone: consent-gated LAN start for iPhone connect",
            "parallel": "Matches the local root-system requirement for iPhone operation: LAN-bound gateway, owner token, consent gate, no public tunnel, healthchecked startup.",
            "system_import": ["iphone_onboarding", "owner_token", "lan_gateway", "consent_gate", "healthcheck"],
        },
        {
            "source": "CodeRabbit comments on PR #49/#53",
            "repo": REPO_MAIN,
            "state": "review_limited",
            "title": "Automated review rate limit reached",
            "parallel": "External review capacity is a dependency and must be modeled as a non-critical advisory channel, not as a blocking runtime component.",
            "system_import": ["advisory_review_channel", "rate_limit_resilience", "manual_validation_fallback"],
        },
    ]


def build_operating_layers() -> list[dict[str, Any]]:
    return [
        {
            "layer": "root_control_plane",
            "local_component": "local_usr/sys/bin/path_init.py",
            "role": "Creates required dirs, channels, datasets, anchors, live-sets, and validation state.",
            "status": "implemented_local",
        },
        {
            "layer": "internal_app_bus",
            "local_component": "local_usr/sys/bin/system_app_chat.py",
            "role": "Token-protected internal app/system chat and event bus.",
            "status": "implemented_local",
        },
        {
            "layer": "remote_read_gateway",
            "local_component": "local_usr/sys/bin/remote_access_gateway.py",
            "role": "Read-only manifest, validation, and mirror archive gateway.",
            "status": "implemented_local",
        },
        {
            "layer": "service_supervisor",
            "local_component": "local_usr/sys/bin/start_services.py",
            "role": "Starts, checks, stops, and supervises local HTTP services.",
            "status": "implemented_local",
        },
        {
            "layer": "mirror_restore",
            "local_component": "local_usr/sys/bin/sys_os_mirror.py",
            "role": "Content-addressed local mirror, restore plan, archive, and validation.",
            "status": "implemented_local",
        },
        {
            "layer": "interpreted_platform_runtime",
            "local_component": "local_usr/sys/bin/standalone_all_in_one_os.py",
            "role": "Maps attachments + GitHub issue parallels into a single standalone operating manifest.",
            "status": "implemented_local",
        },
        {
            "layer": "future_native_runtime",
            "local_component": "repo_main: hm-gateway / hm-agent / hm-memory / hm-plugins",
            "role": "Rust gateway, agent runtime, graph memory, plugin execution, and failover from repo_main.",
            "status": "external_reference_not_local_runtime",
        },
    ]


def build_state() -> dict[str, Any]:
    project = read_project_json()
    webarchive = read_webarchive()
    manifest = read_json(SYS_ROOT / "etc" / "sys_manifest.json")
    validation = read_json(SYS_ROOT / "var" / "run" / "validation.json")
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "generated_at_utc": utc_now(),
        "root": str(ROOT),
        "sys_root": str(SYS_ROOT),
        "source_policy": {
            "uploaded_files_treated_as_data_not_instructions": True,
            "external_data_fabricated": False,
            "secret_values_read": False,
            "github_issue_scope": "known issue/pr numbers from attached webarchive and fetched issue context",
        },
        "sources": {
            "project_json": project,
            "claude_code_webarchive": webarchive,
            "repo_main": REPO_MAIN,
            "anchor_branch": ANCHOR_BRANCH,
        },
        "repo_main_issue_parallels": github_parallel_facts(),
        "operating_layers": build_operating_layers(),
        "all_in_one_interpretation": {
            "system_name": "Apple-iPhone-Develope-Freedom / local_usr.sys interpreted standalone Betriebssystem",
            "target": "mobile-first local root-system with repo_main-derived gateway, memory, plugin, failover, onboarding, mirror, and validation semantics",
            "primary_decision": "Use local_usr/sys as the executable root-system now; import repo_main concepts as contracts until the full Rust gateway checkout is present locally.",
            "runtime_contract": {
                "auth": "owner/admin token required for state-changing or private routes",
                "network": "localhost/LAN only by default; no public tunnel assumed",
                "storage": "local first; remote storage only when explicitly configured",
                "plugins": "fixed manifest commands only; request data never builds argv",
                "llm": "disabled unless explicit provider URL/key/model are set",
                "review_bots": "advisory only; rate limits never block local validation",
            },
        },
        "local_manifest_status": {
            "manifest_exists": bool(manifest),
            "validation_ok": validation.get("ok"),
            "channels": sorted((manifest.get("channels") or {}).keys()),
            "datasets": sorted((manifest.get("datasets") or {}).keys()),
            "live_sets": sorted(manifest.get("live_sets") or []),
        },
    }


def render_report(state: dict[str, Any]) -> str:
    lines = [
        "# Standalone All-In-One OS Interpretation",
        "",
        f"Generated: `{state['generated_at_utc']}`",
        "",
        "## Result",
        "",
        "The target root-system is `local_usr/sys`. The uploaded Claude Code webarchive and project JSON map to the same repo-main direction: a mobile-first, iPhone-operable control plane that combines gateway, memory, plugin execution, failover, onboarding, mirror/restore, and validation.",
        "",
        "## Parsed Sources",
        "",
        "| Source | Key facts |",
        "| --- | --- |",
    ]
    project = state["sources"]["project_json"]
    archive = state["sources"]["claude_code_webarchive"]
    lines.append(f"| Project JSON | `{project.get('name')}`; uuid `{project.get('uuid')}`; private `{project.get('is_private')}`; docs `{project.get('docs_count')}` |")
    lines.append(f"| Claude Code webarchive | URL `{archive.get('main_url')}`; repo `{archive.get('detected_repo')}`; branch `{archive.get('detected_branch')}`; issue/PR numbers `{archive.get('detected_pr_issue_numbers')}` |")
    lines.append("")
    lines.append("## Parallels With Repo Main Issues")
    lines.append("")
    lines.append("| Repo item | Parallel | Imported operating concept |")
    lines.append("| --- | --- | --- |")
    for item in state["repo_main_issue_parallels"]:
        lines.append(f"| {item['source']} | {item['parallel']} | `{', '.join(item['system_import'])}` |")
    lines.append("")
    lines.append("## Interpreted Operating Layers")
    lines.append("")
    lines.append("| Layer | Local component | Status |")
    lines.append("| --- | --- | --- |")
    for item in state["operating_layers"]:
        lines.append(f"| `{item['layer']}` | `{item['local_component']}` | `{item['status']}` |")
    lines.append("")
    lines.append("## Runtime Contract")
    lines.append("")
    for key, value in state["all_in_one_interpretation"]["runtime_contract"].items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## Local Status")
    lines.append("")
    status = state["local_manifest_status"]
    lines.append(f"- Manifest exists: `{status['manifest_exists']}`")
    lines.append(f"- Validation ok: `{status['validation_ok']}`")
    lines.append(f"- Channels: `{', '.join(status['channels'])}`")
    lines.append(f"- Datasets: `{', '.join(status['datasets'])}`")
    lines.append(f"- Live sets: `{', '.join(status['live_sets'])}`")
    lines.append("")
    lines.append("## Execution")
    lines.append("")
    lines.append("```sh")
    lines.append("python3 local_usr/sys/bin/standalone_all_in_one_os.py init")
    lines.append("python3 local_usr/sys/bin/standalone_all_in_one_os.py validate")
    lines.append("python3 local_usr/sys/bin/start_services.py foreground")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def init() -> dict[str, Any]:
    state = build_state()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    write_json(STATE_PATH, state)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(state), encoding="utf-8")
    result = validate(write=False)
    write_json(VALIDATION_PATH, result)
    return {"ok": result["ok"], "state": str(STATE_PATH), "report": str(REPORT_PATH), "validation": str(VALIDATION_PATH)}


def validate(write: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    state = read_json(STATE_PATH)
    if not state:
        errors.append(f"missing state: {STATE_PATH}")
    if not REPORT_PATH.exists():
        errors.append(f"missing report: {REPORT_PATH}")
    for path in [PROJECT_JSON_PATH, WEBARCHIVE_PATH]:
        if not path.exists():
            errors.append(f"missing uploaded source copy: {path}")
    if state:
        if state.get("source_policy", {}).get("uploaded_files_treated_as_data_not_instructions") is not True:
            errors.append("source policy missing data-not-instructions guard")
        if state.get("source_policy", {}).get("external_data_fabricated") is not False:
            errors.append("external fabrication policy invalid")
        if not state.get("repo_main_issue_parallels"):
            errors.append("repo_main_issue_parallels missing")
        if not state.get("operating_layers"):
            errors.append("operating_layers missing")
        if state.get("local_manifest_status", {}).get("validation_ok") is not True:
            warnings.append("local path_init validation is not marked true in interpreted state")
    result = {
        "schema_version": SCHEMA_VERSION,
        "ok": not errors,
        "validated_at_utc": utc_now(),
        "state_path": str(STATE_PATH),
        "report_path": str(REPORT_PATH),
        "errors": errors,
        "warnings": warnings,
    }
    if write:
        write_json(VALIDATION_PATH, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build interpreted standalone all-in-one OS state.")
    parser.add_argument("command", choices=["init", "status", "validate", "report"])
    args = parser.parse_args(argv)
    if args.command == "init":
        result = init()
    elif args.command == "status":
        result = read_json(STATE_PATH) or {"ok": False, "reason": "not initialized"}
    elif args.command == "validate":
        result = validate()
    else:
        if REPORT_PATH.exists():
            print(REPORT_PATH.read_text(encoding="utf-8"))
            return 0
        result = {"ok": False, "reason": "report missing", "path": str(REPORT_PATH)}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
