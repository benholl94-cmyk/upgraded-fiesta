# Übergabe an die nächste Sitzung

Erzeugt 2026-07-26T04:40:56+00:00 von `scripts/munin_handoff.py`. **Alles hier ist gemessen,
nichts erinnert** — neu erzeugen statt von Hand pflegen:

```sh
python3 scripts/munin_handoff.py --write
```

## Zustand

| | |
|---|---|
| Branch | `claude/claud-ai-code-teleport-nx73zr` |
| HEAD | `7d812c4 Revert "feat(ci): automatisches Rollback für main (#77)"` |
| Ungepusht | 0 |
| Arbeitsbaum schmutzig | ja |
| Getrackte Dateien | 722 |
| Crates / Python / Rust / Testdateien | 20 / 136 / 42 / 17 |

## Offene Befunde

| Schwere | Regel | Befund |
|---|---|---|
| VIOLATION | `git-identity-collision` | Committer-Mail ist noreply@anthropic.com, Verfassung verlangt 274793931+benholl94-cmyk@users.noreply.github.co |
| RISK | `archive-in-index` | 16 Archiv(e)/Binary(s) im Index |
| RISK | `oracle-gate-bypass` | supervisor_agent.production.py nennt api.anthropic.com direkt |

Vollständig mit Begründung:
`python3 scripts/munin_supervisor.py --quick`

## Einstiegspunkte

| Befehl | Wofür |
|---|---|
| `python3 scripts/munin_supervisor.py --quick` | Verfassungs-Audit |
| `python3 -m pytest tests/ -q` | Python-Tests |
| `cargo test --workspace` | Rust-Tests |
| `python3 -m agents status` | Agenten + Kostenbremse |
| `python3 scripts/hugin_keyring.py status` | Eigene Dienstschluessel |
| `python3 scripts/validate_repo.py` | Strukturpruefung |
| `cp hugin/hugin.html hugin/index.html` | Nach jeder PWA-Aenderung |

## Letzte Commits

```
7d812c4 Revert "feat(ci): automatisches Rollback für main (#77)"
11254bb Update visible monitoring report
1e2c75d Update visible platform status [skip ci]
4b9c078 feat(ci): automatisches Rollback für main (#77)
f5a6a17 Update visible monitoring report
8e1d6f4 Update visible platform status [skip ci]
8149bcb feat(gateway,hugin): Zugriffsfläche auf den Owner verengt (#76)
d0b6214 Update visible monitoring report
365d04b Update visible platform status [skip ci]
84f1788 feat(agents): Konsensgrad und Kostenbremse (#75)
0456aeb Update visible platform status [skip ci]
11256f5 Update visible monitoring report
```

## Was diese Datei nicht ist

Kein Ersatz für `CLAUDE.md` — dort steht, *wie* das Repo funktioniert.
Hier steht nur, *wo es gerade steht*. Bei Widerspruch gewinnt die
Messung: `CLAUDE.md` kann veralten, diese Datei wird neu erzeugt.

