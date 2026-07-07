#!/usr/bin/env python3
"""Recover an a-Shell Documents session into the correct project control plane.

Designed for the observed state:
  - Current directory is Documents, not the repo root.
  - python3 exists.
  - lg2 exists but fails outside a repository.
  - codex is missing from PATH.
  - scripts/mobile_operator.py is missing from the current directory.

The tool does not invent a remote Codex install. If Codex is missing, it creates
a local read-only fallback shim that reports environment status and bridge
absence honestly.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = "local_usr.sys.ashell_documents_recovery.v1"
ROOT = pathlib.Path(__file__).resolve().parents[3]
SYS_ROOT = ROOT / "local_usr" / "sys"
STATE_DIR = SYS_ROOT / "var" / "lib" / "ashell_documents_recovery"
REPORT_PATH = SYS_ROOT / "var" / "run" / "ashell_documents_recovery.validation.json"
DOC_PATH = ROOT / "docs" / "ASHELL_DOCUMENTS_RECOVERY.md"


PROJECT_MARKERS = [
    "scripts/mobile_operator.py",
    "scripts/validate_mobile_iphone_platform.py",
    "README.md",
    "README.ashell",
    "README.ashell.md",
    "local_usr/sys/bin/path_init.py",
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


def run(command: list[str], cwd: pathlib.Path, timeout: int = 20) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, timeout=timeout, check=False)
        return {
            "command": command,
            "cwd": str(cwd),
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": completed.stdout.strip()[-4000:],
            "stderr": completed.stderr.strip()[-4000:],
        }
    except FileNotFoundError:
        return {"command": command, "cwd": str(cwd), "ok": False, "exit_code": None, "stdout": "", "stderr": "command not found"}
    except subprocess.TimeoutExpired:
        return {"command": command, "cwd": str(cwd), "ok": False, "exit_code": None, "stdout": "", "stderr": f"timeout after {timeout}s"}


def command_version(command: str, args: list[str] | None = None) -> dict[str, Any]:
    resolved = shutil.which(command)
    result: dict[str, Any] = {"command": command, "available": bool(resolved), "path": resolved}
    if not resolved:
        return result
    probe = run([command, *(args or ["--version"])], pathlib.Path.cwd(), timeout=10)
    result["probe"] = probe
    return result


def candidate_roots(start: pathlib.Path) -> list[pathlib.Path]:
    home = pathlib.Path.home()
    docs_candidates = [
        start,
        start / "generated_heavy_metal",
        start / "generated_heavy_metal.git",
        start / "upgraded-fiesta",
        start / "upgraded-fiesta.git",
        start / "Developer" / "generated_heavy_metal.git",
        start / "Developer" / "upgraded-fiesta.git",
        home / "Documents" / "Developer" / "generated_heavy_metal.git",
        home / "Documents" / "Developer" / "upgraded-fiesta.git",
        home / "Documents" / "generated_heavy_metal.git",
        home / "Documents" / "upgraded-fiesta.git",
    ]
    unique: list[pathlib.Path] = []
    seen: set[str] = set()
    for path in docs_candidates:
        key = str(path.expanduser())
        if key not in seen:
            seen.add(key)
            unique.append(path.expanduser())
    return unique


def score_root(path: pathlib.Path) -> dict[str, Any]:
    markers = {marker: (path / marker).exists() for marker in PROJECT_MARKERS}
    score = sum(1 for value in markers.values() if value)
    git_present = (path / ".git").exists()
    if git_present:
        score += 2
    has_mobile_scripts = markers["scripts/mobile_operator.py"] and markers["scripts/validate_mobile_iphone_platform.py"]
    if has_mobile_scripts:
        score += 4
    return {
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "score": score if path.exists() and path.is_dir() else 0,
        "git_present": git_present,
        "has_mobile_scripts": has_mobile_scripts,
        "markers": markers,
    }


def locate_project(start: pathlib.Path) -> dict[str, Any]:
    scored = [score_root(path) for path in candidate_roots(start)]
    existing = [item for item in scored if item["exists"] and item["is_dir"]]
    best = max(existing, key=lambda item: item["score"], default=None)
    return {"start": str(start), "best": best, "candidates": scored}


def create_codex_fallback(shim_dir: pathlib.Path) -> pathlib.Path:
    shim_dir.mkdir(parents=True, exist_ok=True)
    target = shim_dir / "codex"
    body = """#!/usr/bin/env python3
import json, pathlib, sys
root = pathlib.Path.cwd()
payload = {
  "ok": True,
  "tool": "codex-local-fallback",
  "version": "local-fallback-1.0",
  "bridge_configured": False,
  "mode": "ashell_documents_recovery",
  "cwd": str(root),
  "reason": "Real Codex CLI was not found in PATH; this shim only reports local state.",
}
if "--version" in sys.argv:
  print(payload["version"])
else:
  print(json.dumps(payload, indent=2))
