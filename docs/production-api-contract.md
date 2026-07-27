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
| `HM_STORAGE_BACKEND` | `local` | `local` (uses `HM_STORAGE_ROOT`) or `remote` (uses `HM_REMOTE_STORAGE_URL`/`HM_REMOTE_STORAGE_TOKEN`) -- see "External memory place" below |
| `HM_REMOTE_STORAGE_URL` | *(unset)* | Required when `HM_STORAGE_BACKEND=remote`: a plain `http://host:port` URL of another `hm-gateway`-compatible `/storage` endpoint |
| `HM_REMOTE_STORAGE_TOKEN` | *(unset)* | Bearer token sent with every request to `HM_REMOTE_STORAGE_URL`, if that endpoint requires auth (it should) |
| `HM_MEMORY_GRAPH_SEED_PATH` | *(unset)* | Path to a `scripts/generate_knowledge_graph_seed.py`-shaped JSON file (`{"nodes":[...],"edges":[...]}`), ingested into `hm-memory` at startup -- see "Graph-enhanced memory" below. A missing or malformed file logs a warning and does not block startup. A live seed exists at `data/graph-seed.json` (50 nodes, 72 edges). |
| `HM_CRON_CONFIG` | `config/cron.json` | Path to the cron job manifest loaded by `hm-cron` at gateway startup. Jobs run as background `POST /tasks` calls to the gateway itself. Missing file = cron silently disabled. |
| `HM_PLUGIN_MANIFEST` | `config/plugins.json` | Path to the plugin registry mapping `task_type` → subprocess command. |

## External memory place (`hm-storage::RemoteHttpStorage`)

`FileStorage` (the trait `hm-storage` and everything built on it -- `hm-memory`, the `/storage` routes -- are generic over) has a second implementation alongside `LocalFsStorage`: `RemoteHttpStorage`, which persists every `put`/`get`/`delete`/`exists` call to another host's `/storage/{key}` endpoint instead of local disk. Set `HM_STORAGE_BACKEND=remote` + `HM_REMOTE_STORAGE_URL` to point a gateway at external storage -- most naturally, a second `hm-gateway` instance acting purely as a storage node.

Deliberately a hand-rolled plain-HTTP client (no TLS, no external HTTP crate dependency), matching this codebase's existing style, and intended for a private/internal network -- the same trust model already assumed for `HM_GATEWAY_ALLOW_NO_AUTH` and LAN-bound deployments. Never point `HM_REMOTE_STORAGE_URL` at a host over the open internet without a TLS-terminating proxy in front of it.

`HM_STORAGE_BACKEND=remote` without a valid `HM_REMOTE_STORAGE_URL` fails the gateway at startup rather than silently falling back to local disk -- an operator who asked for external storage and got local storage instead, without being told, would be a correctness bug.

**Verified live** (two real `hm-gateway` processes, not simulated): a `POST /memory` on a "primary" instance configured with `HM_STORAGE_BACKEND=remote` pointed at a second "storage node" instance produced zero files on the primary's own disk (its `HM_STORAGE_ROOT` directory was never even created) and the real, complete memory index (including embedding vectors) landed on the storage node, retrievable independently via that node's own `/storage/memory/index.json`.

## Graph-enhanced memory (`GET /memory/graph`)

`hm-memory`'s `MemoryStore` can hold, alongside its free-text records, exactly one structural knowledge-graph seed -- the `{"nodes":[...],"edges":[...]}` shape `scripts/generate_knowledge_graph_seed.py` produces. It is stored and served distinctly from free-text memory: ingesting a graph seed never appears in `GET /memory`'s records, and free-text `remember`/`recall` never touch the graph.

Ingestion happens once, at gateway startup, from `HM_MEMORY_GRAPH_SEED_PATH` if set (there is no route to upload a graph at runtime). Re-ingesting on a later restart with a different file replaces the previous graph rather than accumulating.

```
GET /memory/graph
```

