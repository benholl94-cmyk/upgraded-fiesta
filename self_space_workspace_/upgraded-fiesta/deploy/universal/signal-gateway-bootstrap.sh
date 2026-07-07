#!/usr/bin/env sh
set -eu

APP_DIR="${APP_DIR:-/opt/upgraded-fiesta-signal}"
REPO_RAW_BASE="${REPO_RAW_BASE:-https://raw.githubusercontent.com/benholl94-cmyk/upgraded-fiesta/main}"
ENV_FILE="$APP_DIR/.env.signal.local"
COMPOSE_FILE="$APP_DIR/docker-compose.signal.yml"
STATE_DIR="$APP_DIR/data/signal-cli"

log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

fail() {
  log "ERROR $*"
  exit 1
}

require_root() {
  if [ "$(id -u)" != "0" ]; then
    fail "run as root or with sudo"
  fi
}

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y ca-certificates curl docker.io docker-compose-plugin ufw
    return
  fi
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y ca-certificates curl docker ufw || dnf install -y ca-certificates curl docker firewalld
    return
  fi
  fail "unsupported package manager; install Docker and curl manually"
}

configure_firewall() {
  if command -v ufw >/dev/null 2>&1; then
    ufw default deny incoming || true
    ufw default allow outgoing || true
    ufw allow OpenSSH || true
    ufw --force enable || true
  fi
}

write_env_if_missing() {
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
}

main() {
  require_root
  install_packages
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR" || true
  curl -fsSL "$REPO_RAW_BASE/integrations/signal-cli/docker-compose.signal.yml" -o "$COMPOSE_FILE"
  write_env_if_missing
  systemctl enable --now docker 2>/dev/null || service docker start 2>/dev/null || true
  configure_firewall
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d
  docker ps
  log "gateway bootstrap complete"
  log "server-local check: curl -fsS http://127.0.0.1:9922/v1/about"
  log "iPhone tunnel: ssh -L 9922:127.0.0.1:9922 root@SERVER_IP"
}

main "$@"
