#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

fail() {
  printf 'Validation failed: %s\n' "$1" >&2
  exit 1
}

require_file() {
  local file="$1"
  [[ -f "$file" ]] || fail "missing required file: $file"
}

require_text() {
  local file="$1"
  local pattern="$2"
  local label="$3"

  if ! rg --quiet --fixed-strings -- "$pattern" "$file"; then
    fail "$file is missing $label: $pattern"
  fi
}

reject_text() {
  local file="$1"
  local pattern="$2"
  local label="$3"

  if rg --quiet --fixed-strings -- "$pattern" "$file"; then
    fail "$file contains disallowed $label: $pattern"
  fi
}

printf 'Validating static iPhone control-plane...\n'

require_file "README.md"
require_file "docs/iphone-local-dev-setup.md"

require_text "README.md" "docs/iphone-local-dev-setup.md" "link to the full setup guide"
require_text "README.md" "Stand der geprüften App-/Tool-Informationen: 2026-06-12" "review date"

required_sections=(
  "## 1. Zielbild"
  "## 2. Realistische Grenzen von iOS"
  "## 3. Empfohlene App-Rollen"
  "## 6. Git mit Working Copy einrichten"
  "## 7. a-Shell einrichten"
  "## 8. iSH einrichten"
  "## 10. Lokale Web-Entwicklung"
  "## 11. Internet-Grundlagen und Online-Arbeit"
  "## 13. Sicherheit"
  "## 14. Backup-Strategie"
  "## 16. Fehlerbehebung"
  "## 17. Minimal-Checkliste"
)

for section in "${required_sections[@]}"; do
  require_text "docs/iphone-local-dev-setup.md" "$section" "control-plane section"
done

require_text "docs/iphone-local-dev-setup.md" "export DEV_HOST=127.0.0.1" "private localhost default"
require_text "docs/iphone-local-dev-setup.md" "export DEV_BIND=127.0.0.1" "private bind default"
require_text "docs/iphone-local-dev-setup.md" "export NO_PROXY=\"localhost,127.0.0.1,::1,*.local\"" "local proxy bypass"
require_text "docs/iphone-local-dev-setup.md" 'Nutze `0.0.0.0` nur' "explicit LAN exposure warning"
require_text "docs/iphone-local-dev-setup.md" 'Teile niemals `id_ed25519`, sondern nur `id_ed25519.pub`.' "SSH secret handling warning"
require_text "docs/iphone-local-dev-setup.md" 'Führe unbekannte Shell-Skripte nicht blind mit `curl ... | sh` aus' "download safety warning"

reject_text "docs/iphone-local-dev-setup.md" "curl -fsSL" "pipe-to-shell bootstrap pattern"
reject_text "docs/iphone-local-dev-setup.md" "docker run" "desktop/container assumption"
reject_text "docs/iphone-local-dev-setup.md" "brew install" "macOS desktop package-manager assumption"

printf 'Static iPhone control-plane validation passed.\n'