Returns `200 {"status": "online", "graph": {...}}` with the ingested graph as-is, or `404 {"status": "not_found", "reason": "no graph seed has been ingested"}` if `HM_MEMORY_GRAPH_SEED_PATH` was never set or ingestion failed.

**Verified live**: ran a real `hm-gateway` process with `HM_MEMORY_GRAPH_SEED_PATH` pointed at a freshly generated `scripts/generate_knowledge_graph_seed.py` seed (37 nodes, 65 edges); `GET /memory/graph` returned that exact graph over HTTP (401 without the owner bearer token, 200 with it), the seed was confirmed persisted verbatim in the storage-backed index file on disk, and `GET /memory` remained empty throughout, confirming no cross-contamination.

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

`taskType` is the documented field name. `task_type` is accepted as an alias,
because it is what several clients sent for a long time while the gateway bound
only the camelCase spelling -- see "The `taskType` contract" below.

**`taskType` is required.** A request without it, or with a blank one, is
rejected with HTTP 400 and `accepted: false`. It used to be accepted and
recorded as `"unspecified"`, which meant the gateway promised work it could
never perform: no plugin matches `"unspecified"`, so nothing ran.

Accepted response:

```json
{
  "status": "online",
  "accepted": true,
  "task_id": "task-...",
  "task_type": "analyze",
  "agent_managed": true,
  "dispatch": "plugin_dispatched",
  "plugin_result": { "ok": true, "result": {}, "message": "..." }
}
```

`dispatch` is always present and is either `plugin_dispatched` or `unhandled`.
For `unhandled` there is no `plugin_result`; instead `dispatch_reason` names
the task type that matched nothing:

```json
{
  "status": "online",
  "accepted": true,
  "task_id": "task-...",
  "task_type": "no-such-plugin",
  "agent_managed": true,
  "dispatch": "unhandled",
  "dispatch_reason": "no plugin registered for task_type 'no-such-plugin'"
}
```

Previously "nothing ran" was expressed only by the *absence* of
`plugin_result` -- a caller had to know to look for a field that isn't there.

When the gateway is in zero-staked mode, task dispatch returns HTTP 503 with status `zero_staked`; the UI rotates to the next configured endpoint.

Every accepted task is routed through `hm-agent`'s `Agent::dispatch` (not
invoked directly against `hm-plugins`): if a plugin is registered for
`taskType` in `config/plugins.json`, it runs and the response gains a
`plugin_result` field (`{"ok", "result", "message"}`). Either way,
`Agent::dispatch` also records a one-line summary of the outcome into
`hm-memory`, so `GET /memory` shows a durable history of what every task
actually did, not just what was explicitly `POST`ed to `/memory`.

### The `taskType` contract

The request type is `hm_sdk::TaskSubmission`, shared by the gateway and every
producer rather than re-declared per crate. That is not tidiness; it is the
fix for a defect that survived a fully green test suite.

The gateway bound the field as `taskType`. `hm-cli`, `hm-cron` and all four
channel crates sent `task_type`. Because the field carries
`#[serde(default)]`, the mismatch produced an empty string instead of a
parse error, so the gateway answered `202 accepted: true` and dispatched to
no plugin at all. Measured on a live gateway: **every one of the six
scheduled cron jobs, and every task submitted through the CLI, ran nothing** --
without a single error anywhere.

Three things now hold, and each covers a different way the failure could
return:

| Guard | Where | Covers |
|---|---|---|
| One shared type | `hm_sdk::TaskSubmission` | Producer and consumer are the same declaration, so they cannot drift apart |
| `alias = "task_type"` | same type | Clients *outside* this repository, which a rename cannot reach |
| End-to-end contract test | `crates/hm-gateway/tests/wire_contract.rs` | Spawns the real binary and asserts the plugin received the task type |

The test imports nothing from the gateway on purpose: the defect lived exactly
in the gap between components that were each tested against themselves.

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
    { "task_type": "ops-tool", "command": ["target/release/hm-tool-exec"] },
    { "task_type": "llm-chat", "command": ["python3", "plugins/llm_chat_plugin.py"] }
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

