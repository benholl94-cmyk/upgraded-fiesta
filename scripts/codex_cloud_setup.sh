#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

printf 'Codex cloud setup for upgraded-fiesta\n'
printf 'Repository: %s\n' "$repo_root"

required_files=(
  "README.md"
  "docs/iphone-local-dev-setup.md"
  "scripts/iphone_local_dev_bootstrap.sh"
  "scripts/validate_repository.sh"
)

for file in "${required_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    printf 'Missing required file: %s\n' "$file" >&2
    exit 1
  fi
done

printf 'Running repository validation.\n'
"$repo_root/scripts/validate_repository.sh"
printf 'No dependency installation required. Documentation and scripts are production-ready.\n'
