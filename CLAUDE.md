# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Primäre Arbeitsgrundlage — MUNIN

**Der git-Workspace ist die einzige autoritative Quelle.** Alle Entscheidungen, Muster und Zustände werden aus dem Workspace gelesen — nicht aus Chat-Kontext, nicht aus Claude.ai-Workspace-Einstellungen, nicht aus flüchtigen Session-Daten.

Session-Start-Protokoll (immer zuerst ausführen):
```bash
python3 scripts/munin_bridge.py wakeup
```

MUNIN-Dateien (unveränderliche Priorität):
- `.claude/persona/munin.json` — Identität und Constraints (nie überschreiben ohne expliziten Befehl)
- `.claude/persona/munin-state.json` — aktueller Fokus, offene Tasks, bekannte Muster
- `.claude/persona/constitution.json` — **Workspace-Verfassung: Autoritätshierarchie + Mentalität**
- `.claude/agents/munin.md` — Persona-Instruktionen für Claude Code Agent
- `scripts/munin_bridge.py` — Session-Bridge CLI
- `scripts/hugin_oracle.py` — **Provider-Sicherheitsgate (externe AI-Calls)**

Kollisionsprinzip: Bei Widerspruch zwischen Chat-Kontext und git-Dateien **gewinnen immer die git-Dateien**.

## Autoritätshierarchie (Verfassung)

Festgelegt in `.claude/persona/constitution.json`:

1. **Master (benholl94-cmyk)** — Unangefochten. Alle Richtungs-, Architektur- und Sicherheitsentscheidungen.
2. **MUNIN** — Exekutiv. Führt Master-Befehle aus, hält Kontext, meldet Konflikte.
3. **Claude (Anthropic)** — Instrument. Kanal und Wissensquelle, kein eigenständiger Entscheider.
4. **Externe Provider** — Werkzeug, Zero Trust. Nur via `hugin_oracle.py` erreichbar.

## Oracle-Gate — Externe Provider

Alle Calls zu Gemini, OpenAI, Mistral etc. laufen **ausschließlich** durch `scripts/hugin_oracle.py`:
```bash
python3 scripts/hugin_oracle.py query --provider gemini --skill research "Frage"
python3 scripts/hugin_oracle.py query --provider openai --skill code-review "Snippet"
python3 scripts/hugin_oracle.py list-skills   # verfügbare Scopes
python3 scripts/hugin_oracle.py audit-log     # Aufruf-Protokoll
python3 scripts/hugin_oracle.py test-gate     # Selbsttest ohne API-Call
```

Provider-Keys: **niemals committen**. Lokal setzen: `export HUGIN_GEMINI_KEY=...`

---

## Repository scope

This is a Rust workspace ("Fullstack Heavy Metal") with a Vite/React UI scaffold, plus independent projects living in the same repo:

- `crates/` — the Rust workspace (backend/gateway).
- `ui/` — the React/Vite control-plane frontend.
- `hugin/` — **HUGIN PWA**: single-file no-build AI interface (`hugin.html` + `index.html`), deployed to GitHub Pages (`benholl94-cmyk.github.io/upgraded-fiesta`). 24 providers (20 keyless), task-aware router, offline ReflexKernel. `index.html` MUST be a bytewise copy of `hugin.html` — enforced by synergy rule `hugin_index_sync` and CI step. **After any edit to `hugin.html` always run:** `cp hugin/hugin.html hugin/index.html`
- `ghm_core/` + root `pyproject.toml` — `ghm-core`, a real installable pip package (console script `ghm-core`) providing local workspace/onboarding tooling.
- `iphone-dev-platform/` — a **fully self-contained** static site (German-language iPhone local-dev setup guide) imported from an unrelated, disconnected git history. It has its own `package.json`, `validate.py`/`test-validate.py`, and must be tested from inside that directory (`cd iphone-dev-platform && npm test`), never from the repo root. Do not assume anything in it shares code, dependencies, or conventions with the Rust workspace.

