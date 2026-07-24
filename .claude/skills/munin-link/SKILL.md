---
name: munin-link
description: >
  MUNIN Autonomous Connection Bridge. Verbindet Repo + Chat + Hardware (iPhone).
  Aktivieren bei: Session-Start (broadcast), Status an iPhone senden (telegram),
  Hardware-Befehle empfangen (gateway-cmd), Verbindung prüfen (health).
---

# MUNIN-Link — Vollständige Autonome Verbindung

## Architektur

```
iPhone/Hardware
      │
      ├─ lesen  → .claude/persona/munin-link-status.json  (git pull)
      ├─ lesen  → GET hm-gateway/memory/munin-link-status (HTTP)
      ├─ senden → Telegram-Bot → MUNIN (direkt)
      └─ senden → POST hm-gateway/tasks → hm-agent → MUNIN
            │
       [Chat/CCR]
            │
      ├─ schreiben → direct_write.py full (Repo)
      ├─ pushen    → git push (GitHub)
      └─ empfangen → GitHub-Webhooks (PR-Activity, CI)
            │
         [Repo]
            └─ GitHub Actions → CI → Merge
```

## Verwendung

```bash
# Health-Check (alle Kanäle)
python3 .claude/skills/munin-link/scripts/munin_link.py health

# Status broadcasten (nach jedem Commit sinnvoll)
python3 .claude/skills/munin-link/scripts/munin_link.py broadcast "PR #58 gemergt"

# Nachricht ans iPhone
python3 .claude/skills/munin-link/scripts/munin_link.py telegram "Build grün — merge-ready"

# Repo-Status
python3 .claude/skills/munin-link/scripts/munin_link.py repo-status
```

## Kanal-Aktivierung

| Kanal | Status | Aktivierung |
|-------|--------|-------------|
| Chat → Repo | ✅ aktiv | direct_write.py |
| Repo → Chat | ✅ aktiv | GitHub Webhooks |
| Chat → iPhone | ⚙️ konfigurierbar | `export MUNIN_TELEGRAM_TOKEN=... MUNIN_TELEGRAM_CHAT_ID=...` |
| iPhone → Chat | ⚙️ konfigurierbar | `export HM_OWNER_TOKEN=... HM_GATEWAY_URL=...` |
| CCR-Routine | ✅ aktiv | stündlich via create_trigger |

## Telegram einrichten (iPhone → Chat, Chat → iPhone)

1. `@BotFather` in Telegram → `/newbot` → Token kopieren
2. Bot anschreiben → `@userinfobot` → Chat-ID
3. Lokal setzen:
   ```bash
   export MUNIN_TELEGRAM_TOKEN=<token>
   export MUNIN_TELEGRAM_CHAT_ID=<chat-id>
   ```
4. Test: `python3 .claude/skills/munin-link/scripts/munin_link.py telegram "MUNIN aktiv"`

## Integration in dev-loop

```
12. CHECKPOINT  munin_bridge.py checkpoint "..."
    +BROADCAST  munin_link.py broadcast "done: PR #X grün"
    +TELEGRAM   munin_link.py telegram "✅ PR #X merge-ready"
13. BEREIT      Master informieren
```
