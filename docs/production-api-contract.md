# Production API Contract

## Service

`hm-gateway` exposes the production task control API used by the UI control plane.

## Runtime environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `HM_GATEWAY_BIND` | `config/heavy-metal.json`'s `server.bind`, else `0.0.0.0:8080` | TCP bind address |
| `HM_ZERO_STAKED` | `false` | Forces health and task responses into `zero_staked` failover status when true |
| `HM_STORAGE_ROOT` | `./data/storage` | Local-disk root for the `/storage` file API (see `hm-storage` crate) |
| `HM_MEMORY_KEY` | `memory/index.json` | Storage key (under `HM_STORAGE_ROOT`) where `hm-memory` persists its index |
| `HM_OWNER_TOKEN` | *(required)* | Bearer token gating every route. The process refuses to start without it. |
| `HM_GATEWAY_ALLOW_NO_AUTH` | `false` | Explicit opt-out (`true` exactly) to run with no authentication -- local development only, never in a reachable deployment |
| `HM_DIAGNOSTICS_KEY` | `diagnostics/reports.json` | Storage key (under `HM_STORAGE_ROOT`) where submitted diagnostics reports are persisted |
| `HM_RATE_LIMIT_PER_MINUTE` | `120` | Max requests per source IP per 60s window before `429`; `0` disables rate limiting entirely |

## Observability and abuse protection

Every request produces one structured JSON line on stdout (`{"audit": true, "ts_unix", "remote_addr", "method", "path", "status", "latency_ms"}`), checked before doing any real work so it also covers rejected/rate-limited requests. Under `deploy/hm-gateway.service` (the shipped systemd unit), stdout goes straight to journald -- `journalctl -u hm-gateway -o cat | grep '"audit"'` is a real, queryable audit trail with no extra logging infrastructure required.

Requests are additionally rate-limited per source IP (`HM_RATE_LIMIT_PER_MINUTE`, default 120/minute, fixed window) *before* the request is even read off the socket -- an abusive client is rejected with `429` before it can make the gateway parse a body, run auth, or dispatch a task. This is in-process and per-instance (not shared across multiple gateway replicas); a shared/distributed limiter is a Phase 5/scaling concern, not something this single-instance gateway claims to solve.

```console
# client side:
$ curl http://localhost:8080/health
HTTP/1.1 401 Unauthorized
{"status":"unauthorized","reason":"missing or invalid bearer token"}

# server-side stdout, one line per request, independent of the client's response:
{"audit":true,"ts_unix":1783374080,"remote_addr":"127.0.0.1:55854","method":"GET","path":"/health","status":401,"latency_ms":0}

# client side, after HM_RATE_LIMIT_PER_MINUTE requests within 60s from the same IP:
$ curl http://localhost:8080/health
HTTP/1.1 429 Too Many Requests
{"status":"rate_limited","reason":"too many requests from this client"}
```

## Authentication

Every route (including `/health`) requires `Authorization: Bearer <HM_OWNER_TOKEN>`
unless the gateway was started with `HM_GATEWAY_ALLOW_NO_AUTH=true`. Missing or
incorrect tokens get `401`, with a generic reason that doesn't reveal which part was
wrong. Token comparison is constant-time (`hm_auth::tokens_match`) to resist timing
attacks. `OPTIONS` (CORS preflight) is exempt since it carries no data.

```console
$ curl http://localhost:8080/health
HTTP/1.1 401 Unauthorized
{"status":"unauthorized","reason":"missing or invalid bearer token"}

$ curl -H "Authorization: Bearer $HM_OWNER_TOKEN" http://localhost:8080/health
HTTP/1.1 200 OK
{"service":"hm-gateway","status":"online",...}
```

The UI stores the token in the browser's `localStorage` (see "UI integration" below)
and sends it on every request; it is never logged or echoed back by the gateway.

## Health endpoints

```http
GET /health
GET /api/health
GET /gateway/health
```

Successful online response:

```json
{
  "service": "hm-gateway",
  "status": "online",
  "zero_staked": false,
  "agent_managed": true,
  "task_count": 0,
  "uptime_seconds": 1,
  "checked_at_unix": 0
}
```

Failover response when `HM_ZERO_STAKED=true`:

```json
{
  "service": "hm-gateway",
  "status": "zero_staked",
  "zero_staked": true,
  "agent_managed": true
}
```

## Task dispatch endpoints

```http
POST /tasks
POST /api/tasks
POST /gateway/tasks
```

Request:

```json
{
  "taskType": "analyze",
  "objective": "Validate production readiness",
  "payload": {}
}
```

Accepted response:

```json
{
  "status": "online",
  "accepted": true,
  "task_id": "task-...",
  "task_type": "analyze",
  "agent_managed": true
}
```

