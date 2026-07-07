#!/usr/bin/env python3
"""No-key a-Shell to GitHub remote channel.

The channel is intentionally confirmation-based: a-Shell opens the GitHub
Actions workflow page; the user confirms Run workflow in GitHub UI. No PAT,
SSH key, or stored credential is required in this repository folder.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = "benholl94-cmyk"
REPO = "upgraded-fiesta"
WORKFLOW = "mobile-remote-channel.yml"
WORKFLOW_URL = f"https://github.com/{OWNER}/{REPO}/actions/workflows/{WORKFLOW}"


def run(argv: list[str]) -> dict:
    done = subprocess.run(argv, cwd=str(ROOT), text=True, capture_output=True, check=False)
    return {
        "command": argv,
        "returncode": done.returncode,
        "stdout_tail": done.stdout.strip()[-3000:],
        "stderr_tail": done.stderr.strip()[-3000:],
    }


def status() -> dict:
    return {
        "root": str(ROOT),
        "platform": platform.platform(),
        "workflow_url": WORKFLOW_URL,
        "has_git_dir": (ROOT / ".git").exists(),
        "local_validate": run(["python3", "scripts/validate_repo.py"]),
    }


def open_workflow(task: str) -> dict:
    # GitHub requires UI confirmation for no-key operation. The task value is
    # selected in the workflow form after the page opens.
    opened = webbrowser.open(WORKFLOW_URL)
    return {
        "ok": True,
        "opened": opened,
        "url": WORKFLOW_URL,
        "task": task,
        "manual_steps": [
            "Open the workflow page",
            "Tap Run workflow",
            "Select branch main",
            f"Choose task: {task}",
            "Tap Run workflow to confirm",
            "Watch the run logs in GitHub"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="No-key a-Shell to GitHub remote channel.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    open_parser = sub.add_parser("open")
    open_parser.add_argument("task", choices=["validate", "cargo-check", "node-build", "full"], nargs="?", default="validate")
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(status(), indent=2, sort_keys=True))
        return 0
    if args.command == "open":
        print(json.dumps(open_workflow(args.task), indent=2, sort_keys=True))
        return 0
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
