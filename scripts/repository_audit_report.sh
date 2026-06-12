#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

usage() {
  cat <<'USAGE'
Usage: scripts/repository_audit_report.sh [--output PATH] [--format markdown|json]

Creates a live, deterministic repository audit from the current checkout.
The report includes UTC timestamps, Git state, directory/file inventory,
content hashes, permissions, sizes, line counts, and local quality signals.

No report data is hard-coded: all values are read from the live filesystem
and Git checkout at runtime.
USAGE
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_path=""
report_format="markdown"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      [[ $# -ge 2 ]] || { printf 'Missing value for --output\n' >&2; exit 64; }
      output_path="$2"; shift 2 ;;
    --format)
      [[ $# -ge 2 ]] || { printf 'Missing value for --format\n' >&2; exit 64; }
      report_format="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 64 ;;
  esac
done

case "$report_format" in
  markdown|json) ;;
  *) printf 'Unsupported format: %s\n' "$report_format" >&2; exit 64 ;;
esac

cd "$repo_root"

python_bin="${PYTHON_BIN:-python3}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
  printf 'Required command not found: %s\n' "$python_bin" >&2
  exit 69
fi

if [[ -n "$output_path" ]]; then
  mkdir -p "$(dirname "$output_path")"
  "$python_bin" - "$repo_root" "$report_format" > "$output_path" <<'PY'
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
from typing import Any

root = pathlib.Path(sys.argv[1]).resolve()
report_format = sys.argv[2]

EXCLUDED_DIRS = {".git", "node_modules", "vendor", "Pods", "DerivedData", "build", "dist", ".next"}
GAP_MARKER_RE = re.compile(
    r"\b(TODO|FIXME|TBD|PLACEHOLDER|CHANGEME)\b|"
    r"(sample-token|password-here|api[_-]?key)|"
    r"(<[^>\n]{1,80}>)",
    re.IGNORECASE,
)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def run(argv: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(argv, cwd=root, text=True, capture_output=True, check=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def utc_from_timestamp(timestamp: float) -> str:
    return dt.datetime.fromtimestamp(timestamp, dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def should_skip(path: pathlib.Path) -> bool:
    rel_parts = path.relative_to(root).parts
    return any(part in EXCLUDED_DIRS for part in rel_parts)


def iter_paths() -> tuple[list[pathlib.Path], list[pathlib.Path]]:
    dirs: list[pathlib.Path] = []
    files: list[pathlib.Path] = []
    for current, dirnames, filenames in os.walk(root):
        current_path = pathlib.Path(current)
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        if should_skip(current_path):
            continue
        dirs.append(current_path)
        for filename in sorted(filenames):
            file_path = current_path / filename
            if not should_skip(file_path):
                files.append(file_path)
    return sorted(dirs), sorted(files)


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def line_count(path: pathlib.Path) -> int | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def rel(path: pathlib.Path) -> str:
    if path == root:
        return "."
    return path.relative_to(root).as_posix()


def collect() -> dict[str, Any]:
    started = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    dirs, files = iter_paths()
    git_head_rc, git_head, _ = run(["git", "rev-parse", "--short=12", "HEAD"])
    git_branch_rc, git_branch, _ = run(["git", "branch", "--show-current"])
    git_status_rc, git_status, _ = run(["git", "status", "--short"])
    tracked_rc, tracked_stdout, _ = run(["git", "ls-files"])
    tracked = set(tracked_stdout.splitlines()) if tracked_rc == 0 else set()

    directory_rows = []
    for directory in dirs:
        st = directory.stat()
        directory_rows.append(
            {
                "path": rel(directory),
                "mode": stat.filemode(st.st_mode),
                "modified_utc": utc_from_timestamp(st.st_mtime),
            }
        )

    file_rows = []
    empty_files = []
    placeholder_matches = []
    markdown_failures = []
    shell_scripts = []

    for file_path in files:
        st = file_path.stat()
        relative = rel(file_path)
        lines = line_count(file_path)
        executable = bool(st.st_mode & stat.S_IXUSR)
        row = {
            "path": relative,
            "tracked": relative in tracked,
            "mode": stat.filemode(st.st_mode),
            "bytes": st.st_size,
            "lines": lines,
            "sha256": file_sha256(file_path),
            "modified_utc": utc_from_timestamp(st.st_mtime),
            "executable": executable,
        }
        file_rows.append(row)
        if st.st_size == 0 and relative != ".gitkeep":
            empty_files.append(relative)
        if file_path.suffix in {".md", ".sh", ".py", ".yml", ".yaml", ".json", ".txt"}:
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = ""
            for number, line in enumerate(text.splitlines(), start=1):
                if GAP_MARKER_RE.search(line) and relative not in {"scripts/repository_audit_report.sh", "scripts/validate_repository.sh"}:
                    placeholder_matches.append({"path": relative, "line": number, "text": line.strip()[:180]})
            if file_path.suffix == ".md":
                for raw_link in MARKDOWN_LINK_RE.findall(text):
                    target = raw_link.split("#", 1)[0].strip()
                    if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                        continue
                    candidate = (file_path.parent / target).resolve()
                    if not str(candidate).startswith(str(root)) or not candidate.exists():
                        markdown_failures.append({"path": relative, "target": raw_link})
        if file_path.suffix == ".sh":
            rc, _, stderr = run(["bash", "-n", relative])
            shell_scripts.append({"path": relative, "syntax_ok": rc == 0, "stderr": stderr})

    tools = {}
    for tool, version_args in {
        "bash": ["bash", "--version"],
        "git": ["git", "--version"],
        "python3": ["python3", "--version"],
        "curl": ["curl", "--version"],
    }.items():
        rc, stdout, stderr = run(version_args)
        first_line = (stdout or stderr).splitlines()[0] if (stdout or stderr) else "not available"
        tools[tool] = {"available": rc == 0, "version": first_line}

    finished = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "1.0",
        "started_utc": started,
        "finished_utc": finished,
        "repository": str(root),
        "git": {
            "head": git_head if git_head_rc == 0 else "unavailable",
            "branch": git_branch if git_branch_rc == 0 and git_branch else "detached-or-unavailable",
            "status_short": git_status.splitlines() if git_status_rc == 0 and git_status else [],
        },
        "tools": tools,
        "summary": {
            "directories": len(directory_rows),
            "files": len(file_rows),
            "tracked_files": sum(1 for row in file_rows if row["tracked"]),
            "empty_files_except_gitkeep": len(empty_files),
            "content_gap_matches": len(placeholder_matches),
            "markdown_link_failures": len(markdown_failures),
            "shell_scripts": len(shell_scripts),
            "shell_syntax_failures": sum(1 for row in shell_scripts if not row["syntax_ok"]),
        },
        "directories": directory_rows,
        "files": file_rows,
        "empty_files_except_gitkeep": empty_files,
        "content_gap_matches": placeholder_matches,
        "markdown_link_failures": markdown_failures,
        "shell_scripts": shell_scripts,
    }


def emit_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Live Repository Audit Report",
        "",
        f"- Started UTC: `{data['started_utc']}`",
        f"- Finished UTC: `{data['finished_utc']}`",
        f"- Repository: `{data['repository']}`",
        f"- Git branch: `{data['git']['branch']}`",
        f"- Git HEAD: `{data['git']['head']}`",
        f"- Dirty entries: `{len(data['git']['status_short'])}`",
        "",
        "## Summary",
        "",
    ]
    for key, value in data["summary"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Tool Versions", ""])
    for tool, info in sorted(data["tools"].items()):
        lines.append(f"- {tool}: `{info['version']}`")
    lines.extend(["", "## Directories", "", "| Path | Mode | Modified UTC |", "| --- | --- | --- |"])
    for row in data["directories"]:
        lines.append(f"| `{row['path']}` | `{row['mode']}` | `{row['modified_utc']}` |")
    lines.extend(["", "## Files", "", "| Path | Tracked | Mode | Bytes | Lines | SHA-256 | Modified UTC |", "| --- | --- | --- | ---: | ---: | --- | --- |"])
    for row in data["files"]:
        lines.append(
            f"| `{row['path']}` | `{str(row['tracked']).lower()}` | `{row['mode']}` | "
            f"{row['bytes']} | {'' if row['lines'] is None else row['lines']} | `{row['sha256']}` | `{row['modified_utc']}` |"
        )
    lines.extend(["", "## Quality Findings", ""])
    if not data["empty_files_except_gitkeep"] and not data["content_gap_matches"] and not data["markdown_link_failures"] and data["summary"]["shell_syntax_failures"] == 0:
        lines.append("- No local content gaps detected by this audit.")
    else:
        for item in data["empty_files_except_gitkeep"]:
            lines.append(f"- Empty file: `{item}`")
        for item in data["content_gap_matches"]:
            lines.append(f"- Content gap marker: `{item['path']}:{item['line']}`")
        for item in data["markdown_link_failures"]:
            lines.append(f"- Markdown link failure: `{item['path']}` -> `{item['target']}`")
        for item in data["shell_scripts"]:
            if not item["syntax_ok"]:
                lines.append(f"- Shell syntax failure: `{item['path']}`")
    lines.append("")
    return "\n".join(lines)


audit = collect()
if report_format == "json":
    print(json.dumps(audit, indent=2, sort_keys=True))
else:
    print(emit_markdown(audit))
PY
  printf 'wrote audit report: %s\n' "$output_path" >&2
else
  "$python_bin" - "$repo_root" "$report_format" <<'PY'
from __future__ import annotations

# The implementation is intentionally loaded from this script itself when --output
# is not used, keeping behavior identical without maintaining two code paths.
import pathlib
import subprocess
import sys

import tempfile

repo_root = pathlib.Path(sys.argv[1]).resolve()
report_format = sys.argv[2]
with tempfile.NamedTemporaryFile(prefix="upgraded-fiesta-audit-", suffix=".tmp", delete=False) as handle:
    temp_path = pathlib.Path(handle.name)
try:
    command = ["bash", str(repo_root / "scripts" / "repository_audit_report.sh"), "--output", str(temp_path), "--format", report_format]
    proc = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.exit(proc.returncode)
    sys.stdout.write(temp_path.read_text(encoding="utf-8"))
finally:
    temp_path.unlink(missing_ok=True)
PY
fi
