#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
mkdir -p logs
if ! python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()" >/dev/null 2>&1; then
  python3 scripts/ashell_fullstack_up.py > logs/ashell_fullstack.log 2>&1 &
  sleep 2
fi
sh scripts/ashell_fullstack_check.sh