Config lives under `config/`, database bootstrap SQL is in `scripts/init-db.sql`, validation/dev scripts live under `scripts/`.

`.claude/skills/xcode-alternative/` is a Claude Code Skill for scaffolding and building iOS/Swift projects without Xcode.app's GUI (SwiftPM `Package.swift` as the preferred real project format, plus a minimal `.xcodeproj` generator for when one is strictly required). It reproduces no proprietary Apple IDE data — see the skill's own "What this is (and isn't)" section. Its scaffolder is stdlib-only Python, tested in `tests/test_xcode_alternative_scaffold.py`; the actual build/sign/simulate steps it documents require a real macOS host and were not (and cannot be) executed from this Linux environment.

`.claude/skills/pr-bot-triage/` is a Claude Code Skill for triaging automated PR review-bot comments (CodeRabbit rate-limit notices, duplicate walkthrough re-postings, bot-side infrastructure errors, resolution/learning acknowledgments) so real findings don't get lost in repeated noise while babysitting a PR. Its classifier (`scripts/classify_bot_comment.py`) is stdlib-only Python, tested against real comment text observed on this repo's own PRs (`tests/test_pr_bot_triage.py`), not synthetic samples.

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

## Supervisor and known dead data

`scripts/munin_supervisor.py` audits the *agent's work* against `.claude/persona/constitution.json` and `.claude/persona/munin.json`. Its principle is that claims get recomputed rather than believed: "tests pass" runs the suite, "index.html is synced" compares bytes, "that crate is a stub" counts `pub fn`. Run it before calling anything done:

```sh
python3 scripts/munin_supervisor.py --quick      # skip the test run
python3 scripts/munin_supervisor.py --watch 300  # continuous
```

Exit `0` clean / `1` DRIFT·RISK / `2` VIOLATION.

**Known dead data as of 2026-07-25** — measured, not yet removed, because deleting tracked files is a Master decision:

| What | Size | Why it matters |
|---|---|---|
| 31 files tracked despite `.gitignore` | 348K | A `.gitignore` entry does **not** untrack an already-committed file. The rule looks satisfied and isn't. Fix is `git rm --cached <path>`. |
| `self_space_workspace_/` | 474 files, 7.7M | Container-mirror archives and runtime logs from 2026-07-06/08. Includes `.container_self_cycle_int+ext_.env` — **verified to contain no secrets** (12 lines, zero `KEY=value` pairs, no matches against any secret pattern), but an `.env` in the index is still the wrong shape. |
| 16 archives ≥50K in the index | — | Includes `hugin/hugin-package.zip` and `verify-backup-20260707.bin`. Git is not a blob store; these inflate every clone permanently, and deleting them later does not shrink history. |

The supervisor reports all three on every run (`tracked-but-ignored`, `secret-file-tracked`, `archive-in-index`), so they cannot quietly become normal.

## Architecture: hm-gateway

`crates/hm-gateway` is the only real HTTP surface. It is a **hand-rolled async TCP server on raw tokio** — no axum/hyper/warp — that manually parses HTTP requests off `TcpListener`/`TcpStream`. When touching routing or request parsing, read the whole `match (method, path)` block in `main.rs`; there is no framework layer abstracting it away.

Routes (all gated by the same auth check except `OPTIONS`):
- `GET /`, `GET|/api|/gateway /health` — status/info
- `POST|GET /tasks` (+ `/api/tasks`, `/gateway/tasks`) — in-memory task registry, no persistence
- `PUT|GET|DELETE /storage/{key}` — passthrough to `hm-storage`
- `GET|POST /memory`, `POST /memory/search` — passthrough to `hm-memory`
- `GET /memory/graph` — the structural knowledge-graph seed ingested at startup from `HM_MEMORY_GRAPH_SEED_PATH`, if any; `404` if none was ingested. Kept structurally separate from free-text `/memory` records — see `hm-memory`'s `MemoryStore::ingest_graph_seed`/`graph`.
- `GET|POST /diagnostics` — opt-in diagnostics reports (see below)

