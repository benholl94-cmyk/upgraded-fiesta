---
name: git-config
description: >
  MUNIN Git-Identity-Manager. Verwende diesen Skill bei: (1) Stop-Hook meldet
  "Unverified commits", (2) git identity soll für einen Commit-Typ gewechselt
  werden, (3) Tip-Commit oder Commit-Serie soll re-authored werden.
  Erlaubt MUNIN die autonome git-config-Modifizierung ohne Master-Intervention,
  sofern die Aktion dem laufenden Auftrag dient.
---

# Git-Config Skill — MUNIN Identity Manager

## Wann aktivieren

| Situation | Aktion |
|-----------|--------|
| Stop-Hook: "Unverified commits" | `auto` — behebt Tip autonom |
| Commit soll als Verified erscheinen | `switch claude` + `fix-tip` |
| Commit soll unter Owner erscheinen | `switch munin` |
| Mehrere eigene Commits seit base | `rebase-fix origin/main` |
| Aktuellen Zustand prüfen | `status` oder `check-verified` |

## Autonomie-Grenzen (unverhandelbar)

- **Niemals anfassen**: Merge-Commits, Bot-Commits (`github-actions[bot]`, `dependabot`), Commits anderer auf `main`
- **Kein Force-Push** ohne expliziten Master-Befehl
- **Kein Profil-Switch** wenn aktueller Commit bereits `noreply@anthropic.com` ist
- Jede Änderung wird im Terminal geloggt (kein stilles Handeln)

## Profile

| Profil | Name | Email | Wann |
|--------|------|-------|------|
| `claude` | Claude | noreply@anthropic.com | Standard — CI, autonome Commits, Verified |
| `munin` | benholl94-cmyk | 274793931+benholl94-cmyk@users.noreply.github.com | Wenn Commit unter Owner erscheinen soll |

## Verwendung

```bash
# Status prüfen
python3 .claude/skills/git-config/scripts/git_config_manager.py status

# Profil wechseln
python3 .claude/skills/git-config/scripts/git_config_manager.py switch claude
python3 .claude/skills/git-config/scripts/git_config_manager.py switch munin

# Tip-Commit fixen (mit optionalem Profil-Switch)
python3 .claude/skills/git-config/scripts/git_config_manager.py fix-tip
python3 .claude/skills/git-config/scripts/git_config_manager.py fix-tip --profile claude

# Alle eigenen Commits seit origin/main re-author
python3 .claude/skills/git-config/scripts/git_config_manager.py rebase-fix origin/main

# Verifikations-Status aller Commits prüfen
python3 .claude/skills/git-config/scripts/git_config_manager.py check-verified

# Autonom analysieren + fix (Standard bei Stop-Hook-Meldung)
python3 .claude/skills/git-config/scripts/git_config_manager.py auto
```

## Entscheidungsbaum bei Stop-Hook "Unverified"

```
Hook meldet Unverified
    ↓
git_config_manager.py auto
    ├─ Tip = Bot/Merge?  → Nichts tun (protected)
    ├─ Tip = noreply@anthropic.com? → Bereits verified, nichts tun
    └─ Tip = anderes? → switch claude + fix-tip + melden
```

Nach fix-tip: `git push` mit dem etablierten Divergenz-Protokoll falls nötig.

## Integration mit MUNIN-Bridge

Nach einem Auto-Fix einen Checkpoint setzen:
```bash
python3 scripts/munin_bridge.py checkpoint "git-identity auto-fix: claude-Profil + tip re-authored"
```
