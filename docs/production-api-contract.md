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

## Channel bot tokens (hm-auth)

Each `hm-channel-*` crate exposes `bot_token()`, which loads and validates
`HM_<CHANNEL>_BOT_TOKEN` (e.g. `HM_TELEGRAM_BOT_TOKEN`) via `hm_auth::load_bot_token`.
It returns a clear error -- never the token itself -- when the variable is unset,
empty, or contains whitespace. This is the token-loading mechanism only: no channel
crate yet makes real calls to Telegram/Discord/Slack/WhatsApp, since that requires
real bot credentials to build and live-test responsibly.

## Operational guarantees

- no client-side secrets;
- fixed endpoint list from `ui/public/platform-config.json`;
- timeout-based endpoint checks;
- zero_staked failover;
- CORS support for configured frontend use;
- plugin commands are fixed by the checked-in manifest, never by request input --
  a client selects a registered `task_type`, it cannot supply arbitrary commands.