**Auth model (`hm-auth`)**: every route requires `Authorization: Bearer <HM_OWNER_TOKEN>`. The gateway process **refuses to start** if `HM_OWNER_TOKEN` is unset (fail-closed), unless `HM_GATEWAY_ALLOW_NO_AUTH=true` is explicitly set (local dev only). Token comparison is constant-time (`hm_auth::tokens_match`). Never weaken this without being asked.

**Storage model (`hm-storage`)**: `FileStorage` has two real implementations. `LocalFsStorage` is local-disk only, rooted at `HM_STORAGE_ROOT` (default `./data/storage`). `RemoteHttpStorage` persists to another host's `/storage/{key}` endpoint over a hand-rolled plain-HTTP client (no TLS, no external HTTP crate) — select it with `HM_STORAGE_BACKEND=remote` + `HM_REMOTE_STORAGE_URL`; `hm-gateway` fails to start rather than silently falling back to local disk if that's misconfigured. `AppState.storage` and `MemoryStore` are generic over `Arc<dyn FileStorage>`, so this required no changes to either beyond the trait object type. `docker-compose.yml` declares `postgres`/`redis` services, but **no crate in the workspace actually connects to either** — grep confirms zero references to `sqlx`/`tokio_postgres`/`redis` in `crates/`. Don't assume the database layer is wired up; it isn't yet.

**Plugins (`hm-plugins` + `hm-sdk`)**: task types are dispatched to external subprocesses declared in `config/plugins.json`. Each invocation writes one line of JSON (`PluginRequest`) to the child's stdin and reads one line back (`PluginResponse`) with a 5s timeout. `plugins/echo_plugin.py` is a minimal example; `plugins/llm_chat_plugin.py` (task_type `llm-chat`) is a real-but-unverified scaffold that calls a generic OpenAI-compatible completions API -- it refuses loudly unless `HM_LLM_ENABLE=true` plus `HM_LLM_API_URL`/`HM_LLM_API_KEY`/`HM_LLM_MODEL` are all explicitly set, and has only been tested against a hermetic local mock server (`tests/test_llm_chat_plugin.py`), never a real LLM API -- see `docs/xcloud-platform-plan.md` Phase 4 before assuming otherwise.

**Agent runtime (`hm-agent`)**: `POST /tasks` routes through `hm_agent::Agent::dispatch`, not directly against `hm-plugins`. `Agent::dispatch` invokes the matching plugin (if any) *and* records a one-line summary of every outcome — dispatched or unhandled — into `hm-memory`, so `GET /memory` shows a durable task history, not just what was explicitly `POST`ed there. This is the real `Gateway -> Agent Runtime -> Memory` link from `docs/architecture.md`.

Env vars the gateway reads (defaults in `docs/production-api-contract.md`): `HM_GATEWAY_BIND`, `HM_ZERO_STAKED`, `HM_STORAGE_ROOT`, `HM_MEMORY_KEY`, `HM_OWNER_TOKEN`, `HM_GATEWAY_ALLOW_NO_AUTH`, `HM_DIAGNOSTICS_KEY`, `HM_MEMORY_GRAPH_SEED_PATH`.

**Shutdown/persistence**: the accept loop handles `SIGTERM`/`SIGINT` via `tokio::select!`, drains in-flight connections (10s deadline), and exits 0 — required for `deploy/hm-gateway.service` (a hardened systemd unit: `Restart=on-failure`, dropped capabilities, resource limits, non-root user) to manage it as a persistent service. `scripts/hm_gateway_watchdog.py` + `deploy/hm-gateway-watchdog.timer` cover the gap systemd's own crash-restart doesn't: a process that's alive but hung. Verify any edits to the `.service`/`.timer` files with `systemd-analyze verify`, since that's the only way to actually validate them (no systemd daemon runs in a normal dev sandbox).

