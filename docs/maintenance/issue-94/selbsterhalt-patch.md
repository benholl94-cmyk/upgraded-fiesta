# selbsterhalt.yml — PAT Fallback Patch

If Master creates a PAT with `workflow` scope and stores it as repo secret
`WORKFLOW_TOKEN`, this patch makes selbsterhalt auto-land workflow-file
fixes on its next run.

## The patch

Replace this block in `.github/workflows/selbsterhalt.yml`:

```yaml
      - name: Reparaturen zurueckschreiben
        run: |
          set -euo pipefail
          git config user.name "Claude"
          git config user.email "noreply@anthropic.com"
          if git diff --quiet && git diff --cached --quiet; then
            echo "nichts repariert — kein Commit"
            exit 0
          fi
          git add -A
          GIT_AUTHOR_NAME="benholl94-cmyk" \
          GIT_AUTHOR_EMAIL="274793931+benholl94-cmyk@users.noreply.github.com" \
            git commit -m "chore(selbsterhalt): mechanische Reparaturen [skip ci]"
          git push
```

With this block:

```yaml
      - name: Reparaturen zurueckschreiben
        env:
          # WORKFLOW_TOKEN ist ein PAT mit workflow-Scope.
          # Faellt auf GITHUB_TOKEN zurueck, wenn WORKFLOW_TOKEN nicht gesetzt ist
          # oder wenn keine Workflow-Files geaendert wurden (Default-Verhalten).
          WORKFLOW_TOKEN: ${{ secrets.WORKFLOW_TOKEN }}
        run: |
          set -euo pipefail
          git config user.name "Claude"
          git config user.email "noreply@anthropic.com"
          if git diff --quiet && git diff --cached --quiet; then
            echo "nichts repariert — kein Commit"
            exit 0
          fi

          # Pruefe, ob der Diff Workflow-Files enthaelt (.github/workflows/*.yml)
          WORKFLOW_FILES_CHANGED=$(git diff --cached --name-only | grep -E '^\.github/workflows/.*\.ya?ml$' || true)
          if [ -n "$WORKFLOW_FILES_CHANGED" ] && [ -z "$WORKFLOW_TOKEN" ]; then
            echo "::error::Workflow-Files geaendert, aber WORKFLOW_TOKEN-Secret fehlt."
            echo "::error::Bitte PAT mit workflow-Scope als WORKFLOW_TOKEN hinterlegen."
            echo "::error::Siehe docs/maintenance/issue-94/ACTION-PLAN.md"
            exit 1
          fi

          # Wenn Workflow-Files geaendert wurden UND ein PAT vorhanden ist,
          # den Remote-URL auf PAT-basierte Auth umstellen.
          if [ -n "$WORKFLOW_FILES_CHANGED" ] && [ -n "$WORKFLOW_TOKEN" ]; then
            git remote set-url origin "https://x-access-token:${WORKFLOW_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
            echo "Verwende PAT fuer Push (workflow-Files geaendert)"
          fi

          git add -A
          GIT_AUTHOR_NAME="benholl94-cmyk" \
          GIT_AUTHOR_EMAIL="274793931+benholl94-cmyk@users.noreply.github.com" \
            git commit -m "chore(selbsterhalt): mechanische Reparaturen [skip ci]"
          git push
```

## Why this works

1. **Detection**: `git diff --cached --name-only | grep .github/workflows/` detects
   whether the push would include workflow files.
2. **Conditional PAT**: Only if workflow files changed AND `WORKFLOW_TOKEN` is
   set, the remote URL is rewritten to use the PAT.
3. **Fail-loud**: If workflow files changed but no PAT, the workflow fails with
   a clear error message instead of silently rejecting.
4. **No regression**: For non-workflow pushes (the common case), behavior is
   unchanged — `GITHUB_TOKEN` works fine.

## How to apply

```bash
# Option A: Manual edit
# Open .github/workflows/selbsterhalt.yml and replace the block above.

# Option B: After creating WORKFLOW_TOKEN secret, this can land via:
# 1. Edit selbsterhalt.yml locally with the change above
# 2. Commit and push via PAT (using Option C from ACTION-PLAN.md)
```

Or just use the GitHub Web UI: open the file in edit mode, paste the new
block, commit.
