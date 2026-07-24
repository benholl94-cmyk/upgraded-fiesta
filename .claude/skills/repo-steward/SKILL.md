---
name: repo-steward
description: >
  MUNIN Repo-Steward — PR-Lifecycle und Branch-Hygiene. Aktivieren bei:
  stale PRs schließen, orphan Branches löschen, Repo-Health-Report,
  Duplikat-PRs bereinigen. Kombiniert lokale git-Ops mit MCP-PR-Tools.
---

# Repo-Steward Skill

## Autonomie-Regeln

| Aktion | Autonomie |
|--------|-----------|
| Health-Report / stale-branches anzeigen | Immer autonom |
| Orphan Branch löschen (Bot/Codex, >30d, kein offener PR) | Autonom wenn Auftrag aktiv |
| Duplikat-PR schließen (selbe Arbeit, älter als neueste Version) | Autonom wenn klar |
| PR mit falscher Base schließen | Autonom |
| PR mit aktiver Arbeit schließen (#22 iPhone, #31 UniqueClaw) | **Master fragen** |
| `main` oder `claude/claud-ai-code-teleport-nx73zr` anfassen | Niemals |

## Workflow: Stale PRs schließen

```
1. python3 .claude/skills/repo-steward/scripts/repo_steward.py pr-targets
2. Für jeden klar-close PR:
   → MCP: mcp__github__update_pull_request (state: "closed")
   → MCP: mcp__github__add_issue_comment (kurze Begründung)
3. Branch danach löschen:
   → python3 .claude/skills/repo-steward/scripts/repo_steward.py delete-remote <branch>
```

## Workflow: Branch-Cleanup

```
1. python3 .claude/skills/repo-steward/scripts/repo_steward.py health
2. python3 .claude/skills/repo-steward/scripts/repo_steward.py stale-branches
3. Für jeden sicheren Branch:
   → python3 .claude/skills/repo-steward/scripts/repo_steward.py delete-remote <name>
```

## Entscheidungsbaum: PR schließen?

```
PR älter als 30 Tage?
  ├─ Base ≠ main → CLOSE (nie mergebar)
  ├─ Duplikat einer neueren Version → CLOSE
  ├─ Alle Commits bereits in main → CLOSE
  └─ Aktive Arbeit des Masters → FRAGE MASTER
```

## PR-Kommentar bei Close (Standard)

```
Dieser PR wird geschlossen: [Grund — Duplikat/falscher Base/bereits in main].
Die Änderungen sind in [PR #X / main] enthalten.
```

## Lokale Befehle

```bash
python3 .claude/skills/repo-steward/scripts/repo_steward.py health
python3 .claude/skills/repo-steward/scripts/repo_steward.py stale-branches
python3 .claude/skills/repo-steward/scripts/repo_steward.py pr-targets
python3 .claude/skills/repo-steward/scripts/repo_steward.py delete-remote <branch>
```
