# Standalone AI Platform Roadmap: external memory + cloud-portable deployment

## What this document is

A proof-of-concept-first, staged plan for extending the existing Fullstack
Heavy Metal stack (`hm-gateway` + `hm-agent` + `hm-memory` + `hm-plugins`)
into a genuinely standalone, cloud-portable AI platform with memory storage
that can live outside the single host the gateway runs on. **This is a plan,
not a changelog** — nothing described below as a future phase has been built
yet. Phase 0 is what already exists and is verified; phases 1-5 are ordered,
independently PR-sized worksteps, each with a concrete "done" condition, so
any one of them can be picked up on its own without committing to the rest.

Every phase builds on a real, already-verified seam in the current code —
none of this requires a rewrite. Where a phase depends on a decision only a
human can make (which cloud, which credentials, which LLM provider), that's
called out explicitly rather than guessed.

## Phase 0 — Foundation (done, verified this session)

- `hm-gateway`: hand-rolled async TCP server, owner-token auth, graceful
  `SIGTERM`/`SIGINT` shutdown, systemd unit with real hardening + a health
  watchdog (`deploy/hm-gateway.service`, `deploy/hm-gateway-watchdog.timer`).
- `hm-agent`: real task dispatch → plugin invocation → memory recording link
  (previously a disconnected stub).
- `hm-plugins`: subprocess plugin protocol, two registered plugins (`echo`,
  `ops-tool`), the latter a real allowlisted ops-check tool.
- `hm-memory`: flat, persistent, offline-embedded semantic memory
  (`MemoryStore`), backed by `hm-storage`'s `FileStorage` trait.
- `scripts/generate_knowledge_graph_seed.py`: live-introspected structural
  graph of the repo itself (crates, dependencies, plugins, skills, docs) —
  today's seed export, verified against 9 tests.
- Two Claude Code Skills (`xcode-alternative`, `pr-bot-triage`) as reusable,
  tested capability packages.

**Known, already-documented gaps this plan does not silently paper over**:
`docker-compose.yml`'s real gateway path is not the same as
`deploy/fullstack-compose.yml`'s placeholder Python "gateway"; the runtime
Docker image doesn't package plugin binaries. See `CLAUDE.md` and
`docs/production-api-contract.md` for the full detail — phases below note
where they intersect with these.

## Phase 1 — External memory place — **done**

**Goal**: prove memory can live somewhere other than the gateway's local
disk.

**What actually shipped** (differs slightly from the original sketch below,
kept for context): rather than an S3/SFTP backend needing real cloud
credentials this environment can't obtain or test against, `RemoteHttpStorage`
was added to `crates/hm-storage` — a second `FileStorage` implementor that
persists to another host's `/storage/{key}` endpoint (most naturally, a
second `hm-gateway` instance acting as a pure storage node) over a
hand-rolled plain-HTTP client, matching this codebase's no-framework style.
`AppState.storage`'s type had to change from the concrete `Arc<LocalFsStorage>`
to `Arc<dyn FileStorage>` (a 3-call-site change) for runtime backend
selection; `MemoryStore` was already generic over the trait and needed no
changes at all. Selected via `HM_STORAGE_BACKEND=local|remote` +
`HM_REMOTE_STORAGE_URL`/`HM_REMOTE_STORAGE_TOKEN`; fails the gateway at
startup rather than silently falling back to local disk if misconfigured.

**Verified live, not simulated**: ran two real `hm-gateway` processes — a
"storage node" (plain local storage) and a "primary" (`HM_STORAGE_BACKEND=remote`
pointed at the storage node). A `POST /memory` on the primary produced zero
files on the primary's own disk (its `HM_STORAGE_ROOT` directory was never
even created) and the real memory index, including embedding vectors,
landed on the storage node — confirmed by querying that node's own
`/storage/memory/index.json` directly. 13 new `hm-storage` unit tests
(URL parsing, HTTP response parsing, and full request/response round-trips
against a hermetic mock TCP server) plus the live two-process run above.

An S3-compatible or SFTP backend is still a reasonable future addition if a
real cloud target is available to test against, but is no longer required
to satisfy this phase's goal — the external-memory-place seam is real and
proven with the lowest-credential-risk implementation available.

<details>
<summary>Original worksteps sketch (superseded by the above)</summary>

1. Add a second `FileStorage` implementor in `crates/hm-storage` — e.g.
   `S3CompatibleStorage` (works against any S3-API object store: AWS S3,
   Cloudflare R2, MinIO self-hosted) or `SftpStorage` for a plain remote
   host. **Needs a human decision**: which external target to target first
   — pick based on what you actually have access to test against.
2. Select the backend via an env var (`HM_STORAGE_BACKEND=local|s3`, extending
   the existing `HM_STORAGE_ROOT` convention) at gateway startup — no new
   route or protocol change.
