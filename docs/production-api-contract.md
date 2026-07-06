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
{ "plugins": [{ "task_type": "echo", "command": ["python3", "plugins/echo_plugin.py"] }] }
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

## Channel bot tokens (hm-auth)

Each `hm-channel-*` crate exposes `bot_token()`, which loads and validates
`HM_<CHANNEL>_BOT_TOKEN` (e.g. `HM_TELEGRAM_BOT_TOKEN`) via `hm_auth::load_bot_token`.
It returns a clear error -- never the token itself -- when the variable is unset,
empty, or contains whitespace. This is the token-loading mechanism only: no channel
crate yet makes real calls to Telegram/Discord/Slack/WhatsApp, since that requires
real bot credentials to build and live-test responsibly.

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
