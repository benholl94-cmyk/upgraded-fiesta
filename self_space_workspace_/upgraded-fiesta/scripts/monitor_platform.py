#!/usr/bin/env python3
"""Repository-local monitoring checker for the fullstack control plane.

This script uses only Python standard-library modules. It verifies that the
production platform files exist, parses JSON configuration, checks that expected
runtime states and routes are represented, and emits a machine-readable report.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "monitoring" / "required-files.json"
REPORT_PATH = ROOT / "logs" / "monitoring-report.json"


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_required_files(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for raw in manifest.get("required_files", []):
        rel = str(raw)
        path = ROOT / rel
        results.append({
            "path": rel,
            "exists": path.exists(),
            "is_file": path.is_file(),
            "size_bytes": path.stat().st_size if path.exists() else 0,
        })
    return results


def check_platform_config() -> dict[str, Any]:
    path = ROOT / "ui" / "public" / "platform-config.json"
    config = read_json(path)
    endpoints = config.get("endpoints", [])
    return {
        "exists": path.exists(),
        "endpoint_count": len(endpoints) if isinstance(endpoints, list) else 0,
        "has_zero_staked_status": config.get("zeroStakedStatus") == "zero_staked",
        "has_timeout": isinstance(config.get("requestTimeoutMs"), int),
        "endpoint_ids": [item.get("id") for item in endpoints if isinstance(item, dict)],
    }


def check_source_markers(manifest: dict[str, Any]) -> dict[str, Any]:
    rotation = read_text(ROOT / "ui" / "src" / "endpoint-rotation.ts")
    gateway = read_text(ROOT / "crates" / "hm-gateway" / "src" / "main.rs")
    states = manifest.get("required_endpoint_states", [])
    routes = manifest.get("expected_routes", [])
    return {
        "endpoint_states_present": {state: str(state) in rotation for state in states},
        "gateway_routes_present": {route: route in gateway for route in routes},
        "gateway_agent_managed_present": "agent_managed" in gateway,
        "gateway_zero_staked_present": "zero_staked" in gateway,
        "ui_dispatch_present": "dispatchWithRotation" in rotation,
    }


def build_report() -> dict[str, Any]:
    manifest = read_json(MANIFEST)
    required_files = check_required_files(manifest)
    missing = [item for item in required_files if not item["exists"] or not item["is_file"]]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": manifest.get("platform"),
        "ok": len(missing) == 0,
        "missing_files": missing,
        "required_files": required_files,
        "platform_config": check_platform_config(),
        "source_markers": check_source_markers(manifest),
    }
    marker_failures = []
    source_markers = report["source_markers"]
    for group in ("endpoint_states_present", "gateway_routes_present"):
        for key, present in source_markers[group].items():
            if not present:
                marker_failures.append({"group": group, "key": key})
    for key in ("gateway_agent_managed_present", "gateway_zero_staked_present", "ui_dispatch_present"):
        if not source_markers[key]:
            marker_failures.append({"group": "source_marker", "key": key})
    report["marker_failures"] = marker_failures
    report["ok"] = bool(report["ok"] and not marker_failures)
    return report


def main() -> int:
    report = build_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
