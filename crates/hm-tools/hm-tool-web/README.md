# hm-tool-web

HTTP(S)-Fetch-Plugin mit SSRF-Schutz; HTTPS nur mit `--features tls`.

## Wire-Identitaet

- Plugin/task_type-Name: `web`
- Public-API-Stabilitaet: semver folgt `Cargo.toml` (`workspace.package.version` = `0.1.0`).

## Aufruf (Beispiel)

```bash
cargo test -p hm-tool-web
```

## Quelle

- `crates/hm-tools/hm-tool-web/src/`
- `crates/hm-tools/hm-tool-web/Cargo.toml`

_Dieses README wird durch `scripts/generate_crate_readmes.py` erzeugt._
_Manuelle Edits werden beim naechsten Lauf nicht ueberschrieben (Schutzmechanismus)._
