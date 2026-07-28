# Stale-Branch-Cleanup Report — 2026-07-29

## Context

After merging PR #101 (auto-rollback SOH fix), the repo accumulated 8 stale
local branches from parallel-session leftovers. Each was already superseded
by main via other PRs, or contained only workflow-file changes blocked by
the Codespace-OAuth workflow-scope.

## Audit Result

For each stale branch, every unique commit was checked against `origin/main`
by commit message:

| Branch                              | Unique commits | Status                                  |
| ----------------------------------- | -------------- | --------------------------------------- |
| `docs/dev-server-fix`               | 6              | All superseded by main (other PRs)      |
| `docs/workflow-fix-waiting`         | 5              | All superseded by main (other PRs)      |
| `fix/100-percent-green`             | 1              | Superseded by #93                       |
| `fix/ci-workflow-yaml`              | 0              | Already merged via fast-forward         |
| `fix/continuity-ledger-only`        | 2              | Continuity-only, superseded by #97      |
| `fix/selbsterhalt-adds-workflow-repair` | 1          | Superseded by #100                      |
| `fix/workflows-ci-and-rollback`     | 3              | Workflow-files only (OAuth-blocked)    |
| `munin/continuity-ledger`           | 1              | Superseded by #97                       |

## Action Taken

Deleted all 8 stale LOCAL branches. Remote branches left untouched
(no force-push, no remote-branch-delete — outside routine mandate).

## OAuth-Workflow-Scope Blocker (recap)

`x-oauth-scopes: codespace, repo, user:email` — no `workflow` scope.
Workflow files (`.github/workflows/*.yml`) cannot be pushed from the
Codespace token. Master must land them via GitHub Web UI or a PAT-bearing
workflow. Tracked in Issue #94.

## Verification

- `git branch` shows only `main` and `chore/cleanup-stale-branches` locally.
- No remote refs were modified.
- No commits were rewritten (no force-push).
