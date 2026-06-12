#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

utc_now="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf 'Repository validation started at %s\n' "$utc_now"
printf 'Repository: %s\n' "$repo_root"

failures=0
warn() { printf 'WARN: %s\n' "$*" >&2; }
fail() { printf 'FAIL: %s\n' "$*" >&2; failures=$((failures + 1)); }
pass() { printf 'PASS: %s\n' "$*"; }

required_paths=(
  "README.md"
  "docs/iphone-local-dev-setup.md"
  "scripts/codex_cloud_setup.sh"
  "scripts/iphone_local_dev_bootstrap.sh"
  "scripts/validate_repository.sh"
)

for path in "${required_paths[@]}"; do
  if [[ -s "$path" ]]; then
    pass "required file exists and is non-empty: $path"
  else
    fail "required file is missing or empty: $path"
  fi
done

while IFS= read -r file; do
  [[ -n "$file" ]] || continue
  if [[ "$file" == ".gitkeep" ]]; then
    pass "tracked directory sentinel may be empty: $file"
  elif [[ ! -s "$file" ]]; then
    fail "tracked file is empty: $file"
  fi
done < <(git ls-files)

placeholder_regex='(TODO|FIXME|TBD|PLACEHOLDER|CHANGEME|your-|your_|dein-|deine-|<[^>]+>|\.\.\.|xxx|dummy|sample-token|api[_-]?key|password-here)'
if matches="$(rg -n --hidden -g '!\.git' -g '!node_modules' -g '!Pods' -g '!DerivedData' -g '!build' -g '!scripts/validate_repository.sh' -e "$placeholder_regex" . || true)"; then
  if [[ -n "$matches" ]]; then
    printf '%s\n' "$matches" >&2
    fail "unresolved placeholder markers were found"
  else
    pass "no unresolved placeholder markers found"
  fi
fi

for script in scripts/*.sh; do
  [[ -f "$script" ]] || continue
  bash -n "$script" && pass "shell syntax valid: $script" || fail "shell syntax invalid: $script"
  if [[ -x "$script" ]]; then
    pass "script is executable: $script"
  else
    fail "script is not executable: $script"
  fi
done

python3 - <<'PY'
from __future__ import annotations
import pathlib
import re
import sys

root = pathlib.Path.cwd()
failed = False
link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
for md in sorted(root.glob("**/*.md")):
    if ".git" in md.parts:
        continue
    text = md.read_text(encoding="utf-8")
    for raw in link_re.findall(text):
        target = raw.split("#", 1)[0].strip()
        if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            continue
        candidate = (md.parent / target).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            print(f"FAIL: markdown link leaves repository: {md.relative_to(root)} -> {raw}", file=sys.stderr)
            failed = True
            continue
        if not candidate.exists():
            print(f"FAIL: broken markdown link: {md.relative_to(root)} -> {raw}", file=sys.stderr)
            failed = True
if failed:
    sys.exit(1)
print("PASS: local markdown links resolve")
PY
case $? in
  0) ;;
  *) fail "markdown local link validation failed" ;;
esac

if git diff --check -- .; then
  pass "git diff whitespace check passed"
else
  fail "git diff whitespace check failed"
fi

if [[ "$failures" -gt 0 ]]; then
  printf 'Repository validation finished with %d failure(s).\n' "$failures" >&2
  exit 1
fi

printf 'Repository validation finished successfully at %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
