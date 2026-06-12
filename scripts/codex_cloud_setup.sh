#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

printf 'Codex cloud setup for upgraded-fiesta\n'
printf 'Repository: %s\n' "$repo_root"

scripts/validate_iphone_control_plane.sh

printf 'No dependency installation required. Static iPhone control-plane validation passed.\n'
