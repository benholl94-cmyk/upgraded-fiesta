# Issue #94 — Action Plan

**Issue**: [ci: workflow-YAML-Fixes für 100%-Green — OAuth scope blockiert Codespace-Push](#94)

## Root cause

Codespace token (and the default `GITHUB_TOKEN` in workflows) does **not** have
the `workflow` scope. Per [GitHub community discussion #35410][gh-35410]:

> Adding `actions: write` or `workflows: write` to the permissions block does
> **not** allow pushing workflow files when using the default `GITHUB_TOKEN`.
> The exact solution is to **use a Personal Access Token (PAT)** with `workflow`
> scope.

This is a security feature: GitHub blocks the default token from triggering
workflow runs to prevent infinite loops, and this restriction **cannot** be
overridden by adding permissions.

[gh-35410]: https://github.com/orgs/community/discussions/35410

## Files to land

| File | Status | Source |
| ---- | ------ | ------ |
| `.github/workflows/auto-rollback.yml` | NEW (1967 bytes) | `docs/maintenance/issue-94/auto-rollback.yml` |
| `.github/workflows/ci.yml` | MODIFY (+/- 7 lines) | `docs/maintenance/issue-94/ci.yml.patch` |

Both files are also preserved in commit `9258c84` on branch `fix/selbsterhalt-adds-workflow-repair`.

## Master actions (5 minutes)

### Option A: GitHub Web UI (recommended — fastest)

1. Open <https://github.com/benholl94-cmyk/upgraded-fiesta/new/main?filename=.github/workflows/auto-rollback.yml>
2. Paste contents from `docs/maintenance/issue-94/auto-rollback.yml`
3. Click "Commit changes" → "Commit directly to the main branch"
4. Open <https://github.com/benholl94-cmyk/upgraded-fiesta/edit/main/.github/workflows/ci.yml>
5. Apply the patch from `docs/maintenance/issue-94/ci.yml.patch` (or copy the file from commit `9258c84` via "Edit file" → paste)
6. Commit

### Option B: PAT in repo secret + selbsterhalt auto-land

1. Create a fine-grained PAT at <https://github.com/settings/personal-access-tokens/new>
   - Repository access: "Only select repositories" → `benholl94-cmyk/upgraded-fiesta`
   - Permissions: "Contents: Read and write", "Workflows: Read and write"
2. Add the PAT as repo secret `WORKFLOW_TOKEN` at <https://github.com/benholl94-cmyk/upgraded-fiesta/settings/secrets/actions/new>
3. Patch `selbsterhalt.yml` (see `docs/maintenance/issue-94/selbsterhalt-patch.md`)
4. Run selbsterhalt workflow: `gh workflow run selbsterhalt.yml`
5. The next selbsterhalt run will land the workflow files automatically.

### Option C: Local clone with PAT

```bash
git clone https://github.com/benholl94-cmyk/upgraded-fiesta.git
cd upgraded-fiesta
git remote set-url origin https://x-access-token:$YOUR_PAT@github.com/benholl94-cmyk/upgraded-fiesta.git
cp docs/maintenance/issue-94/auto-rollback.yml .github/workflows/auto-rollback.yml
git apply docs/maintenance/issue-94/ci.yml.patch
git commit -am "fix(workflows): Issue #94 — ci.yml + auto-rollback.yml"
git push origin main
```

## What Claude CAN do (already done)

- ✅ Diagnosed the failure via selbsterhalt run logs (`refusing to allow a GitHub App to create or update workflow`).
- ✅ Surveyed external community discussions for the canonical solution.
- ✅ Staged the workflow files in this directory for Master to land.
- ✅ Verified the files exist in branch history (commit `9258c84`).
- ❌ Cannot push workflow files directly — requires Master action with PAT or Web UI.

## Verification after landing

```bash
python3 -m pytest tests/test_wave1_smoke.py -q
# Expected: all 3 tests pass (auto-rollback, ci.yml generate-lockfile, hugin-sync warning)
```

Then full pytest run:

```bash
python3 -m pytest tests/ -q
# Expected: 963 passed, 6 skipped (was 955 passed, 6 skipped, 3 failed)
```

## References

- Stack Overflow: <https://stackoverflow.com/questions/64059610/how-to-resolve-refusing-to-allow-an-oauth-app-to-create-or-update-workflow-on>
- GitHub community: <https://github.com/orgs/community/discussions/35410>
- GitHub community: <https://github.com/orgs/community/discussions/27072>
- Graphite guide: <https://graphite.com/guides/github-actions-permissions>
