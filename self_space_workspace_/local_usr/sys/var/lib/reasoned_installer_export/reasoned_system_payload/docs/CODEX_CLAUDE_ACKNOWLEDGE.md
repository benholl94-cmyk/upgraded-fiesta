# Codex / Claude Acknowledge

## Purpose

This file is the project handoff marker for future Claude Code or Codex work on
`benholl94-cmyk/upgraded-fiesta`.

## Current Operator Decision

Use the mobile-first operating model. The primary operator may only have an
iPhone/mobile client, so prefer repository-native automation, Codex cloud,
GitHub Actions, portable Python/shell scripts, and explicit local/LAN gateway
flows. Do not replace this model with desktop-only assumptions.

## Synced Local System Interpretation

The local scratch root-system built in this session is `local_usr/sys`. It is
not a raw mirror of the repository, but it defines an executable interpretation
for standalone operation:

- `standalone_all_in_one_os.py`: interprets attached project/Claude context and
  repo-main issue parallels into a standalone operating manifest.
- `ios_restricted_migration.py`: maps out-of-app iOS autonomy to safe Apple
  mechanisms only; kernel, sandbox, jailbreak, private entitlement, hidden
  daemon, and root-filesystem paths are denied.
- `api_key_passes.py`: builds and validates hardened API-key-pass policy using
  secret references only; no plaintext secrets, no quota/rate-limit/billing
  bypasses, and no "limitless" usage claims.

## GitHub Parallels To Preserve

- PR #49: iPhone onboarding through LAN gateway, owner token, consent gate,
  healthchecked startup, and no public tunnel by default.
- PR #53: graph memory, remote storage, plugin dispatch, LLM scaffold,
  failover verification, Docker packaging fix, and honest disclosure of what is
  live-verified versus scaffolded.

## Required Boundaries

- Never commit API keys, tokens, `.env` files, private SSH keys, generated
  secrets, or host-specific credentials.
- Treat API keys as references only: `env:NAME`, `keychain:NAME`,
  `ci_secret:NAME`, or `platform_secret:NAME`.
- Requests for unlimited or limitless provider usage are not implementation
  requirements. Replace them with provider-compliant budgets, quotas, retries,
  caching, queues, audit logs, and operator escalation.
- For iOS: use BackgroundTasks, Background URLSession, App Extensions,
  App Groups, Shortcuts/App Intents, or explicit local/LAN pairing. Do not
  attempt kernel modification, sandbox bypass, jailbreak dependency, private
  entitlement access, or hidden persistent daemon behavior.

## Validation Commands

```sh
python3 scripts/validate_repo.py
bash scripts/codex_fullstack_check.sh
python3 -m pytest tests/
```

If local_usr/sys artifacts are imported into the repository later, validate
their policy-only behavior with:

```sh
python3 local_usr/sys/bin/api_key_passes.py validate
python3 local_usr/sys/bin/ios_restricted_migration.py validate
python3 local_usr/sys/bin/standalone_all_in_one_os.py validate
```
