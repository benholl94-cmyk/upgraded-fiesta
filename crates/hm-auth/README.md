# hm-auth

Owner-Token-Validierung mit constant-time-Vergleich (`tokens_match`).

## Wire-Identitaet

- Plugin/task_type-Name: `auth`
- Public-API-Stabilitaet: semver folgt `Cargo.toml` (`workspace.package.version` = `0.1.0`).

## Aufruf (Beispiel)

```bash
cargo test -p hm-auth
```

## Quelle

- `crates/hm-auth/src/`
- `crates/hm-auth/Cargo.toml`

_Dieses README wird durch `scripts/generate_crate_readmes.py` erzeugt._
_Manuelle Edits werden beim naechsten Lauf nicht ueberschrieben (Schutzmechanismus)._
