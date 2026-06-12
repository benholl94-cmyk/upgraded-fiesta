#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

usage() {
  cat <<'USAGE'
Usage: scripts/iphone_local_dev_bootstrap.sh [--dry-run] [--profile PATH]

Idempotent bootstrap for an iPhone-local developer shell in a-Shell or iSH.
It creates a stable Developer directory tree, writes a reusable shell profile
fragment, and prints live diagnostics without overwriting user-owned secrets.

Environment inputs are optional:
  GIT_AUTHOR_NAME   Git display name to configure when non-empty.
  GIT_AUTHOR_EMAIL  Git commit email to configure when non-empty.
USAGE
}

dry_run=false
profile_path="${HOME}/.iphone-local-dev-profile"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) dry_run=true; shift ;;
    --profile)
      [[ $# -ge 2 ]] || { printf 'Missing value for --profile\n' >&2; exit 64; }
      profile_path="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 64 ;;
  esac
done

run() {
  printf '+ %q' "$1"
  shift || true
  for arg in "$@"; do printf ' %q' "$arg"; done
  printf '\n'
  if [[ "$dry_run" == false ]]; then
    "$@"
  fi
}

write_file() {
  local path="$1"
  local tmp
  tmp="$(mktemp)"
  cat > "$tmp"
  if [[ "$dry_run" == true ]]; then
    printf '+ write %s\n' "$path"
    cat "$tmp"
    rm -f "$tmp"
    return 0
  fi
  mkdir -p "$(dirname "$path")"
  if [[ -f "$path" ]] && cmp -s "$tmp" "$path"; then
    printf 'unchanged: %s\n' "$path"
    rm -f "$tmp"
  else
    mv "$tmp" "$path"
    chmod 600 "$path"
    printf 'wrote: %s\n' "$path"
  fi
}

printf 'iPhone local developer bootstrap started at %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf 'Shell: %s\n' "${SHELL:-unknown}"
printf 'Home: %s\n' "$HOME"

base_dir="${IPHONE_DEV_HOME:-${HOME}/Developer}"
for dir in repos scratch keys exports backups logs; do
  if [[ "$dry_run" == true ]]; then
    printf '+ mkdir -p %q\n' "${base_dir}/${dir}"
  else
    mkdir -p "${base_dir}/${dir}"
  fi
done

write_file "$profile_path" <<'PROFILE'
# iPhone-local development profile. Source from ~/.profile or app-specific shell rc.
export IPHONE_DEV_HOME="${IPHONE_DEV_HOME:-$HOME/Developer}"
export DEV_HOST="${DEV_HOST:-127.0.0.1}"
export DEV_BIND="${DEV_BIND:-127.0.0.1}"
export DEV_PORT="${DEV_PORT:-8000}"
export DEV_ALT_PORT="${DEV_ALT_PORT:-3000}"
export DEV_URL="http://${DEV_HOST}:${DEV_PORT}"
export LOCALHOST_URL="$DEV_URL"
export NO_PROXY="localhost,127.0.0.1,::1,*.local${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"
export PYTHONUNBUFFERED=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export npm_config_audit=false
export npm_config_fund=false
export EDITOR="${EDITOR:-vim}"
alias ll='ls -la'
alias py='python3'
alias serve='python3 -m http.server "$DEV_PORT" --bind "$DEV_BIND"'
PROFILE

if command -v git >/dev/null 2>&1; then
  if [[ -n "${GIT_AUTHOR_NAME:-}" ]]; then
    if [[ "$dry_run" == true ]]; then printf '+ git config --global user.name %q\n' "$GIT_AUTHOR_NAME"; else git config --global user.name "$GIT_AUTHOR_NAME"; fi
  fi
  if [[ -n "${GIT_AUTHOR_EMAIL:-}" ]]; then
    if [[ "$dry_run" == true ]]; then printf '+ git config --global user.email %q\n' "$GIT_AUTHOR_EMAIL"; else git config --global user.email "$GIT_AUTHOR_EMAIL"; fi
  fi
  if [[ "$dry_run" == true ]]; then
    printf '+ git config --global init.defaultBranch main\n'
    printf '+ git config --global pull.ff only\n'
  else
    git config --global init.defaultBranch main
    git config --global pull.ff only
  fi
fi

printf '\nLive diagnostics\n'
printf 'UTC datetime: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf 'Local datetime: %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
for tool in git python3 node curl ssh; do
  if command -v "$tool" >/dev/null 2>&1; then
    if [[ "$tool" == "ssh" ]]; then
      version="$(ssh -V 2>&1 | head -n 1 || true)"
    else
      version="$($tool --version 2>&1 | head -n 1 || true)"
    fi
    printf '%s: %s\n' "$tool" "$version"
  else
    printf '%s: not installed or not exposed in this shell\n' "$tool"
  fi
done

cat <<NEXT

Next step:
  Add this line to ~/.profile or the shell startup file used by the app:
  . "$profile_path"
NEXT

printf 'iPhone local developer bootstrap finished at %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
