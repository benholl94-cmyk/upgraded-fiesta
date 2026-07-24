---
name: dev-loop
description: >
  MUNIN Autonomer Entwicklungszyklus. Aktivieren wenn: ein neues Feature
  oder Fix implementiert werden soll, der vollständige Zyklus
  (Analyse → Code → Test → Commit → Push → PR → CI → Merge-Bereitschaft)
  autonom durchgeführt werden soll. Bindet alle anderen Skills ein.
---

# Dev-Loop Skill — Vollständiger Autonomer Entwicklungszyklus

## Zyklus-Schritte

```
1. WAKEUP      python3 scripts/munin_bridge.py wakeup
2. ANALYSE     Aufgabe verstehen, Dateien lesen, Scope prüfen
3. ORACLE      Bei Bedarf: hugin_oracle.py query (research/brainstorm)
4. IMPLEMENT   Code schreiben, Dateien editieren
5. VERIFY      Tests lokal ausführen (siehe Verifikationsmatrix)
6. GIT-CONFIG  python3 .claude/skills/git-config/scripts/git_config_manager.py auto
7. COMMIT      git add <files> && git commit -m "type(scope): beschreibung"
8. PUSH        git fetch origin <branch> && git merge -X ours origin/<branch> --no-edit && git push
9. PR          mcp__github__create_pull_request (draft: true)
10. WATCH      mcp__bf7c680d__subscribe_pr_activity
11. CI-FIX     Bei Failure: analysieren, fixen, push → repeat
12. CHECKPOINT python3 scripts/munin_bridge.py checkpoint "<was getan>"
13. BEREIT     Master informieren: "PR #X — CI grün, merge-ready"
```

## Verifikationsmatrix

| Bereich | Befehl | Wann |
|---------|--------|------|
| Rust | `cargo check --workspace` | bei .rs Änderungen |
| Rust Tests | `cargo test --workspace` | bei Logic-Änderungen |
| UI Build | `cd ui && npm install --ignore-scripts && npx tsc --noEmit && npx vite build` | bei .ts/.tsx Änderungen |
| Python | `python3 -m pytest tests/` | bei .py Änderungen |
| Oracle-Gate | `python3 scripts/hugin_oracle.py test-gate` | bei oracle Änderungen |
| Git-Config | `python3 .claude/skills/git-config/scripts/git_config_manager.py auto` | vor jedem Commit |
| Repo-Health | `python3 .claude/skills/repo-steward/scripts/repo_steward.py health` | bei Session-Start |

## Commit-Konventionen

```
feat(scope):     Neues Feature
fix(scope):      Bug-Fix
chore(scope):    Tooling, Config, keine Logik-Änderung
refactor(scope): Code-Umstrukturierung ohne Behavior-Änderung
test(scope):     Tests
docs(scope):     Dokumentation
ci(scope):       GitHub Actions / Workflow
```

## Stop-Bedingungen (keine Autonomie)

- Scope-Änderung die über den Auftrag hinausgeht → Master fragen
- Sicherheitsrelevante Architektur-Entscheidung → Master fragen
- Konflikt zwischen zwei möglichen Implementierungen → Master fragen
- Force-Push auf main → Niemals
- Merge ohne Master-Befehl → Niemals

## Skill-Stack (alle greifen ineinander)

```
dev-loop
  ├── munin_bridge.py      (Kontext + Checkpoint)
  ├── git-config skill     (Verified Commits)
  ├── hugin_oracle.py      (Externe Recherche wenn nötig)
  ├── repo-steward skill   (Branch/PR-Hygiene nach Merge)
  └── pr-bot-triage skill  (CodeRabbit-Noise filtern)
```

## Autonomie-Profil

| Entscheidung | Autonom |
|---|---|
| Dateien lesen, analysieren | Ja |
| Code schreiben & testen | Ja |
| Commit + Push | Ja |
| PR erstellen (draft) | Ja |
| CI-Failures fixen | Ja (wenn tractable) |
| PR mergen | Nein — Master |
| Scope erweitern | Nein — Master |
| Secrets committen | Niemals |