When the gateway is in zero-staked mode, task dispatch returns HTTP 503 with status `zero_staked`; the UI rotates to the next configured endpoint.

Every accepted task is routed through `hm-agent`'s `Agent::dispatch` (not
invoked directly against `hm-plugins`): if a plugin is registered for
`taskType` in `config/plugins.json`, it runs and the response gains a
`plugin_result` field (`{"ok", "result", "message"}`), exactly as before.
If no plugin matches, the response shape is unchanged (no extra field) --
but either way, `Agent::dispatch` also records a one-line summary of the
outcome into `hm-memory`, so `GET /memory` shows a durable history of what
every task actually did, not just what was explicitly `POST`ed to `/memory`.

## Task registry endpoint

```http
GET /tasks
GET /api/tasks
GET /gateway/tasks
```

Returns the in-memory task registry for the current gateway process.

## File storage endpoints

```http
PUT    /storage/{key}
GET    /storage/{key}
DELETE /storage/{key}
```

Backed entirely by local disk via the `hm-storage` crate (`LocalFsStorage`), rooted at
`HM_STORAGE_ROOT`. No external or remote storage target is involved. Keys are relative
paths (e.g. `notes/hello.txt`); parent segments (`..`) and absolute paths are rejected.

```console
$ curl -X PUT --data-binary @report.json http://localhost:8080/storage/reports/report.json
{"status":"stored","key":"reports/report.json","bytes":812}

$ curl http://localhost:8080/storage/reports/report.json
{...}

$ curl -X DELETE http://localhost:8080/storage/reports/report.json
{"status":"deleted","key":"reports/report.json"}
```

Requests are capped at `MAX_REQUEST_BYTES` (1,048,576 bytes / 1 MiB) at the HTTP layer;
larger uploads are rejected with `413`.

## Plugin dispatch (hm-plugins / hm-sdk)

`POST /tasks` invokes a matching plugin, if one is registered for the request's
`taskType`, and includes its result under `plugin_result` in the response. Plugins
are external processes, defined in a JSON manifest (`HM_PLUGIN_MANIFEST`, default
`config/plugins.json`) that maps a `task_type` to a fixed command:

```json
{
  "plugins": [
    { "task_type": "echo", "command": ["python3", "plugins/echo_plugin.py"] },
    { "task_type": "ops-tool", "command": ["target/release/hm-tool-exec"] }
  ]
}
```

Protocol: the gateway writes one `PluginRequest` JSON line (`task_type`, `objective`,
`payload`) to the plugin's stdin, and reads one `PluginResponse` JSON line (`ok`,
`result`, `message`) back from its stdout, with a 5-second timeout. A client can only
*select* a `task_type` already present in the manifest -- the command executed is
always the one fixed in that checked-in file, never derived from request input.
Missing/invalid plugin output surfaces as `plugin_result.ok: false` without failing
the task dispatch itself.

See `crates/hm-sdk` for the request/response types and `plugins/echo_plugin.py` for
a minimal working example.

### `ops-tool` (`crates/hm-tools/hm-tool-exec`)

The first real `hm-tools/*` crate (the rest are still 1-line stubs). Deliberately
**not** an arbitrary-command-execution plugin: `payload.operation` only ever
*selects* one entry from a fixed, hardcoded allowlist (`gateway_status`,
`gateway_logs`, `disk_usage`, `memory_usage`) -- it never contributes to argv
construction, so there is no command-injection surface regardless of what a
caller sends. Every allowlisted operation is read-only.

```console
$ curl -X POST http://localhost:8080/tasks -H "Authorization: Bearer $HM_OWNER_TOKEN" \
    -d '{"taskType":"ops-tool","objective":"check disk","payload":{"operation":"disk_usage"}}'
{"accepted":true,"plugin_result":{"ok":true,"result":{"operation":"disk_usage","stdout":"...","stderr":""},...},...}
```

**Known packaging gap**: the root `Dockerfile`'s runtime stage only copies the
`hm-gateway` binary -- it does not copy `plugins/`, `config/`, a Python
interpreter, or `hm-tool-exec`. This means plugin dispatch (`echo` *and*
`ops-tool`) does not actually work in the Docker deployment as currently
packaged; it only works when running `hm-gateway` directly from a full
checkout (as `docker-compose.yml`'s bind-mounted dev setup and every example
in this document do). Not fixed here -- packaging plugins into the runtime
image is a separate decision.

## Memory endpoints (hm-memory / hm-vector)

```http
GET  /memory
POST /memory
POST /memory/search
```

A persistent, semantically-searchable text memory, backed by `hm-storage` (so it
survives process restarts) and `hm-vector`'s cosine-similarity index. Embeddings are
a deterministic, fully offline hashing-trick bag-of-words (`hm_vector::embed`) -- no
external model, no API key, no network call. This captures lexical/word-overlap
similarity, not learned deep semantics; swapping in a real embedding model later is a
drop-in replacement for `embed()` behind the same `MemoryStore` API.

