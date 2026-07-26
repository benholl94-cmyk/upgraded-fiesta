#!/bin/bash

# Read the JSON input from stdin
input=$(cat)

# Check if stop hook is already active (recursion prevention)
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active')
if [[ "$stop_hook_active" = "true" ]]; then
  exit 0
fi

# Check if we're in a git repository - bail if not
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  exit 0
fi

# Bail if there's no remote to push to. Every error path below asks the user
# to "push to the remote branch" — meaningless without a remote, and
# unsatisfiable if signing also requires a source. This case arises when CCR
# was launched against a local repo with no github remote (sources=[]) and
# the container's cwd has a leftover .git from a cached resume.
if [[ -z "$(git remote)" ]]; then
  exit 0
fi

# Check for uncommitted changes (both staged and unstaged)
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "There are uncommitted changes in the repository. Please commit and push these changes to the remote branch." >&2
  exit 2
fi

# Check for untracked files that might be important
untracked_files=$(git ls-files --others --exclude-standard)
if [[ -n "$untracked_files" ]]; then
  echo "There are untracked files in the repository. Please commit and push these changes to the remote branch." >&2
  exit 2
fi

current_branch=$(git branch --show-current)
if [[ -n "$current_branch" ]]; then
  if git rev-parse "origin/$current_branch" >/dev/null 2>&1; then
    upstream="origin/$current_branch"
  else
    upstream="origin/HEAD"
  fi

  # The signature check runs against the DEFAULT branch, not the remote
  # tracking branch. Reason: after a PR merges and the local branch is reset
  # onto main, "origin/<branch>" still points at the pre-merge tip. The range
  # "origin/<branch>..HEAD" then contains main's own history — the merge
  # commit and any CI bot commits — and the hook demands a rebase of commits
  # that belong to other authors and are already on the default branch.
  # Rewriting those would orphan the merge and force-push over main.
  # Anything already on the default branch is, by definition, not local work.
  if default_ref=$(git symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null); then
    :
  elif git rev-parse --verify -q origin/main >/dev/null 2>&1; then
    default_ref="origin/main"
  elif git rev-parse --verify -q origin/master >/dev/null 2>&1; then
    default_ref="origin/master"
  else
    default_ref="$upstream"
  fi

  # Check for local commits that GitHub will show as "Unverified": either no
  # signature at all (%G? == N), or signed with a committer email other than
  # noreply@anthropic.com (the identity CCR's signing key is registered to).
  # Only run when commit signing is configured. Note: %G? is N for unsigned
  # commits; signed-but-locally-unverifiable commits report B/U/E, so this is
  # a reliable presence check even though CCR doesn't configure local verification.
  if [[ "$(git config --type=bool commit.gpgsign 2>/dev/null)" == "true" ]]; then
    unverifiable=$(git log --format='%h %G? %ce' "$default_ref..HEAD" 2>/dev/null | awk '$2 == "N" || $3 != "noreply@anthropic.com"')
    if [[ -n "$unverifiable" ]]; then
      echo "There are commit(s) on branch '$current_branch' that GitHub will show as Unverified (missing signature, or committer email is not noreply@anthropic.com):" >&2
      echo "$unverifiable" >&2
      echo "Please run 'git config user.email noreply@anthropic.com && git config user.name Claude', then 'git commit --amend --no-edit --reset-author' for the tip commit, or 'git rebase --exec \"git commit --amend --no-edit --reset-author\" $default_ref' for earlier commits, then push." >&2
      exit 2
    fi
  fi

  # Same stale-ref trap as above: "$upstream..HEAD" counts commits that are
  # already on origin/main but not on the pre-merge branch ref, so a merged
  # branch reset onto main reports work to push that does not exist.
  # A commit reachable from no remote ref at all is the only kind that is
  # genuinely unpushed.
  unpushed=$(git rev-list HEAD --not --remotes --count 2>/dev/null) || unpushed=0
  if [[ "$unpushed" -gt 0 ]]; then
    if [[ "$upstream" == "origin/$current_branch" ]]; then
      echo "There are $unpushed unpushed commit(s) on branch '$current_branch'. Please push these changes to the remote repository." >&2
    else
      echo "Branch '$current_branch' has $unpushed unpushed commit(s) and no remote branch. Please push these changes to the remote repository." >&2
    fi
    exit 2
  fi
fi

exit 0
