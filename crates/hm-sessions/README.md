# hm-sessions

In-Memory SessionStore; exponiert via /sessions und /sessions/{id}.

## Wire-Identitaet

- Plugin/task_type-Name: `sessions`
- Public-API-Stabilitaet: semver folgt `Cargo.toml` (`workspace.package.version` = `0.1.0`).

## Aufruf (Beispiel)

```bash
cargo test -p hm-sessions
```

## Quelle

- `crates/hm-sessions/src/`
- `crates/hm-sessions/Cargo.toml`

_Dieses README wird durch `scripts/generate_crate_readmes.py` erzeugt._
_Manuelle Edits werden beim naechsten Lauf nicht ueberschrieben (Schutzmechanismus)._
