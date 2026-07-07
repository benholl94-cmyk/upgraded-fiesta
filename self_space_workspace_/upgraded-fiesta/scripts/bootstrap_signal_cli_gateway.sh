#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
INTEGRATION_DIR="$ROOT_DIR/integrations/signal-cli"
ENV_FILE="$INTEGRATION_DIR/.env.signal.local"
ENV_EXAMPLE="$INTEGRATION_DIR/signal.env.example"
COMPOSE_FILE="$INTEGRATION_DIR/docker-compose.signal.yml"

log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

fail() {
  log "ERROR $*"
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "docker is not installed or not in PATH"
docker compose version >/dev/null 2>&1 || fail "docker compose plugin is not available"
[ -f "$COMPOSE_FILE" ] || fail "missing compose file: $COMPOSE_FILE"

mkdir -p "$INTEGRATION_DIR/data/signal-cli"
chmod 700 "$INTEGRATION_DIR/data/signal-cli" 2>/dev/null || true

if [ ! -f "$ENV_FILE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  chmod 600 "$ENV_FILE" 2>/dev/null || true
  log "created $ENV_FILE from example; edit phone numbers before send tests"
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

log "starting signal-cli REST gateway"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d

log "waiting for gateway health"
tries=0
until docker inspect --format='{{json .State.Health.Status}}' upgraded-fiesta-signal-api 2>/dev/null | grep -q 'healthy'; do
  tries=$((tries + 1))
  if [ "$tries" -ge 20 ]; then
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps || true
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail=120 || true
    fail "signal gateway did not become healthy"
  fi
  sleep 3
done

log "signal gateway is healthy"
log "local API: ${SIGNAL_API_BASE_URL:-http://127.0.0.1:9922}"
log "next: register/link a Signal account, then run scripts/signal_cli_smoke_test.py"
