# System App Chat

`local_usr/sys/bin/system_app_chat.py` provides a local internal chat and event
bus for system components and apps. It is stdlib-only, stores data in SQLite,
and exposes both CLI and localhost HTTP access.

It is not a WhatsApp client.

## Initialize

```sh
python3 local_usr/sys/bin/system_app_chat.py init
python3 local_usr/sys/bin/system_app_chat.py validate
python3 local_usr/sys/bin/system_app_chat.py self-test
```

## Register An App

```sh
python3 local_usr/sys/bin/system_app_chat.py register \
  --app-id optimizer \
  --display-name "Optimizer" \
  --scopes send,read,heartbeat
```

The token is returned once and also stored locally in:

```text
local_usr/sys/etc/app_tokens/optimizer.token
```

## Send And Poll

```sh
TOKEN="$(cat local_usr/sys/etc/app_tokens/optimizer.token)"

python3 local_usr/sys/bin/system_app_chat.py post \
  --app-id optimizer \
  --token "$TOKEN" \
  --channel progress \
  --kind status \
  --metadata-json '{"component":"optimizer"}' \
  "optimizer ready"

python3 local_usr/sys/bin/system_app_chat.py poll \
  --app-id optimizer \
  --token "$TOKEN" \
  --channel progress \
  --limit 20
```

## Serve HTTP

```sh
python3 local_usr/sys/bin/system_app_chat.py serve
```

Default bind: `127.0.0.1:8787`

HTTP app authentication:

- Header `X-App-Id: <app_id>`
- Header `Authorization: Bearer <app_token>`

Admin routes use the admin token from:

```text
local_usr/sys/etc/system_app_chat.admin.token
```

## HTTP Routes

| Method | Path | Auth | Role |
| --- | --- | --- | --- |
| GET | `/health` | none | health and route discovery |
| GET | `/regulation` | none | WhatsApp/DMA boundary summary |
| GET | `/messages?channel=system&after=0&limit=50` | app token | poll messages |
| POST | `/messages` | app token | send message |
| POST | `/apps/heartbeat` | app token | update app heartbeat |
| GET | `/apps` | admin token | list registered apps |
| GET | `/metrics` | admin token | app/message/channel counts |

POST `/messages` body:

```json
{
  "channel": "progress",
  "kind": "status",
  "body": "optimizer ready",
  "recipient_app_id": null,
  "metadata": {
    "component": "optimizer"
  }
}
```

## Persisted Files

| Path | Role |
| --- | --- |
| `local_usr/sys/var/lib/system_app_chat/chat.sqlite3` | SQLite message bus |
| `local_usr/sys/etc/system_app_chat.config.json` | service config |
| `local_usr/sys/etc/system_app_chat.admin.token` | local admin token |
| `local_usr/sys/etc/app_tokens/*.token` | local per-app tokens |
| `local_usr/sys/var/run/system_app_chat.validation.json` | latest validation |
| `local_usr/sys/var/log/system_app_chat.events.jsonl` | audit-like service events |

## Safety Boundary

The module rejects direct shell execution by design. It transports messages,
events, commands-as-data, and status records; consumers decide what to do with
messages after their own validation and authorization checks.
