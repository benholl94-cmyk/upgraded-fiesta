---
name: pr-bot-triage
description: Use when subscribed to or babysitting a GitHub PR and an automated review-bot comment (CodeRabbit, or similar) arrives that isn't obviously a real finding -- rate-limit warnings ("Review limit reached"), repeated walkthrough re-postings, bot-side infrastructure errors, or resolution/learning acknowledgments. Also use proactively before replying to any incoming <github-webhook-activity> bot comment, to decide in one step whether it needs investigation or can be skipped silently.
license: Original content, no external code included.
---

# PR bot comment triage

## Why this exists

Babysitting a PR means every comment from a review bot arrives with the same
urgency-coded framing (⚠️, 🟠 Major, etc.) whether or not it's actually new
information. In practice, most incoming comments on a long-lived PR are noise:
the bot re-hit its own rate limit, re-posted the same walkthrough after a
disposable log-only commit, or is just confirming a fix already landed. Only
some are a genuinely new finding that needs triage. Reading each one in full
every time wastes turns and risks either missing the one real finding buried
in repeated noise, or over-reacting to noise as if it were signal.

## How to use it

For each incoming bot comment, run the classifier before deciding how to respond:

```sh
python3 .claude/skills/pr-bot-triage/scripts/classify_bot_comment.py comment.txt
```

Or call it directly in Python:

```python
from classify_bot_comment import classify_bot_comment
result = classify_bot_comment(comment_body)
# result.category, result.should_act, result.reason
```

## Categories and what to do for each

| category | `should_act` | What it means | What to do |
|---|---|---|---|
| `rate_limited` | `False` | Bot hit its own per-developer review quota; no review ran | Skip silently. Don't retry manually -- it retries itself on the next push or after the stated window. |
| `bot_infra_error` | `False` | The bot's own side-feature failed (timed-out request, failed auto-PR generation) | Skip silently. This is the bot's infrastructure, not your code. |
| `resolution_ack` | `False` | Bot confirming a fix you already pushed landed | Skip silently -- purely confirmatory. |
| `learning_ack` | `False` | Bot recorded your explanation as a review learning | Skip silently -- no further action implied. |
| `walkthrough_summary` | `False` | A high-level PR description with no actionable-finding count attached | Skip silently unless it's the very first one on the PR (worth a skim for surprises). |
| `clean_review` | `False` | A real review ran and reported zero actionable comments | Nothing to fix; safe to note the PR is currently clean. |
| `actionable_review` | `True` | A real review ran and reported one or more actionable comments | Read every finding individually: verify each against current code, fix what's genuinely valid, reply with reasoning for anything you deliberately skip (see below). |
| `unknown` | `True` | Doesn't match any known noise pattern | Read it in full -- the classifier's safety property is to default to "investigate" for anything unrecognized, never to "ignore." |

## Handling `actionable_review` findings

This classifier only tells you *whether* a comment needs attention, not what
to do with the findings inside one that does. For those, verify each finding
against the current code before changing anything (a finding can be stale --
already fixed by a later commit, or based on a misread of the diff), then:

- **Fix it** if it's a small, clearly-scoped, safe change (matches this
  repo's existing "quick win" pattern) -- verify with the same rigor as any
  other change (build/test/lint, live-exercise if it has runtime behavior).
- **Reply explaining why not**, briefly, if it's a deliberate scope decision
  (e.g. "this is a pre-existing condition, not introduced here, and the real
  fix is a separate packaging decision") -- bots (CodeRabbit specifically)
  can record that reasoning as a "learning" for future reviews, so a good
  explanation compounds.
- **Skip silently** only for things that are genuinely non-actionable noise
  even within an actionable-review comment (rare, but e.g. a nitpick already
  fixed by a commit made after the review ran).

## What this deliberately does not do

This is a text classifier, not a GitHub API client -- it doesn't fetch
comments, post replies, or know anything about a specific PR. Wire it into
whatever already reads the comment body (a webhook payload, `list_issue_comments`,
etc.); don't build a second, redundant fetch path around it.