**Packaging gap, fixed and live-verified**: the root `Dockerfile`'s runtime
stage previously only copied the `hm-gateway` binary -- no `plugins/`,
`config/`, Python interpreter, or `hm-tool-exec` -- so plugin dispatch
(`echo` *and* `ops-tool`) did not actually work in the Docker deployment as
packaged, only when running `hm-gateway` directly from a full checkout. The
runtime stage now installs `python3` and copies `config/`, `plugins/`, and
the `hm-tool-exec` binary alongside `hm-gateway`.

**Verified live, not just inspected**: built the actual image (`docker
build .`), ran it as a real container, and dispatched both `POST /tasks`
`taskType: "echo"` and `taskType: "ops-tool"` (`operation: "disk_usage"`)
against it over HTTP -- both returned real `plugin_result.ok: true`, proving
the fix, not just the Dockerfile diff. (This sandbox has no running Docker
daemon by default -- one was started manually for this one verification,
and `cargo build`'s access to crates.io through this sandbox's TLS-
intercepting proxy required a temporary, uncommitted CA-trust step used only
for that local test build; the actual committed `Dockerfile` has no such
workaround and is unchanged from a normal production Dockerfile's shape.)

### `llm-chat` (`plugins/llm_chat_plugin.py`) -- scaffold, not live-verified

The first (and only) plugin in this repo that calls a real third-party API.
Targets a generic OpenAI-compatible `/chat/completions`-shaped endpoint.
Refuses to run -- with a machine-readable `result.reason`, `ok: false` --
unless **all** of `HM_LLM_ENABLE=true`, `HM_LLM_API_URL`, `HM_LLM_API_KEY`,
and `HM_LLM_MODEL` are explicitly set; no default model or endpoint is
invented. Discloses exactly what it's about to send (destination URL, model,
message length -- never the message body) to stderr before every call, per
this codebase's off-machine-data disclosure rule (`ghm_core/cli.py`'s
`cmd_report_diagnostics`).

**Not live-verified**: no real LLM API credentials or egress exist in this
environment. `tests/test_llm_chat_plugin.py` exercises the refusal paths, a
successful round-trip, an upstream error, and an unreachable host against a
hermetic local mock HTTP server -- proving the plugin's own logic, not a
real provider round-trip. See `docs/xcloud-platform-plan.md`'s Phase 4 for
the exact scope disclosure.

## Memory endpoints (hm-memory / hm-vector)

```http
GET  /memory
POST /memory
POST /memory/search
GET  /memory/graph
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

`topK` also accepts `top_k`, for the same reason `taskType` accepts
`task_type`: `hm-cli memory recall --top-k N` sent the snake_case spelling,
which bound to nothing and silently fell back to the default. The flag was
accepted, reported nowhere, and ignored -- a request for 2 results returned 5.

`POST /memory` takes `{"text": "..."}`. It is a free-text memory with semantic
recall, **not** a key/value store -- that is `/storage/{key}`. `hm-cli memory
store` used to send `{"key", "value"}` and was answered with HTTP 400 on every
invocation; its signature is now `hm-cli memory store <text>`.

## Chat / command stream (`POST /chat`)

```http
POST /chat          (also /api/chat, /gateway/chat)
Authorization: Bearer $HM_OWNER_TOKEN
Content-Type: application/json

