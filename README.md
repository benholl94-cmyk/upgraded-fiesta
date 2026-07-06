# Fullstack Heavy Metal

Generated from the uploaded Markdown specification as a Rust workspace.

## Includes

- core types, traits, events and configuration
- gateway skeleton with health/chat/session/agent/memory/tool handler modules
- agent runtime modules for pi, codex and cli backends
- memory modules for fts, vector, hybrid, embeddings, dreaming, episodic and semantic memory
- channel crates for telegram, discord, slack and whatsapp
- tool crates for exec, browser, web and media
- plugin, sdk, session, vector, cron, auth and cli crates
- ui scaffold, docker files, makefile, configuration, SQL and validator

## Codex fullstack setup

Repository-level Codex behavior is defined in:

- `AGENTS.md`
- `.codex/config.toml`
- `.codex/setup.sh`
- `.codex/maintenance.sh`
- `scripts/codex_fullstack_setup.sh`
- `scripts/codex_fullstack_check.sh`

For Codex cloud, configure the environment setup command as:

```sh
bash .codex/setup.sh
```

For cached Codex cloud environments, configure the maintenance command as:

```sh
bash .codex/maintenance.sh
```

For a complete local or cloud verification pass, run:

```sh
make codex-check
```

## Validate

```sh
python3 scripts/validate_repo.py
```

## Reference

`docs/master-dossier.html` is a visual dossier of the workspace — architecture,
per-crate line counts, the `hm-gateway` API (including the local `/storage`
file endpoints), and CI/self-monitoring status. Open it directly in a browser.

## Other projects in this repository

`iphone-dev-platform/` is a self-contained static site (German-language iPhone
local-dev setup guide) with its own toolchain, unrelated to the Rust
workspace above — see its own `README.md`.