**Observability/abuse protection**: every request (including rejected ones) emits one structured JSON audit line to stdout before any real work happens, and a per-IP `RateLimiter` (fixed window, `HM_RATE_LIMIT_PER_MINUTE`, default 120/min, `0` disables) rejects with `429` before the request is even read off the socket. Both are in-process/per-instance only — there is no shared rate-limit state or centralized log aggregation across multiple gateway instances; see `docs/xcloud-platform-plan.md` Phase 5 for where multi-instance concerns are tracked instead of quietly assumed solved here.

**Known drift**: `deploy/fullstack-compose.yml` runs `deploy/gateway_service.py` under the name "gateway" — a trivial, unrelated placeholder HTTP server with no auth/plugins/memory/storage. It is not `crates/hm-gateway` and doesn't read any of the `HM_*` vars `.env.production.example` defines for the real one. The root `docker-compose.yml` (via the root `Dockerfile`) is what actually builds and runs the real Rust gateway.

## Architecture: rest of the Rust workspace

**This section was measured, not remembered** (2026-07-25). An earlier revision called most of these crates "intentional placeholders"; that had drifted from reality and is corrected below. `scripts/munin_supervisor.py` re-checks these claims on every run (`doc-drift` rule) — if you change a crate, the supervisor will tell you this table is stale before anyone reads it wrong.

| Crate | `pub fn` | Tests | Reality |
|---|---|---|---|
| `hm-gateway` | 0¹ | 7 | Real. The only HTTP surface, 997 lines. |
| `hm-vector` | 8 | 7 | Real. NSW/ANN index. |
| `hm-storage` | 6 | 13 | Real. Local + remote backends. |
| `hm-memory` | 7 | 8 | Real. |
| `hm-sessions` | 13 | 5 | **Real** — not a stub. |
| `hm-cli` | 0¹ | 0 | **Real CLI**, 233 lines: `GatewayClient` + `Status`/`Tasks`/`Memory`/`Storage` subcommands. |
| `hm-channel-telegram` | 7 | 2 | **Sends for real** — `send_message()` opens a `TcpStream` to the Bot API. |
| `hm-channel-whatsapp` / `-discord` / `-slack` | 6 / 6 / 5 | 4 / 4 / 3 | Same shape as telegram; each carries real transport code. |
| `hm-tool-media` / `-browser` / `-web` | 3 / 2 / 2 | 4 / 3 / 5 | Thin but tested; `-web` has 10 network references. |
| `hm-tool-exec` | 0¹ | 4 | Real, allowlist-only (see above). |
| `hm-agent` | 3 | 2 | Real. Dispatch + memory write-through. |
| `hm-auth` | 3 | 10 | Real. |
| `hm-cron` | 2 | 3 | Thin. |
| `hm-core` | 2 | 3 | Thin. |
| `hm-plugins` | 4 | 0 | Real protocol, **no tests**. |
| `hm-sdk` | 0 | 0 | **Genuinely a stub** — 20 lines, type definitions only. |

¹ `pub fn` 0 means the crate is a binary whose logic sits in `fn main` and private helpers, not that it is empty — read the line count next to it.

