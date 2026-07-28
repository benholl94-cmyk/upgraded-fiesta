# hm-sdk

Gemeinsamer Wire-Code (TaskSubmission) + optionaler HTTPS-Client (`tls`-Modul).

## Wire-Identitaet

- Plugin/task_type-Name: `sdk`
- Public-API-Stabilitaet: semver folgt `Cargo.toml` (`workspace.package.version` = `0.1.0`).

## Aufruf (Beispiel)

```bash
cargo test -p hm-sdk
```

## Quelle

- `crates/hm-sdk/src/`
- `crates/hm-sdk/Cargo.toml`

_Dieses README wird durch `scripts/generate_crate_readmes.py` erzeugt._
_Manuelle Edits werden beim naechsten Lauf nicht ueberschrieben (Schutzmechanismus)._
