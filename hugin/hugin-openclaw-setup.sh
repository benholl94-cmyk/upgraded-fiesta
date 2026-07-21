#!/bin/sh
# ============================================================================
# hugin-openclaw-setup.sh  ·  v1.1.0
# Richtet OpenClaw als kostenlose ($0) Arbeits-Engine für HUGIN ein.
#
# Ergebnis: ein OpenClaw-Gateway, das
#   - auf der freien Cerebras-Stufe läuft (1M Token/Tag, kein Kreditkartenzwang)
#   - echte Werkzeuge hat (Datei, Web, Speicher, Cron) via tools.profile "coding"
#   - die OpenAI-kompatible Schnittstelle /v1/chat/completions bereitstellt
#   - über ein Operator-Token abgesichert ist (idempotent: Token wird wiederverwendet)
# HUGIN verbindet sich danach über Gateway-URL + Token (⚙ → Arbeits-Engine).
#
# Nur dokumentierte OpenClaw-CLI/Config wird verwendet. Keine Platzhalter.
# Referenz: https://docs.openclaw.ai/gateway  ·  /gateway/config-tools
# POSIX sh, idempotent, fail-fast.
# ============================================================================
set -eu

PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
BIND="${HUGIN_BIND:-loopback}"          # loopback | lan | tailnet
MODEL_PRIMARY="cerebras/llama-4-scout"
MODEL_FALLBACK="cerebras/llama-3.3-70b"
TOKEN_FILE="${HOME}/.openclaw/hugin_gateway_token"

say(){ printf '\033[36m▸ %s\033[0m\n' "$1"; }
warn(){ printf '\033[33m! %s\033[0m\n' "$1"; }
die(){ printf '\033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

# --- 1. Voraussetzungen ------------------------------------------------------
command -v openclaw >/dev/null 2>&1 || die "openclaw nicht gefunden. Installation: npm install -g openclaw (Node.js erforderlich)."

say "OpenClaw gefunden: $(openclaw --version 2>/dev/null || echo '?')"

# --- 2. Cerebras-Key (frei) einsammeln --------------------------------------
if [ -z "${CEREBRAS_API_KEY:-}" ]; then
  printf 'Cerebras API-Key (frei von https://cloud.cerebras.ai — kein Kreditkartenzwang): '
  read -r CEREBRAS_API_KEY
  [ -n "$CEREBRAS_API_KEY" ] || die "Kein Cerebras-Key angegeben."
fi

# --- 3. Operator-Token erzeugen oder wiederverwenden (idempotent) ------------
mkdir -p "$(dirname "$TOKEN_FILE")"
if [ -f "$TOKEN_FILE" ] && [ -s "$TOKEN_FILE" ]; then
  GW_TOKEN="$(cat "$TOKEN_FILE")"
  say "Vorhandenes Gateway-Token wiederverwendet (idempotent)"
else
  if command -v openssl >/dev/null 2>&1; then
    GW_TOKEN="$(openssl rand -hex 24)"
  else
    # POSIX-Fallback: dd + od (breiter Plattform-Support ohne openssl)
    GW_TOKEN="$(dd if=/dev/urandom bs=24 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')"
  fi
  [ -n "$GW_TOKEN" ] || die "Token-Erzeugung fehlgeschlagen."
  printf '%s' "$GW_TOKEN" > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
  say "Neues Gateway-Token erzeugt und gespeichert"
fi

# --- 4. Baseline-Setup -------------------------------------------------------
say "Baseline-Konfiguration (openclaw setup)"
openclaw setup >/dev/null 2>&1 || openclaw --dev setup >/dev/null 2>&1 || warn "setup meldete Warnungen — fahre fort."

# --- 5. Freies Modell (Cerebras) als Primär-Provider -------------------------
say "Cerebras als kostenlose Arbeits-Engine einrichten (llama-4-scout)"
openclaw config set env.CEREBRAS_API_KEY "$CEREBRAS_API_KEY"

openclaw config set models.providers.cerebras '{
  "baseUrl": "https://api.cerebras.ai/v1",
  "apiKey": "${CEREBRAS_API_KEY}",
  "api": "openai-completions",
  "models": [
    { "id": "llama-4-scout",  "name": "Llama 4 Scout (Cerebras)" },
    { "id": "llama-3.3-70b", "name": "Llama 3.3 70B (Cerebras)" }
  ]
}' --strict-json --merge

