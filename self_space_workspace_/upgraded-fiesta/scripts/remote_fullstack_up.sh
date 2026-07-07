#!/usr/bin/env sh
set -eu

REPO_URL=${REPO_URL:-https://github.com/benholl94-cmyk/upgraded-fiesta.git}
APP_DIR=${APP_DIR:-$HOME/upgraded-fiesta}
BRANCH=${BRANCH:-main}

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: missing required command: $1" >&2
    exit 1
  }
}

need git
need docker

docker compose version >/dev/null 2>&1 || {
  echo 'ERROR: docker compose plugin is required.' >&2
  exit 1
}

if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  cd "$APP_DIR"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git reset --hard "origin/$BRANCH"
fi

cd "$APP_DIR"

if [ ! -f .env ]; then
  cp .env.production.example .env
  echo 'Created .env from .env.production.example. Edit POSTGRES_PASSWORD, then rerun this command.' >&2
  exit 1
fi

sh scripts/fullstack_up.sh