```console
$ curl -X POST http://localhost:8080/memory -d '{"text":"the gateway exposes a storage API"}'
{"status":"stored","record":{"id":"mem-...","text":"...","created_at_unix":...}}

$ curl -X POST http://localhost:8080/memory/search -d '{"query":"storage api on the gateway","topK":5}'
{"status":"online","results":[{"record":{...},"score":0.57}, ...]}

$ curl http://localhost:8080/memory
{"status":"online","records":[...]}
```

## UI integration

`ui/src/main.ts` has a "Memory" panel calling the endpoints above through the same
priority-ordered endpoint rotation as task dispatch (`ui/src/endpoint-rotation.ts`), and
an "Owner access" panel for entering the bearer token, persisted in `localStorage` and
attached as `Authorization: Bearer <token>` to every gateway request.

**Found and fixed while adding auth**: `detectState()` in `endpoint-rotation.ts`
defaulted any 2xx response it couldn't parse into a known status/state/health shape to
`"online"`. Serving the UI via a static file server with SPA fallback (e.g. `vite
preview`, or any nginx `try_files ... /index.html` config) returns `200` with the app's
own HTML for an unmatched path like `/api/health` -- which this code then treated as a
healthy gateway. Live-tested: with an incorrect owner token, this masked real `401`s
from the actual gateway behind a confusing `memory_store_failed_404` from the fake
"online" endpoint instead. Fixed by requiring a recognized status/state/health field
before returning anything other than `"unknown"` (treated the same as offline).

**Known gap**: the `primary` (`/api`) and `gateway-fallback` (`/gateway`) endpoints in
`ui/public/platform-config.json` assume a reverse proxy stripping that prefix before
forwarding to `hm-gateway` -- no such proxy exists in `ui/Dockerfile` (plain nginx,
static files only) or anywhere else in this repo, so in the `docker-compose` deployment
those two always fail and every request falls through to `gateway-local`
(`http://127.0.0.1:8080`, a direct URL). This was true before the memory panel existed
and is unrelated to it; not fixed here since there's no Docker daemon available in this
environment to verify an nginx proxy config end-to-end.

## Diagnostics endpoints

```http
GET  /diagnostics
POST /diagnostics
```

Persistent, opt-in-only diagnostics reports (OS name, OS version, Python version,
architecture -- exactly these four fields, nothing else), submitted by the
`ghm-core report-diagnostics` CLI (see below) and gated by the same owner bearer
token as every other route.

```console
$ curl -X POST http://localhost:8080/diagnostics \
    -H "Authorization: Bearer $HM_OWNER_TOKEN" \
    -d '{"os_name":"Linux","os_version":"6.18.5","python_version":"3.11.15","architecture":"x86_64"}'
{"status":"stored","report":{...,"reported_at_unix":...}}

$ curl -H "Authorization: Bearer $HM_OWNER_TOKEN" http://localhost:8080/diagnostics
{"status":"online","reports":[...]}
```

### `ghm-core report-diagnostics` (pip package)

`ghm_core` is now a real installable package (`pyproject.toml` at the repo root,
console script `ghm-core`; `pip install -e .` for local use). Its
`report-diagnostics` subcommand:

1. Prints the exact fields it's about to send (never anything beyond `os_name`,
   `os_version`, `python_version`, `architecture`) and the destination URL.