openclaw config set agents.defaults.model.primary "$MODEL_PRIMARY"
openclaw config set agents.defaults.model.fallbacks "[\"$MODEL_FALLBACK\"]" --strict-json

# --- 6. Werkzeuge freischalten (echte Arbeit statt Chat) ---------------------
say "Werkzeugprofil 'coding' (Datei, Laufzeit, Web, Speicher, Cron)"
openclaw config set tools.profile "coding"

# --- 7. Gateway absichern ----------------------------------------------------
say "Gateway-Auth (Operator-Token) + Bind '$BIND' + Port $PORT"
openclaw config set gateway.mode "local"
openclaw config set gateway.port "$PORT" --strict-json
openclaw config set gateway.bind "$BIND"
openclaw config set gateway.auth.mode "token"
openclaw config set gateway.auth.token "$GW_TOKEN"

# --- 8. Beispiel-Automatisierung: täglicher Arbeits-Digest -------------------
say "Automatisierung: täglicher Digest um 08:00 (Cron)"
openclaw cron add "0 8 * * *" \
  "agent 'Fasse offene Aufgaben und Termine für heute in 5 Stichpunkten zusammen.'" \
  2>/dev/null || warn "Cron-Beispiel übersprungen (bereits vorhanden oder Syntax abweichend)."

# --- 9. Validieren + reparieren ----------------------------------------------
say "Konfiguration validieren"
openclaw config validate || {
  warn "Validierung meldete Punkte — versuche doctor --fix"
  openclaw doctor --fix || true
  openclaw config validate || die "Konfiguration ungültig — bitte manuell prüfen."
}

# --- 10. Dienst installieren & starten ---------------------------------------
say "Gateway als Dienst installieren und starten"
openclaw gateway install >/dev/null 2>&1 || warn "Dienstinstallation übersprungen (evtl. Rechte/Plattform — 'sudo' versuchen?)."
if ! openclaw gateway restart >/dev/null 2>&1; then
  warn "restart fehlgeschlagen — starte im Hintergrund"
  openclaw gateway start >/dev/null 2>&1 &
  sleep 3
fi
openclaw gateway status 2>/dev/null || warn "Status unbekannt — 'openclaw logs --follow' prüfen."

# --- 11. Verbindungsdaten für HUGIN ausgeben ---------------------------------
# IP-Erkennung: macOS → Linux → Fallback
HOST_IP="$(ipconfig getifaddr en0 2>/dev/null \
  || hostname -I 2>/dev/null | awk '{print $1}' \
  || echo '127.0.0.1')"

LOOPBACK_NOTE=""
if [ "$BIND" = "loopback" ]; then
  LOOPBACK_NOTE=" ⚠  Bind=loopback → nur lokal erreichbar.
 Vom iPhone: Tailscale/VPN empfohlen, oder SSH-Tunnel:
   ssh -N -L ${PORT}:127.0.0.1:${PORT} user@${HOST_IP}
 → dann in HUGIN  http://127.0.0.1:${PORT}  eintragen."
fi

cat <<EOF

============================================================
 FERTIG — HUGIN mit OpenClaw verbinden
============================================================
 In HUGIN:  ⚙  →  ARBEITS-ENGINE — OPENCLAW

   Gateway-URL   :  http://${HOST_IP}:${PORT}
   Operator-Token:  ${GW_TOKEN}
   Modell        :  openclaw/default   (Standard, leer lassen)
${LOOPBACK_NOTE}
 Token dauerhaft gespeichert unter: ${TOKEN_FILE}
 Erneut anzeigen: openclaw config get gateway.auth.token
 Oder:            cat "${TOKEN_FILE}"

 Logs in Echtzeit: openclaw logs --follow
============================================================
EOF
