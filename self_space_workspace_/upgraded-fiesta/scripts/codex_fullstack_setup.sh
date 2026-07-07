#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Codex setup failed: required command not found: $cmd" >&2
    exit 1
  fi
}

echo "Codex fullstack setup for upgraded-fiesta"
echo "Repository: $ROOT"

require_cmd python3
require_cmd cargo
require_cmd npm

python3 scripts/validate_repo.py

if command -v rustup >/dev/null 2>&1; then
  rustup component add rustfmt clippy >/dev/null || true
fi

cargo fetch
cargo check --workspace

if [[ -f ui/package.json ]]; then
  (
    cd ui
    npm install --package-lock=false --no-audit --no-fund
    npm run build
  )
fi

echo "Codex fullstack setup complete."
