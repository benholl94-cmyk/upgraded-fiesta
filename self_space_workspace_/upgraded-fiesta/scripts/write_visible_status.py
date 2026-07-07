#!/usr/bin/env python3
"""Write repository-visible CI status.

The connector sometimes cannot see GitHub Actions check-runs or workflow-runs.
This script writes the current CI result into a normal repository file so status
can be fetched through the contents API.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MONITOR_REPORT = ROOT / "logs" / "monitoring-report.json"
VISIBLE_STATUS = ROOT / "logs" / "visible-status.json"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"raw": data}
    except Exception as error:
        return {"parse_error": str(error)}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def main() -> int:
    monitor_report = read_json(MONITOR_REPORT)
    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "scripts/write_visible_status.py",
        "repository": env("GITHUB_REPOSITORY", "benholl94-cmyk/upgraded-fiesta"),
        "sha": env("GITHUB_SHA"),
        "ref": env("GITHUB_REF"),
        "run_id": env("GITHUB_RUN_ID"),
        "run_number": env("GITHUB_RUN_NUMBER"),
        "workflow": env("GITHUB_WORKFLOW"),
        "actor": env("GITHUB_ACTOR"),
        "monitor_ok": monitor_report.get("ok"),
        "monitor_platform": monitor_report.get("platform"),
        "missing_files": monitor_report.get("missing_files", []),
        "marker_failures": monitor_report.get("marker_failures", []),
        "platform_config": monitor_report.get("platform_config", {}),
        "connector_visibility_workaround": True,
        "status_file_visible_via_contents_api": True,
    }
    VISIBLE_STATUS.parent.mkdir(parents=True, exist_ok=True)
    VISIBLE_STATUS.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
