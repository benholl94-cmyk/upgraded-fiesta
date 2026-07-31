# hm-cron

Cron-Scheduler: liest config/cron.json, ruft due Jobs als POST /tasks auf.

## Wire-Identitaet

- Plugin/task_type-Name: `cron`
- Public-API-Stabilitaet: semver folgt `Cargo.toml` (`workspace.package.version` = `0.1.0`).

## Aufruf (Beispiel)

```bash
cargo test -p hm-cron
```

## Quelle

- `crates/hm-cron/src/`
- `crates/hm-cron/Cargo.toml`

_Dieses README wird durch `scripts/generate_crate_readmes.py` erzeugt._
_Manuelle Edits werden beim naechsten Lauf nicht ueberschrieben (Schutzmechanismus)._
