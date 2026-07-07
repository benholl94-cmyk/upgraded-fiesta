#!/usr/bin/env python3
"""Write a repository-visible CI/monitoring report.

This script is intentionally standard-library only. It turns otherwise hidden
workflow state into a committed JSON file under logs/ so the status can be read
through repository file access even when check-run or artifact APIs are not
visible to the current connector.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "logs" / "visible-monitoring-report.json"
MONITOR_REPORT = ROOT / "logs" / "monitoring-report.json"
MONITOR_STDOUT = ROOT / "logs" / "monitoring-stdout.txt"


def load_json(path: Path) -> object | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - report writer must not hide parse failures
        return {"parse_error": str(error), "path": str(path)}


def load_text(path: Path, limit: int = 20000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return text[-limit:]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def main() -> int:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    monitor_exit_code = int(env("MONITOR_EXIT_CODE", "999"))
    setup_exit_code = int(env("SETUP_EXIT_CODE", "999"))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": env("GITHUB_REPOSITORY"),
        "workflow": env("GITHUB_WORKFLOW"),
        "run_id": env("GITHUB_RUN_ID"),
        "run_number": env("GITHUB_RUN_NUMBER"),
        "sha": env("GITHUB_SHA"),
        "ref": env("GITHUB_REF"),
        "actor": env("GITHUB_ACTOR"),
        "event": env("GITHUB_EVENT_NAME"),
        "monitor_exit_code": monitor_exit_code,
        "setup_exit_code": setup_exit_code,
        "ok": monitor_exit_code == 0 and setup_exit_code == 0,
        "monitoring_report": load_json(MONITOR_REPORT),
        "monitoring_stdout_tail": load_text(MONITOR_STDOUT),
        "visibility_bridge": {
            "purpose": "make hidden CI status visible through repository files",
            "report_path": "logs/visible-monitoring-report.json",
            "manual_action_required": False,
        },
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
