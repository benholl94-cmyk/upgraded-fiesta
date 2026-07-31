#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Codex fullstack check failed: required command not found: $cmd" >&2
    exit 1
  fi
}

echo "Codex fullstack check for upgraded-fiesta"
echo "Repository: $ROOT"

require_cmd python3
require_cmd cargo
require_cmd npm

python3 scripts/validate_repo.py

if cargo fmt --version >/dev/null 2>&1; then
  cargo fmt --all -- --check
else
  echo "cargo fmt not available; skipping Rust formatting check" >&2
fi

cargo check --workspace
cargo test --workspace

if [[ -f ui/package.json ]]; then
  (
    cd ui
    npm install --package-lock=false --no-audit --no-fund
    npm run build
  )
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  # `docker compose config` prueft die SYNTAX der Compose-Datei. Weil
  # docker-compose.yml HM_OWNER_TOKEN als Pflichtvariable interpoliert,
  # scheiterte dieser Schritt auf jedem frischen Checkout ohne exportiertes
  # Token -- und damit die gesamte Pruefung, mit Exit 1, obwohl fmt, check,
  # test und der UI-Build alle durchgelaufen waren.
  #
  # Ein fehlendes Token ist hier keine Aussage ueber das Repo: es ist eine
  # Startsperre fuer den BETRIEB, nicht fuer die Syntaxpruefung. Eine
  # Vorabpruefung, die an etwas scheitert, das die Sache gar nicht betrifft,
  # wird beim zweiten Mal umgangen -- dieselbe Lehre wie beim
  # Vorschalt-Check von hugin_clarity.py.
  #
  # Der Platzhalter wird ausschliesslich hier gesetzt und nie exportiert;
  # ein tatsaechlich gesetztes Token gewinnt.
  # Zwei Pflichtvariablen, nicht eine. Die erste Fassung setzte nur
  # HM_OWNER_TOKEN -- POSTGRES_PASSWORD interpoliert docker-compose.yml
  # ebenso mit `:?`, also scheiterte der Schritt weiterhin auf jedem frischen
  # Checkout. Der Fix war beschrieben und wirkungslos; gemessen mit
  # `docker compose config`, das prompt nach POSTGRES_PASSWORD verlangte.
  #
  # Beide Platzhalter gelten nur fuer diesen Aufruf und werden nie
  # exportiert; tatsaechlich gesetzte Werte gewinnen.
  HM_OWNER_TOKEN="${HM_OWNER_TOKEN:-compose-syntax-check-only}" \
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-compose-syntax-check-only}" \
    docker compose config >/dev/null
else
  echo "docker compose not available; skipping Compose syntax check" >&2
fi

echo "Codex fullstack check complete."
