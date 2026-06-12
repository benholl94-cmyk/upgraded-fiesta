#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

printf 'Codex cloud setup for upgraded-fiesta\n'
printf 'Repository: %s\n' "$repo_root"

required_files=(
  "README.md"
  "docs/iphone-local-dev-setup.md"
)

for file in "${required_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    printf 'Missing required file: %s\n' "$file" >&2
    exit 1
  fi
done

# This repository currently contains documentation only, so no package
# installation is required. Keep the script intentionally lightweight and
# deterministic for Codex/cloud bootstrap jobs.
printf 'No dependency installation required. Documentation files are present.\n'