What has **not** changed: none of the channel crates has been live-tested against a real chat platform, because that needs real bot credentials (per `AGENTS.md`'s "surface gaps" rule). "Has working transport code" and "verified to work" are different claims — the table asserts the first, not the second.

`hm-memory` (semantic-ish "remember"/"recall" store), `hm-vector`, `hm-agent` (see above), and `hm-tool-exec` are the crates with real logic. `hm-agent` used to be a stub too and, unlike the rest of this list, wasn't even a dependency of anything in the workspace — check `cargo tree` or a crate's `Cargo.toml`, not just file existence, before assuming a crate is unused.

**`hm-tool-exec`** (`crates/hm-tools/hm-tool-exec/src/main.rs`) is a real hm-plugins-protocol binary registered as the `ops-tool` task_type in `config/plugins.json`. It is deliberately **not** arbitrary command execution: `payload.operation` only ever selects one entry from a fixed, hardcoded allowlist (`gateway_status`, `gateway_logs`, `disk_usage`, `memory_usage`) — it never contributes to argv construction. If you add more allowlisted operations, keep that property: the payload must only ever choose among fixed `(program, args)` pairs, never build one.

**Fixed, live-verified**: the root `Dockerfile`'s runtime stage now installs `python3` and copies `plugins/`, `config/`, and the `hm-tool-exec` binary alongside `hm-gateway` — plugin dispatch works in the containerized deployment, not just a full checkout. Verified by actually building the image and running both `echo` and `ops-tool` through a live container (see `docs/xcloud-platform-plan.md` Phase 2); this required a locally-started `dockerd` and a temporary, uncommitted CA-trust workaround for this sandbox's TLS-intercepting proxy during `cargo build` only — the committed `Dockerfile` itself has no such workaround.

## Architecture: UI

`ui/` is a Vite + React app (`vite build` only; no dev-server script is defined in `package.json`, so `node_modules` must exist before running Vite directly). It does **not** get served by `hm-gateway` — `GET /` on the gateway returns JSON, not the UI's HTML. The UI is a separate static bundle that talks to the gateway over HTTP.

Key piece: `ui/src/endpoint-rotation.ts`. The UI is designed to fail over across multiple gateway endpoints (`primary` → `gateway-local` → `gateway-fallback`, configurable via `/platform-config.json`), health-checking each before dispatch and requiring a *recognizable* status/state/health JSON body (not just a 2xx) before trusting an endpoint as "online" — a bare 2xx from a misconfigured proxy or SPA fallback is treated as `unknown`, not `online`. The owner bearer token lives in the browser's `localStorage` (`hm_owner_token` key) and is attached to every outgoing request.

## The `ghm-core` pip package

`ghm_core/cli.py` is a real console-script CLI (`pip install -e .`), separate from the Rust CLI (`hm-cli`, which is *also* real — see the crate table above; the two are independent tools, not one real and one placeholder). Subcommands follow one hard rule established across this codebase: **anything that sends data off the machine or starts a network-reachable process must disclose exactly what it's about to do and require explicit consent before acting**, and must refuse loudly (nonzero exit + machine-readable reason) rather than silently no-op or silently act when run non-interactively without `--yes`. See `cmd_report_diagnostics` and `cmd_onboard_iphone` for the pattern; any new subcommand with similar side effects should follow it too.

- `report-diagnostics` — sends exactly four disclosed fields (`os_name`, `os_version`, `python_version`, `architecture`) to your own gateway's `/diagnostics`, gated by `HM_OWNER_TOKEN`.
- `onboard-iphone` — starts `hm-gateway` bound to `0.0.0.0:<port>` (LAN-reachable, never a public tunnel) and prints the URL + owner token to enter on an iPhone.

## Documentation map

- `docs/production-api-contract.md` — the authoritative reference for every gateway route, env var, and the `ghm-core` CLI subcommands. Update this when changing gateway behavior.
- `docs/master-dossier.html` — visual dossier (architecture, per-crate line counts, API reference); open in a browser.
- `docs/architecture.md` states the intended chain (`Gateway -> Agent Runtime -> Memory -> Channels -> Tools -> Plugins -> UI`) and, below it, which links are real vs. still placeholder — keep that table in sync when a stub crate becomes real.
- `docs/xcloud-platform-plan.md` — a staged, PoC-first roadmap (external memory backends via the existing `FileStorage` trait, cloud-portable deployment, graph-enhanced memory, an actual LLM-calling plugin, multi-instance failover). A plan, not a changelog — check it before assuming any of those phases already exist.