3. Verify live: run a real gateway with the new backend selected, `PUT`/`GET`/
   `DELETE` through `/storage/{key}`, confirm a real object landed in the
   external target (not just that the Rust code compiled).
4. Document the new env var in `docs/production-api-contract.md`, and the
   credential/config requirements plainly (no invented "zero-config cloud
   magic" — a real external store needs real credentials).

</details>

## Phase 2 — Cloud-portable deployment (prove "standalone", not "one host")

**Goal**: the same `hm-gateway` binary + systemd unit from Phase 0 runs
unmodified on at least two different hosting substrates, proving it's not
accidentally coupled to this dev sandbox.

**Worksteps**:
1. Reconcile the two divergent compose files noted in Phase 0's gaps: decide
   whether `deploy/fullstack-compose.yml` should be deleted, or updated to
   actually run `crates/hm-gateway` instead of the placeholder Python script
   — **needs a human decision**, since it changes what "deploy" means for
   anyone currently using that file.
2. Fix the Dockerfile packaging gap (already documented, not yet fixed):
   decide what the runtime image should install for plugin dispatch to work
   (copy `plugins/`, `config/`, a Python interpreter, and any plugin
   binaries like `hm-tool-exec`) — or explicitly scope plugins out of the
   containerized deployment path if that's the intended split.
3. Stand up `deploy/hm-gateway.service` for real on one non-sandbox host
   (a VPS, a spare machine, a cloud VM) and confirm `systemd-analyze verify`
   plus an actual `systemctl start` + real `/health` request — this
   environment has no systemd daemon, so this step has never actually run
   the unit, only verified its syntax.
4. Stand up the docker-compose path on a second, different host/provider.

**Done when**: two independently-provisioned hosts (different providers or
at least different environments) both run a working `hm-gateway` from the
same checked-in artifacts, with no host-specific patches.

## Phase 3 — Graph-enhanced memory — **done**

**Goal**: let a gateway answer structural questions ("what depends on
hm-gateway", "which plugins does hm-tool-exec back") over HTTP, using the
knowledge-graph seed already built in Phase 0, alongside `hm-memory`'s
existing text-similarity search.

**What shipped**: `MemoryStore` (`crates/hm-memory/src/lib.rs`) gained a
`graph: Option<Value>` field on its persisted state, kept structurally
separate from `records`/`index` — never blended into free-text
`remember`/`recall`. Two new methods: `ingest_graph_seed(&self, graph_json:
&[u8])` (validates the `{"nodes":[...],"edges":[...]}` shape, replaces any
previously-ingested graph rather than accumulating) and `graph(&self) ->
Option<Value>`. `hm-gateway` reads an optional `HM_MEMORY_GRAPH_SEED_PATH`
env var at startup and ingests that file if set — a missing or malformed
seed logs a warning and does not block startup, matching this codebase's
"never crash on an optional nice-to-have" convention. A new `GET
/memory/graph` route returns the ingested graph as-is, or `404` if none was
ingested. 6 new `hm-memory` unit tests (including one asserting graph
ingestion never pollutes free-text recall, and one asserting re-ingestion
replaces rather than accumulates).

**Verified live, not simulated**: generated a real seed via
`scripts/generate_knowledge_graph_seed.py` (37 nodes, 65 edges from this
actual repo), started a real `hm-gateway` process with
`HM_MEMORY_GRAPH_SEED_PATH` pointed at it, and confirmed `GET /memory/graph`
returned that exact graph over HTTP (401 without the owner bearer token, 200
with it), the graph was persisted verbatim on disk in the storage-backed
index file, and `GET /memory` stayed empty throughout — no cross-
contamination between the two data shapes.

Regenerating the seed on a schedule (rather than once at process start) is
left as a follow-up — see `docs/production-api-contract.md`'s "Graph-
enhanced memory" section for the exact route/env var contract.

## Phase 4 — Close the "AI" loop — **scaffold built, not live-verified**

**Goal**: name the actual gap plainly — nothing in this stack calls an LLM
today. `hm-agent` dispatches to fixed, deterministic plugins; there is no
chat/completion call anywhere in the codebase. Calling this an "AI platform"
before this phase would overstate what exists.

**What shipped**: `plugins/llm_chat_plugin.py`, a new subprocess plugin
following the same `echo`/`ops-tool` protocol, registered as the `llm-chat`
`task_type` in `config/plugins.json`. It targets a generic OpenAI-compatible
`/chat/completions`-shaped endpoint (the most portable choice — works
against many hosted providers and self-hosted gateways without hardcoding
one vendor; picking a specific provider/model remains the human decision
this phase always flagged). It follows this codebase's disclosure/consent
rule for anything sending data off-machine (`ghm_core/cli.py`'s
`cmd_report_diagnostics` pattern): it refuses loudly, with a machine-readable
reason, unless `HM_LLM_ENABLE=true` **and** `HM_LLM_API_URL`,
`HM_LLM_API_KEY`, and `HM_LLM_MODEL` are all explicitly set — no silent
no-op, no invented default model or endpoint — and prints exactly what it's
about to send (destination URL, model, message length, never the message
body itself) to stderr before making the call.

**Explicitly NOT done, and not claimed**: this plugin has **not** been
live-verified against a real LLM API. This environment has no LLM API
credentials and no network egress to a real completions endpoint to test
against. `tests/test_llm_chat_plugin.py` (5 tests) exercises every code path
— the two refusal cases, a successful round-trip, an upstream error status,
and an unreachable-host error — against a **hermetic local mock HTTP
server**, not a real provider. That proves the plugin's own logic is
correct; it is not the same claim as "a real chat message gets a real LLM
response," and this document will not say otherwise until that's actually
been run.

**Worksteps still open** (need a human decision on provider/model +
credentials, then this environment or a real deployment target to test
from):
1. An operator picks a real provider/model and sets
   `HM_LLM_ENABLE=true`/`HM_LLM_API_URL`/`HM_LLM_API_KEY`/`HM_LLM_MODEL` for
   real.
2. Wire the UI's existing chat-shaped panel (if any) or add a minimal one to
   `ui/` that calls `POST /tasks` with `taskType: "llm-chat"` and renders
   `plugin_result`.
3. Verify live: a real prompt round-trips through gateway → agent → plugin →
   real LLM API → response, with the outcome recorded in memory per the
   existing `Agent::dispatch` behavior from Phase 0 — no mocked responses.

**Done when**: a real chat message sent through the UI gets a real LLM
response back, and `GET /memory` shows the recorded outcome.

## Phase 5 — Multi-environment scaling — **partially done, scope disclosed**

**Goal**: prove the "platform" framing for real — more than one `hm-gateway`
instance (different hosts/regions/providers from Phase 2), each optionally
pointed at its own or a shared external memory place (Phase 1), fronted by
the UI's already-existing endpoint-rotation/failover logic
(`ui/src/endpoint-rotation.ts`), which today only *simulates* multi-endpoint
behavior against a single real instance plus fallbacks that were never live.

**What actually shipped**: `scripts/verify_multi_instance_failover.mjs` — a
live verification script that imports `ui/src/endpoint-rotation.ts`
*unmodified* (Node 22's native TypeScript-stripping support, no build step,
no reimplementation of the rotation logic) and exercises it against two real,
independently-spawned `hm-gateway` processes (distinct ports, distinct
`HM_STORAGE_ROOT` directories). It calls the real `checkEndpoint` and
`dispatchWithRotation` functions, confirms both instances are healthy, sends
a real `echo` task and confirms it lands on the priority-1 instance, then
**kills that process for real** and confirms the exact same rotation call
fails over to the priority-2 instance — a real `202` response from a real
second process, not a mocked one.

**Disclosed scope limitation**: both instances run on this same host/sandbox
(different ports and storage roots, genuinely independent OS processes with
independent state — not the same process pretending to be two endpoints),
not genuinely different hosts, regions, or cloud providers. That gap is
Phase 2's, which needs real infrastructure this environment doesn't have
access to. What *is* proven live, not simulated: the rotation algorithm
itself — unmodified production code — correctly detects a dead gateway via
real HTTP health checks and correctly redirects real task dispatches to a
surviving instance.

**Verified live** (run yourself via `node --experimental-strip-types
scripts/verify_multi_instance_failover.mjs` after `cargo build -p
hm-gateway`): output confirms `gatewayA`/`gatewayB` both `online`, a dispatch
picks `gateway-a` (priority 1, `202`), then after `gateway-a` is killed the
identical dispatch call picks `gateway-b` (`202`) with `gateway-a` correctly
recorded as `offline` in the attempt log.

**Still open** (genuinely requires Phase 2's human decisions — cloud
provider, real hosts): running this same script's *scenario* — not the
script itself, which is host-agnostic already — against two instances on
different real hosts/providers, and pointing `ui/public/platform-config.json`
at their real URLs instead of the `/api`/`/gateway` reverse-proxy placeholder
already flagged as a gap in `docs/production-api-contract.md`.

**Done when** (revised): the disclosed same-host limitation above is closed
— i.e. the same failover scenario observed against two genuinely
independent hosts/providers from a completed Phase 2.

## How to use this plan

Each phase stands alone — pick one, and it's a normal PR-sized piece of
work following the same rigor as everything else in this repo's history:
minimal scope, real verification (build/test/live-exercise), documented
gaps left open rather than papered over. Phase 4 is flagged as the largest
conceptual gap (no LLM call exists anywhere yet); Phase 1 is the smallest,
safest starting point given the trait boundary already in place. Say which
phase to start, and any human-only decisions it needs (cloud provider, LLM
provider, credentials) up front.
