# Architecture

Gateway -> Agent Runtime -> Memory -> Channels -> Tools -> Plugins -> UI.

This document corresponds to the uploaded Markdown sections for Fullstack Heavy Metal.

## Current implementation status of this chain

- **Gateway** (`crates/hm-gateway`): real. Hand-rolled async TCP HTTP server; see `docs/production-api-contract.md`.
- **Agent Runtime** (`crates/hm-agent`): real. `Agent::dispatch` is the actual `Gateway -> Agent Runtime` link: `POST /tasks` calls it instead of invoking `hm-plugins` directly.
- **Memory** (`crates/hm-memory`): real. `Agent::dispatch` is also the actual `Agent Runtime -> Memory` link: every task outcome (plugin-dispatched or unhandled) gets a one-line summary recorded via `MemoryStore::remember`, so `GET /memory` shows task history, not just what the UI explicitly submitted.
- **Channels** (`crates/hm-channels/hm-channel-*`): stub. Each only loads and validates a bot token; none makes real calls to Telegram/Discord/Slack/WhatsApp.
- **Tools** (`crates/hm-tools/hm-tool-*`): mostly stub, one real. `hm-tool-exec` is a real hm-plugins-protocol binary (`ops-tool` task_type) exposing a fixed, hardcoded allowlist of read-only ops checks (gateway status/logs, disk/memory usage) -- not arbitrary command execution. `hm-tool-browser`, `hm-tool-media`, `hm-tool-web` are still single-constant placeholders.
- **Plugins** (`crates/hm-plugins`): real. Subprocess dispatch by `task_type`, driven from `config/plugins.json`.
- **UI** (`ui/`): real, but separate -- it talks to the gateway over HTTP with endpoint rotation/failover; the gateway does not serve it.
