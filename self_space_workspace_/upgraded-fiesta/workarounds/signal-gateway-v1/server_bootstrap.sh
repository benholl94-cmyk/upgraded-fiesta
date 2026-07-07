#!/usr/bin/env sh
set -eu

VERSION="1.0.0"
APP_DIR="/opt/upgraded-fiesta-signal"
STATE_DIR="$APP_DIR/data/signal-cli"
ENV_FILE="$APP_DIR/.env.signal.local"
COMPOSE_FILE="$APP_DIR/docker-compose.signal.yml"
RAW_BASE="https://raw.githubusercontent.com/benholl94-cmyk/upgraded-fiesta/main"

log() {
  printf '%s signal-gateway-v1[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$VERSION" "$*"
}

fail() {
  log "ERROR $*"
  exit 1
}

[ "$(id -u)" = "0" ] || fail "run as root"

if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl docker.io docker-compose-plugin ufw
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y ca-certificates curl docker ufw || dnf install -y ca-certificates curl docker firewalld
else
  fail "unsupported package manager"
fi

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR" || true

curl -fsSL "$RAW_BASE/integrations/signal-cli/docker-compose.signal.yml" -o "$COMPOSE_FILE"

if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<'EOF'
SIGNAL_CLI_MODE=json-rpc-native
SIGNAL_BIND_HOST=127.0.0.1
SIGNAL_BIND_PORT=9922
SIGNAL_STATE_DIR=/opt/upgraded-fiesta-signal/data/signal-cli
SIGNAL_AUTO_RECEIVE_SCHEDULE=
SIGNAL_API_BASE_URL=http://127.0.0.1:9922
SIGNAL_ACCOUNT_NUMBER=+4900000000000
SIGNAL_TEST_RECIPIENT=+4900000000000
EOF
  chmod 600 "$ENV_FILE" || true
fi

systemctl enable --now docker 2>/dev/null || service docker start 2>/dev/null || true

if command -v ufw >/dev/null 2>&1; then
  ufw default deny incoming || true
  ufw default allow outgoing || true
  ufw allow OpenSSH || true
  ufw --force enable || true
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d

docker ps > "$APP_DIR/docker-ps.txt"
printf '%s\n' "$VERSION" > "$APP_DIR/workaround-version.txt"

log "complete"
log "check on server: curl -fsS http://127.0.0.1:9922/v1/about"