2. Requires explicit consent -- an interactive `[y/N]` prompt, or `--yes` for
   scripted use. **Never sends anything in a non-interactive run without `--yes`**
   (exits `1` with a clear reason instead of silently no-op'ing or silently sending).
3. Reads the bearer token from `HM_OWNER_TOKEN` in the environment; refuses to send
   (exits `1`) if it's unset, rather than sending unauthenticated and getting a
   confusing `401` back.

```console
$ pip install -e .
$ HM_OWNER_TOKEN=... ghm-core report-diagnostics
This will send exactly these fields, nothing else, to your own gateway:
{ "os_name": "Linux", "os_version": "6.18.5", "python_version": "3.11.15", "architecture": "x86_64" }
Destination: http://127.0.0.1:8080/diagnostics
Send this? [y/N]:
```

### `ghm-core onboard-iphone` (pip package)

Ties `hm-gateway` to an iPhone on the same Wi-Fi/LAN. Unlike
`report-diagnostics`, this command starts a process and binds a port, so it
discloses more and is gated the same way:

1. Locates the `hm-gateway` binary (`--gateway-bin`, else `PATH`, else
   `target/release/` or `target/debug/`) and refuses immediately with a clear
   `hint` if none is found -- it never attempts to build one itself.
2. Prints exactly what it is about to do -- bind address/port, that this
   makes the gateway reachable by any device on the local network (not just
   this machine), and where the owner token will be stored -- before doing
   anything.
3. Requires explicit consent, with the same non-interactive-refuses-without-
   `--yes` property as `report-diagnostics`.
4. On consent: generates (or reuses) an owner token, writes it to
   `<workspace>/settings/iphone_owner_token` (`chmod 600`), starts
   `hm-gateway` with `HM_OWNER_TOKEN` set and `HM_GATEWAY_BIND=0.0.0.0:<port>`,
   waits for an authenticated health check to succeed, then prints the LAN
   URL and token to enter on the iPhone. No public-internet tunnel is created.

```console
$ ghm-core onboard-iphone --workspace ~/Developer/scratch/ghm --yes
This will:
  1. Start hm-gateway (...) bound to 0.0.0.0:8080 -- reachable by
     ANY device on your local network/Wi-Fi, not just this machine.
  2. Store an owner token at .../settings/iphone_owner_token (chmod 600), generating one if none exists.
  3. Print a URL and token for you to enter on your iPhone: http://192.168.1.23:8080
No tunnel to the public internet is created; nothing leaves your local network.
{ "ok": true, "started": true, "pid": ..., "gateway_url": "http://192.168.1.23:8080", "token_path": "..." }

On your iPhone (same Wi-Fi), open the gateway UI and enter:
  Gateway URL: http://192.168.1.23:8080
  Bearer token: ...
```

## Channel bot tokens (hm-auth)

Each `hm-channel-*` crate exposes `bot_token()`, which loads and validates
`HM_<CHANNEL>_BOT_TOKEN` (e.g. `HM_TELEGRAM_BOT_TOKEN`) via `hm_auth::load_bot_token`.
It returns a clear error -- never the token itself -- when the variable is unset,
empty, or contains whitespace. This is the token-loading mechanism only: no channel
crate yet makes real calls to Telegram/Discord/Slack/WhatsApp, since that requires
real bot credentials to build and live-test responsibly.

## Persistence and hardening (production deployment)

`hm-gateway` handles `SIGTERM`/`SIGINT` by draining in-flight connections
(up to a 10s deadline) and exiting with status 0, so a process supervisor
can stop it cleanly instead of hard-killing it.

`deploy/hm-gateway.service` is a systemd unit for running it as a
persistent, always-on host service: `Restart=on-failure` recovers from
crashes, and a hardened sandbox (`ProtectSystem=strict`, `NoNewPrivileges`,
dropped capabilities, `MemoryMax`/`CPUQuota`/`TasksMax` limits, a dedicated
non-root user) limits what a compromised or misbehaving process can touch.
See the comments in that file for install steps; verify edits to it with
`systemd-analyze verify deploy/hm-gateway.service`.

`Restart=on-failure` alone does not catch a process that's alive but wedged
(deadlocked, exhausted file descriptors, etc.) and no longer answering
requests. `scripts/hm_gateway_watchdog.py` closes that gap: a one-shot,
stdlib-only script that makes one authenticated `GET /health` request and,
on failure, runs `systemctl restart` on the unit. `deploy/hm-gateway-watchdog.timer`
runs it every 30 seconds.

`docker-compose.yml`'s `gateway` service also carries `restart: unless-stopped`,
`cap_drop: ["ALL"]`, and `no-new-privileges:true` -- verified changes only
(`docker compose config` was used to check syntax; there is no verified
non-root-user or read-only-rootfs hardening for the container path yet,
since that needs an actual container build+run pass to confirm volume
permissions don't break on first boot).

**Known drift, not yet reconciled**: `deploy/fullstack-compose.yml` runs a
completely different, trivial placeholder (`deploy/gateway_service.py`, a
stdlib `BaseHTTPRequestHandler` with no auth/plugins/memory/storage) under
the name "gateway" -- it is unrelated to `crates/hm-gateway` and does not
read any of the `HM_*` variables `.env.production.example` sets up for the
real gateway. Don't assume `deploy/fullstack-compose.yml` deploys the real
gateway; it currently doesn't.

## Operational guarantees

- every route requires the owner bearer token unless explicitly opted out
  (`HM_GATEWAY_ALLOW_NO_AUTH=true`); the gateway process itself refuses to start
  without one configured;
- the owner token is the one client-side secret in this system -- held only in the
  browser's `localStorage`, never logged, never committed to the repo;
- fixed endpoint list from `ui/public/platform-config.json`;
- timeout-based endpoint checks;
- zero_staked failover;
- CORS support for configured frontend use, restricted to the methods and headers
  this API actually uses;
- plugin commands are fixed by the checked-in manifest, never by request input --
  a client selects a registered `task_type`, it cannot supply arbitrary commands.
