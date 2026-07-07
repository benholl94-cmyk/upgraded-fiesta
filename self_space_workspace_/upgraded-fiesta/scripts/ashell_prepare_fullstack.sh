#!/usr/bin/env sh
set -eu

ROOT=${ROOT:-$HOME/Documents/Developer/upgraded-fiesta.git}
mkdir -p "$HOME/Documents/Developer"

if [ -d "$ROOT/.git" ]; then
  cd "$ROOT"
  git pull || true
else
  git clone https://github.com/benholl94-cmyk/upgraded-fiesta.git "$ROOT"
  cd "$ROOT"
fi

if [ ! -f .env ]; then
  cp .env.production.example .env
fi

echo "Prepared repository: $ROOT"
echo "Edit .env without nano: python3 - <<'PY'"
echo "from pathlib import Path"
echo "p=Path('.env')"
echo "s=p.read_text().replace('POSTGRES_PASSWORD=change-me-before-use','POSTGRES_PASSWORD=CHANGE_THIS_SECRET')"
echo "p.write_text(s)"
echo "PY"
echo "Docker must run on a Linux server, not inside a-Shell."
