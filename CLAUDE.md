# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository scope

This is a Rust workspace ("Fullstack Heavy Metal") with a Vite/React UI scaffold, plus two independent, unrelated projects living in the same repo:

- `crates/` — the Rust workspace (backend/gateway).
- `ui/` — the React/Vite control-plane frontend.
- `ghm_core/` + root `pyproject.toml` — `ghm-core`, a real installable pip package (console script `ghm-core`) providing local workspace/onboarding tooling.
- `iphone-dev-platform/` — a **fully self-contained** static site (German-language iPhone local-dev setup guide) imported from an unrelated, disconnected git history. It has its own `package.json`, `validate.py`/`test-validate.py`, and must be tested from inside that directory (`cd iphone-dev-platform && npm test`), never from the repo root. Do not assume anything in it shares code, dependencies, or conventions with the Rust workspace.

Config lives under `config/`, database bootstrap SQL is in `scripts/init-db.sql`, validation/dev scripts live under `scripts/`.

## Operating environment

The primary operator may only have an iPhone/mobile client. Do not assume access to macOS, a desktop IDE, local Docker Desktop, Homebrew, or a long-running local shell. Prefer repository-native automation, Codex cloud, GitHub Actions, and portable shell/Python scripts. Do not replace this mobile-first operating model with desktop-only instructions.

Never commit API keys, tokens, private SSH keys, `.env` files, generated secrets, or host-specific credentials.

## Commands

From the repository root:

```sh
python3 scripts/validate_repo.py      # structural validation: workspace members, config JSON, required files
bash scripts/codex_fullstack_check.sh # preferred single verification command (see below)
cargo check --workspace
cargo test --workspace
cd ui && npm run build
python3 -m pytest tests/              # Python tests (ghm_core CLI smoke tests, url-builder, etc.)
```

`bash scripts/codex_fullstack_check.sh` validates repo structure, checks Rust formatting (when `cargo fmt` is available), runs `cargo check`/`cargo test` for the workspace, installs UI deps without writing a lockfile, and builds the UI. Run it (or the equivalent subset) before calling a change done.

Single-test invocations:

```sh
cargo test -p hm-gateway some_test_name       # one Rust crate/test
python3 -m pytest tests/test_ghm_core_cli_smoke.py::test_doctor -v   # one Python test
```

For the isolated iPhone site, run its own tooling from its own directory — it is not covered by any of the above:

```sh
cd iphone-dev-platform && npm test    # or: python3 scripts/test-validate.py
```

Codex cloud environment setup/maintenance commands (`bash .codex/setup.sh`, `bash .codex/maintenance.sh`) wrap `scripts/codex_fullstack_setup.sh` and dependency refresh (`cargo fetch`, `npm install`) respectively — see `AGENTS.md` for when these apply.

## Architecture: hm-gateway

`crates/hm-gateway` is the only real HTTP surface. It is a **hand-rolled async TCP server on raw tokio** — no axum/hyper/warp — that manually parses HTTP requests off `TcpListener`/`TcpStream`. When touching routing or request parsing, read the whole `match (method, path)` block in `main.rs`; there is no framework layer abstracting it away.

Routes (all gated by the same auth check except `OPTIONS`):
- `GET /`, `GET|/api|/gateway /health` — status/info
- `POST|GET /tasks` (+ `/api/tasks`, `/gateway/tasks`) — in-memory task registry, no persistence
- `PUT|GET|DELETE /storage/{key}` — passthrough to `hm-storage`
- `GET|POST /memory`, `POST /memory/search` — passthrough to `hm-memory`
- `GET|POST /diagnostics` — opt-in diagnostics reports (see below)

**Auth model (`hm-auth`)**: every route requires `Authorization: Bearer <HM_OWNER_TOKEN>`. The gateway process **refuses to start** if `HM_OWNER_TOKEN` is unset (fail-closed), unless `HM_GATEWAY_ALLOW_NO_AUTH=true` is explicitly set (local dev only). Token comparison is constant-time (`hm_auth::tokens_match`). Never weaken this without being asked.

