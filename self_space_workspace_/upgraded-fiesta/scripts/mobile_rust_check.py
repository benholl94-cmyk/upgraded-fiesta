#!/usr/bin/env python3
"""Mobile-aware Rust workspace checker.

This script does not pretend that a-Shell ships a native cargo toolchain.
It detects the available environment, runs the strongest possible local check,
and reports the exact next build route.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(argv: list[str]) -> dict:
    done = subprocess.run(argv, cwd=str(ROOT), text=True, capture_output=True, check=False)
    return {
        "command": argv,
        "returncode": done.returncode,
        "stdout_tail": done.stdout.strip()[-4000:],
        "stderr_tail": done.stderr.strip()[-4000:],
    }


def main() -> int:
    tools = {name: shutil.which(name) for name in ["python3", "cargo", "rustc", "docker", "node", "npm"]}
    result = {
        "platform": platform.platform(),
        "tools": tools,
        "structure": run(["python3", "scripts/validate_repo.py"]),
        "cargo_check": None,
        "route": None,
    }
    if tools["cargo"]:
        result["cargo_check"] = run(["cargo", "check", "--workspace"])
        result["route"] = "native-cargo"
    elif tools["docker"]:
        result["route"] = "docker-or-remote-cargo"
    else:
        result["route"] = "structure-only-on-mobile; use GitHub Actions, Codex Cloud, Codespaces, Mac/Linux, or Docker host for cargo"
    ok = result["structure"]["returncode"] == 0 and (result["cargo_check"] is None or result["cargo_check"]["returncode"] == 0)
    result["ok"] = ok
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
