# hm-plugins

Subprocess-Plugin-Dispatcher: eine JSON-Zeile rein, eine raus, Timeout-Trennung.

## Wire-Identitaet

- Plugin/task_type-Name: `plugins`
- Public-API-Stabilitaet: semver folgt `Cargo.toml` (`workspace.package.version` = `0.1.0`).

## Aufruf (Beispiel)

```bash
cargo test -p hm-plugins
```

## Quelle

- `crates/hm-plugins/src/`
- `crates/hm-plugins/Cargo.toml`

_Dieses README wird durch `scripts/generate_crate_readmes.py` erzeugt._
_Manuelle Edits werden beim naechsten Lauf nicht ueberschrieben (Schutzmechanismus)._
