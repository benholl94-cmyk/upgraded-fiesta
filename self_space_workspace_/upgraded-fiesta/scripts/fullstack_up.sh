#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if [ ! -f .env ]; then
  if [ -f .env.production.example ]; then
    cp .env.production.example .env
  fi
fi

if grep -q '^POSTGRES_PASSWORD=change-me-before-use$' .env; then
  echo 'ERROR: set a real POSTGRES_PASSWORD in .env before starting the stack.' >&2
  exit 1
fi

python3 scripts/validate_repo.py
docker compose -f deploy/fullstack-compose.yml config >/dev/null
docker compose -f deploy/fullstack-compose.yml up -d --build --remove-orphans
docker compose -f deploy/fullstack-compose.yml ps