**Storage model (`hm-storage`)**: `LocalFsStorage` is local-disk only, rooted at `HM_STORAGE_ROOT` (default `./data/storage`). `docker-compose.yml` declares `postgres`/`redis` services, but **no crate in the workspace actually connects to either** — grep confirms zero references to `sqlx`/`tokio_postgres`/`redis` in `crates/`. Don't assume the database layer is wired up; it isn't yet.

**Plugins (`hm-plugins` + `hm-sdk`)**: task types are dispatched to external subprocesses declared in `config/plugins.json`. Each invocation writes one line of JSON (`PluginRequest`) to the child's stdin and reads one line back (`PluginResponse`) with a 5s timeout. `plugins/echo_plugin.py` is the only registered example.

Env vars the gateway reads (defaults in `docs/production-api-contract.md`): `HM_GATEWAY_BIND`, `HM_ZERO_STAKED`, `HM_STORAGE_ROOT`, `HM_MEMORY_KEY`, `HM_OWNER_TOKEN`, `HM_GATEWAY_ALLOW_NO_AUTH`, `HM_DIAGNOSTICS_KEY`.

## Architecture: rest of the Rust workspace

Most other workspace members are **intentional placeholders**, not partial implementations — `hm-core`, `hm-agent`, `hm-cli`, `hm-cron`, `hm-sessions`, and all four `hm-tools/hm-tool-*` crates are single-function/single-constant stubs. The four `hm-channels/hm-channel-*` crates (telegram/discord/slack/whatsapp) only load and validate a bot token via `hm_auth::load_bot_token`; **none makes real calls to any chat platform** — that requires real bot credentials to build and live-test responsibly, per `AGENTS.md`'s "surface gaps" rule. Don't mistake the presence of a crate for a working feature; check line count/content before assuming behavior exists.

`hm-memory` (semantic-ish "remember"/"recall" store) and `hm-vector` are the only other crates with real logic.

## Architecture: UI

`ui/` is a Vite + React app (`vite build` only; no dev-server script is defined in `package.json`, so `node_modules` must exist before running Vite directly). It does **not** get served by `hm-gateway` — `GET /` on the gateway returns JSON, not the UI's HTML. The UI is a separate static bundle that talks to the gateway over HTTP.

Key piece: `ui/src/endpoint-rotation.ts`. The UI is designed to fail over across multiple gateway endpoints (`primary` → `gateway-local` → `gateway-fallback`, configurable via `/platform-config.json`), health-checking each before dispatch and requiring a *recognizable* status/state/health JSON body (not just a 2xx) before trusting an endpoint as "online" — a bare 2xx from a misconfigured proxy or SPA fallback is treated as `unknown`, not `online`. The owner bearer token lives in the browser's `localStorage` (`hm_owner_token` key) and is attached to every outgoing request.

## The `ghm-core` pip package

`ghm_core/cli.py` is a real console-script CLI (`pip install -e .`), separate from the Rust CLI (`hm-cli`, which is just a stub). Subcommands follow one hard rule established across this codebase: **anything that sends data off the machine or starts a network-reachable process must disclose exactly what it's about to do and require explicit consent before acting**, and must refuse loudly (nonzero exit + machine-readable reason) rather than silently no-op or silently act when run non-interactively without `--yes`. See `cmd_report_diagnostics` and `cmd_onboard_iphone` for the pattern; any new subcommand with similar side effects should follow it too.

- `report-diagnostics` — sends exactly four disclosed fields (`os_name`, `os_version`, `python_version`, `architecture`) to your own gateway's `/diagnostics`, gated by `HM_OWNER_TOKEN`.
- `onboard-iphone` — starts `hm-gateway` bound to `0.0.0.0:<port>` (LAN-reachable, never a public tunnel) and prints the URL + owner token to enter on an iPhone.

## Documentation map

- `docs/production-api-contract.md` — the authoritative reference for every gateway route, env var, and the `ghm-core` CLI subcommands. Update this when changing gateway behavior.
- `docs/master-dossier.html` — visual dossier (architecture, per-crate line counts, API reference); open in a browser.
- `docs/architecture.md` is a one-line stub (`Gateway -> Agent Runtime -> Memory -> Channels -> Tools -> Plugins -> UI`) describing the intended shape, not the current implementation — most of that chain is still placeholder crates (see above).
