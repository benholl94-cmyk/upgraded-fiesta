---
name: direct-write
description: >
  MUNIN Direct-Write — atomares Schreiben, Committen und Pushen ohne
  extra PR-Runde oder manuelle Reviews. Aktivieren wenn: Code direkt
  ins Repo eingeschrieben werden soll, sofort auf dem Branch verfügbar,
  ohne Unterbrechung des Arbeitsflusses.
---

# Direct-Write Skill

## Was es tut

Code wird geschrieben → sofort committed → sofort gepusht. Ein Schritt, kein Warten.

## Verwendung

```bash
# Alles in einem: commit + sync + push
python3 .claude/skills/direct-write/scripts/direct_write.py full "feat(scope): was getan"

# Nur committen (alle geänderten Dateien außer logs/.env)
python3 .claude/skills/direct-write/scripts/direct_write.py commit "fix(scope): beschreibung"

# Nur pushen (inkl. automatischer Sync mit remote)
python3 .claude/skills/direct-write/scripts/direct_write.py push

# Status prüfen
python3 .claude/skills/direct-write/scripts/direct_write.py status
```

## Integration in dev-loop

Ersetzt Schritte 7–8 des dev-loop:

```
4. IMPLEMENT   Code schreiben (Edit/Write Tools)
5. VERIFY      Tests
6. GIT-CONFIG  git_config_manager.py auto
7+8. DIRECT    direct_write.py full "type(scope): beschreibung"
```

## Sicherheitsregeln (unveränderlich)

- Staged niemals: `logs/`, `.env*`, `*.key`, `*.pem`
- Pusht nur auf den aktuellen Branch — niemals auf `main` direkt
- Merge-Konflikte in `logs/` werden automatisch mit `ours` aufgelöst
- Commit enthält immer `Co-Authored-By: benholl94-cmyk`

## settings.json (bereits konfiguriert)

```json
"Bash(python3 .claude/skills/direct-write/scripts/direct_write.py*)"
"Bash(git add --all*)"
"Bash(git push -u origin*)"
"Bash(git push origin*)"
```
