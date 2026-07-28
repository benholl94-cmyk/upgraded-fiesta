#!/usr/bin/env python3
"""Apply Issue #94 workflow-file fixes via a Master-supplied PAT.

This script:
1. Writes the staged auto-rollback.yml to .github/workflows/
2. Applies the ci.yml patch
3. Switches the git remote URL to use the PAT
4. Pushes to main

The script does NOT modify any source-of-truth: it only stages pre-prepared
content from docs/maintenance/issue-94/. It exits with a clear error if
the PAT is missing.

Usage:
    PAT=ghp_xxx... python3 docs/maintenance/issue-94/apply_fix.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ISSUE_DIR = Path(__file__).resolve().parent
AUTO_ROLLBACK_SRC = ISSUE_DIR / "auto-rollback.yml"
AUTO_ROLLBACK_DST = REPO_ROOT / ".github/workflows/auto-rollback.yml"
CI_PATCH = ISSUE_DIR / "ci.yml.patch"
CI_TARGET = REPO_ROOT / ".github/workflows/ci.yml"


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kwargs)


def main() -> int:
    pat = os.environ.get("PAT")
    if not pat:
        print("ERROR: PAT env var is required", file=sys.stderr)
        print("  PAT=ghp_xxx... python3 docs/maintenance/issue-94/apply_fix.py",
              file=sys.stderr)
        return 1

    if not AUTO_ROLLBACK_SRC.is_file():
        print(f"ERROR: {AUTO_ROLLBACK_SRC} missing", file=sys.stderr)
        return 1
    if not CI_PATCH.is_file():
        print(f"ERROR: {CI_PATCH} missing", file=sys.stderr)
        return 1

    print("Step 1: copy auto-rollback.yml into workflows dir")
    AUTO_ROLLBACK_DST.parent.mkdir(parents=True, exist_ok=True)
    AUTO_ROLLBACK_DST.write_bytes(AUTO_ROLLBACK_SRC.read_bytes())

    print("Step 2: apply ci.yml patch")
    run(["git", "apply", str(CI_PATCH)])

    print("Step 3: verify the patched files parse as valid YAML")
    import yaml
    for path in (AUTO_ROLLBACK_DST, CI_TARGET):
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
            print(f"  {path.name}: OK")
        except yaml.YAMLError as e:
            print(f"  {path.name}: BROKEN -- {e}", file=sys.stderr)
            return 2

    print("Step 4: switch git remote URL to PAT-based auth")
    repo_url = run(["git", "remote", "get-url", "origin"]).stdout.strip()
    if pat in repo_url:
        print("  remote already uses PAT, skipping")
    else:
        # Replace https://...@github.com/... token with new PAT
        new_url = repo_url.replace("https://", f"https://x-access-token:{pat}@", 1) \
            if "@" not in repo_url.split("//", 1)[1] else repo_url
        # If there's already a token in the URL, replace it
        if "@github.com" in repo_url:
            prefix, suffix = repo_url.split("@github.com", 1)
            new_url = f"https://x-access-token:{pat}@github.com{suffix}"
        run(["git", "remote", "set-url", "origin", new_url])
        print(f"  remote URL updated")

    print("Step 5: commit and push")
    run(["git", "add", str(AUTO_ROLLBACK_DST), str(CI_TARGET)])
    run(["git", "commit", "-m", "fix(workflows): Issue #94 — ci.yml + auto-rollback.yml"])
    run(["git", "push", "origin", "HEAD:main"])

    print("Done. Issue #94 should be resolved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