"""
    target.write_text(body, encoding="utf-8")
    try:
        os.chmod(target, 0o755)
    except OSError:
        pass
    return target


def install_shims(project_root: pathlib.Path | None) -> dict[str, Any]:
    shim_dir = STATE_DIR / "ashell_cmds"
    created = []
    if not shutil.which("codex"):
        created.append(str(create_codex_fallback(shim_dir)))
    env = {
        "schema_version": SCHEMA_VERSION,
        "shim_dir": str(shim_dir),
        "project_root": str(project_root) if project_root else None,
        "path_hint": f"export PATH={shim_dir}:$PATH",
        "codex_fallback_created": bool(created),
    }
    write_json(STATE_DIR / "ashell_workspace.env.json", env)
    return {"shim_dir": str(shim_dir), "created": created, "env": env}


def run_mobile_validation(project_root: pathlib.Path | None) -> dict[str, Any]:
    if not project_root or not project_root.exists():
        return {"ok": False, "reason": "project root not found"}
    steps: list[dict[str, Any]] = []
    scripts = [
        ["python3", "scripts/validate_mobile_iphone_platform.py"],
        ["python3", "scripts/mobile_operator.py", "self-test"],
        ["python3", "scripts/mobile_operator.py", "validate"],
        ["python3", "scripts/mobile_operator.py", "audit"],
    ]
    for command in scripts:
        script = project_root / command[1]
        if script.exists():
            steps.append(run(command, project_root))
        else:
            steps.append({"command": command, "cwd": str(project_root), "ok": False, "exit_code": None, "stdout": "", "stderr": f"missing script: {command[1]}"})
    if (project_root / ".git").exists():
        steps.append(run(["lg2", "status"], project_root))
    else:
        steps.append({"command": ["lg2", "status"], "cwd": str(project_root), "ok": False, "exit_code": None, "stdout": "", "stderr": "skipped: .git missing"})
    return {"ok": all(step.get("ok") for step in steps), "steps": steps}


def build_report(start: pathlib.Path, install: bool, validate: bool) -> dict[str, Any]:
    location = locate_project(start)
    best = location.get("best")
    project_root = pathlib.Path(best["path"]) if best and best.get("score", 0) > 0 else None
    shims = install_shims(project_root) if install else None
    validation = run_mobile_validation(project_root) if validate else None
    report = {
        "schema_version": SCHEMA_VERSION,
        "ok": bool(project_root),
        "diagnosed_at_utc": utc_now(),
        "facts": {
            "current_directory": str(start),
            "python3": command_version("python3"),
            "lg2": command_version("lg2", ["version"]),
            "codex": command_version("codex"),
            "observed_failure_class": "documents_not_project_root_and_codex_missing",
        },
        "location": location,
        "selected_project_root": str(project_root) if project_root else None,
        "shims": shims,
        "validation": validation,
        "next_commands": [
            "python3 local_usr/sys/bin/ashell_documents_recovery.py diagnose",
            "python3 local_usr/sys/bin/ashell_documents_recovery.py install-shims",
            "python3 local_usr/sys/bin/ashell_documents_recovery.py validate",
        ],
    }
    write_json(REPORT_PATH, report)
    return report


def write_docs() -> None:
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(
        """# a-Shell Documents Recovery

Observed failure:

- `python3` works.
- `lg2` exists, but `lg2 status` and `lg2 pull` fail because `Documents` is not a Git repository.
- `codex` is not installed in the current PATH.
- `scripts/validate_mobile_iphone_platform.py` and `scripts/mobile_operator.py` are not in `Documents`; they must be run from the project root.

Run:

```sh
python3 local_usr/sys/bin/ashell_documents_recovery.py all
```

If the project is under `~/Documents/Developer/upgraded-fiesta.git` or `~/Documents/Developer/generated_heavy_metal.git`, the tool will select it automatically.

When Codex CLI is missing, the tool creates a local fallback command at:

```text
local_usr/sys/var/lib/ashell_documents_recovery/ashell_cmds/codex
```

This fallback is not a real Codex CLI. It only reports local state honestly so scripts do not confuse `command not found` with a bridge failure.

Use this PATH command in a-Shell:

```sh
export PATH=local_usr/sys/var/lib/ashell_documents_recovery/ashell_cmds:$PATH
```
""",
        encoding="utf-8",
    )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recover a-Shell Documents into project-root validation flow.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("diagnose")
    sub.add_parser("install-shims")
    sub.add_parser("validate")
    sub.add_parser("all")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    start = pathlib.Path.cwd()
    write_docs()
    if args.command == "diagnose":
        report = build_report(start, install=False, validate=False)
    elif args.command == "install-shims":
        report = build_report(start, install=True, validate=False)
    elif args.command == "validate":
        report = build_report(start, install=False, validate=True)
    else:
        report = build_report(start, install=True, validate=True)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
