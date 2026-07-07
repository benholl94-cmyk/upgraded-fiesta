#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

echo "Codex maintenance for upgraded-fiesta"
echo "Repository: $ROOT"

python3 scripts/validate_repo.py

if command -v cargo >/dev/null 2>&1; then
  cargo fetch
else
  echo "cargo not available; skipping Rust dependency refresh" >&2
fi

if [[ -f ui/package.json ]] && command -v npm >/dev/null 2>&1; then
  (
    cd ui
    npm install --package-lock=false --no-audit --no-fund --prefer-offline
  )
else
  echo "npm not available or ui/package.json missing; skipping UI dependency refresh" >&2
fi

echo "Codex maintenance complete."