{"line": "/tiers", "files": ["crates/hm-gateway/src/main.rs"]}
```

The single surface through which the system is commanded. It is the only route
that streams: the response has **no `Content-Length`**, uses
`Content-Type: text/event-stream` with `Connection: close`, and each line the
brain emits is flushed to the socket before the next is computed.

Behind it is `agents/brain.py`, not a model. A line starting with `/` selects a
command from a fixed table (`/help` lists it); anything else is a question,
answered on the best tier that is actually available -- local GGUF, then a
keyless provider through the oracle gate, then a no-model answer that cites
repository evidence instead of inventing prose. **No tier requires Anthropic**;
`tests/test_brain.py` proves it by running with every `ANTHROPIC*` variable
stripped from the environment.

Each SSE event carries one NDJSON object from the brain, passed through
verbatim: `{"typ": "info"|"token"|"fehler"|"ende", "text": ..., "meta": {...}}`.
The stream ends with `data: [DONE]`. The gateway does not parse the payload --
the event vocabulary belongs to the brain, and a gateway that understood it
would need changing every time an event type is added.

| Env var | Default | Meaning |
|---|---|---|
| `HM_BRAIN_REPO` | `.` | Working directory for the brain subprocess |
| `HM_BRAIN_PYTHON` | `python3` | Interpreter used to run it |

Input limits, enforced before the first byte of body: line non-empty and
≤ 32 KiB, at most 16 context files, and every file a plain relative path --
an entry starting with `-` is rejected because it would reach the brain as an
option rather than as an argument. The body *chooses*; it never constructs a
command line, and no shell is involved anywhere in the path.

Clients must use `fetch()` + `ReadableStream`, not `EventSource`: `EventSource`
cannot set an `Authorization` header, and this route is bearer-gated like every
other.

```console
$ curl -N -X POST http://localhost:8080/chat \
    -H "Authorization: Bearer $HM_OWNER_TOKEN" -d '{"line":"/tiers"}'
data: {"typ": "token", "text": "[x] T0   Befehle, Pruefungen, Belege — braucht kein Modell"}

data: {"typ": "token", "text": "[ ] T1b  fehlt: models/model.gguf ..."}

data: {"typ": "ende", "text": "", "meta": {"tier": "T0"}}

data: [DONE]
```

**Verified live**: run against a real `hm-gateway` process on a real socket --
401 without the token, `400` with `{"files":["--json"]}`, and a `/tests` turn
whose first event arrived after 0.11 s while the run itself took 10.7 s,
confirming the stream is incremental rather than buffered.

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

**Multi-instance failover, verified live**: `scripts/verify_multi_instance_failover.mjs`
imports `endpoint-rotation.ts` unmodified and runs it against two real, independently
spawned `hm-gateway` processes -- confirms a real dispatch lands on the priority-1
instance, then, after that process is actually killed, confirms the identical dispatch
call fails over to the priority-2 instance. Both instances run on this same host
(disclosed scope: proves the rotation algorithm, not a multi-region deployment -- see
`docs/xcloud-platform-plan.md` Phase 5).

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

## Session API (`/sessions/*`)

In-memory conversation session store backed by `hm-sessions::SessionStore`. Sessions are not persisted to disk — they live only while the gateway process is running. All routes require the owner bearer token.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/sessions` | List all session IDs and names |
| `POST` | `/sessions` | Create a new session; body: `{"name":"optional-label"}` |
| `GET` | `/sessions/{id}` | Fetch a session and its full message history |
| `POST` | `/sessions/{id}` | Append a message; body: `{"role":"user","content":"..."}` |
| `DELETE` | `/sessions/{id}` | Delete a session |

## Cron scheduler (`hm-cron`)

`hm-cron` runs as a `tokio::spawn`-ed background task inside `hm-gateway`. On startup it loads `HM_CRON_CONFIG` (default `config/cron.json`), derives a `JobState` per entry, and submits each due job as a `POST /tasks` to `http://{HM_GATEWAY_BIND}` with the owner token. The bearer token used for internal cron calls is the same `HM_OWNER_TOKEN` the gateway itself was started with. If `HM_CRON_CONFIG` does not exist, the cron scheduler is silently disabled — no panic, no log noise.

Example `config/cron.json`:
```json
[
  {
    "name": "heartbeat",
    "task_type": "echo",
    "payload": { "msg": "cron-heartbeat" },
    "interval_secs": 3600
  }
]
```

## Autonomy layer (Python, out-of-process)

`scripts/autonomy_core.py` and `scripts/repo_tracker.py` are not part of the Rust gateway binary. They run as separate Python processes and interact with the gateway only via its HTTP API (same bearer-token auth). They are the self-monitoring / self-healing / self-documentation layer of the platform and are tracked in `.claude/persona/autonomy-state.json`.
