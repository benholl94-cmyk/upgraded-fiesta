#!/bin/bash

# Read the JSON input from stdin
input=$(cat)

# Check if stop hook is already active (recursion prevention).
# jq ist nicht ueberall installiert; eine regex auf das boolesche Feld
# reicht, weil der Hook nur den String "true" braucht, nicht das volle JSON.
if command -v jq >/dev/null 2>&1; then
  stop_hook_active=$(printf '%s' "$input" | jq -r '.stop_hook_active // empty')
else
  if printf '%s' "$input" | grep -Eq '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
    stop_hook_active=true
  else
    stop_hook_active=
  fi
fi
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
  # signature at all, or signed with a committer email other than
  # noreply@anthropic.com (the identity CCR's signing key is registered to).
  #
  # This asks whether a signature is PRESENT, not whether it verifies. An
  # earlier version used "%G? == N" and claimed that signed-but-unverifiable
  # commits report B/U/E. That is false here: CCR signs via SSH and does not
  # configure gpg.ssh.allowedSignersFile, so git cannot even attempt
  # verification and reports N for *every* commit -- signed or not. ("git log"
  # prints "gpg.ssh.allowedSignersFile needs to be configured" when asked.)
  #
  # Collapsing "cannot determine" into "not signed" made the hook demand an
  # amend/rebase of correctly signed commits that were already pushed; the
  # remedy would have required a force-push, which is denied. Same defect
  # class as an unknown CI result being read as success -- an indeterminate
  # answer turned into a definite one, here falling to the false side.
  #
  # The raw object header answers the question that can actually be answered
  # without a key or a verification config. Only header lines are inspected
  # (sed quits at the blank line), so a commit *message* mentioning gpgsig
  # cannot pose as a signature.
  if [[ "$(git config --type=bool commit.gpgsign 2>/dev/null)" == "true" ]]; then
    unverifiable=$(
      git log --format='%H %ce' "$default_ref..HEAD" 2>/dev/null |
      while read -r sha email; do
        sig=unsigned
        if git cat-file commit "$sha" 2>/dev/null |
             sed -n '/^$/q;p' | grep -q '^gpgsig '; then
          sig=signed
        fi
        if [[ "$sig" == "unsigned" || "$email" != "noreply@anthropic.com" ]]; then
          printf '%s %s %s\n' "${sha:0:7}" "$sig" "$email"
        fi
      done
    )
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
