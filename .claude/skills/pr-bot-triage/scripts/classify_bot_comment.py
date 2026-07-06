#!/usr/bin/env python3
"""Classify a GitHub PR bot comment so an agent (or human) knows whether it
needs action, without re-reading the same boilerplate every time.

Built from real, repeatedly-observed noise patterns: CodeRabbit's per-developer
rate limit ("Review limit reached"), its own infrastructure failures (request
timeouts, failed unit-test-generation attempts), duplicate walkthrough
re-postings after every push, and resolution acknowledgments -- all of which
look alarming on first read but carry zero new information after the first
time you've seen the shape.

This is a classifier over comment *text*, not a GitHub API client -- feed it
a comment body (from a webhook payload, `list_issue_comments`, etc.) and it
tells you what kind of noise (or signal) it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Classification:
    category: str
    should_act: bool
    reason: str


# Order matters: rate-limit notices can carry a stale, previously-successful
# walkthrough in the same comment body (CodeRabbit re-posts the last good
# summary underneath the new warning), so "no new review happened" must be
# checked before anything about walkthroughs/findings.
_RATE_LIMIT_MARKERS = (
    "review limit reached",
    "you've reached your pr review limit",
    "reached your pr review limit",
)

_BOT_INFRA_ERROR_MARKERS = (
    "request timed out after",
    "error creating unit test pr",
    "error creating pr",
)

_RESOLUTION_ACK_MARKERS = (
    "✅ addressed in commit",
)

_LEARNING_ACK_MARKERS = (
    "learnings added",
    "learning added",
)

_ACTIONABLE_COMMENT_COUNT = re.compile(r"\*\*actionable comments posted:\s*(\d+)\*\*", re.IGNORECASE)

_WALKTHROUGH_MARKERS = (
    "📝 walkthrough",
    "estimated code review effort",
)


def classify_bot_comment(body: str) -> Classification:
    """Classifies a single PR comment/review body. Case-insensitive; matches
    on the substrings CodeRabbit (and similar review bots) actually emit,
    not on author name -- callers should already know the comment is from a
    bot before calling this (e.g. author login ends in "[bot]")."""
    text = body.lower()

    if any(marker in text for marker in _RATE_LIMIT_MARKERS):
        return Classification(
            category="rate_limited",
            should_act=False,
            reason="Bot hit its own per-developer review-rate limit; no new review ran. "
                   "Wait for the retry window or the next push -- nothing to fix here.",
        )

    if any(marker in text for marker in _BOT_INFRA_ERROR_MARKERS):
        return Classification(
            category="bot_infra_error",
            should_act=False,
            reason="The bot's own side-feature (e.g. auto-generated unit tests, a timed-out "
                   "request) failed. This is about the bot's infrastructure, not your code.",
        )

    if any(marker in text for marker in _RESOLUTION_ACK_MARKERS):
        return Classification(
            category="resolution_ack",
            should_act=False,
            reason="The bot is confirming a previously-flagged finding was addressed. "
                   "Already handled; this comment is just the bot catching up.",
        )

    if any(marker in text for marker in _LEARNING_ACK_MARKERS):
        return Classification(
            category="learning_ack",
            should_act=False,
            reason="The bot recorded your explanation as a learning for future reviews. "
                   "No further action implied.",
        )

    match = _ACTIONABLE_COMMENT_COUNT.search(text)
    if match:
        count = int(match.group(1))
        if count > 0:
            return Classification(
                category="actionable_review",
                should_act=True,
                reason=f"Bot reports {count} actionable comment(s) -- a real review ran and "
                       f"found something. Triage each finding individually.",
            )
        return Classification(
            category="clean_review",
            should_act=False,
            reason="A real review ran and found zero actionable comments.",
        )

    if any(marker in text for marker in _WALKTHROUGH_MARKERS):
        return Classification(
            category="walkthrough_summary",
            should_act=False,
            reason="A high-level PR summary/walkthrough with no actionable-comment count attached "
                   "-- informational only. If it repeats verbatim after a push with no new "
                   "findings section, it's the bot re-summarizing, not new signal.",
        )

    return Classification(
        category="unknown",
        should_act=True,
        reason="Doesn't match any known noise pattern -- err on the side of reading it "
               "in full rather than assuming it's safe to skip.",
    )


def main() -> int:
    import json
    import sys

    if len(sys.argv) != 2:
        print("usage: classify_bot_comment.py <path-to-comment-body.txt>", file=sys.stderr)
        return 2

    with open(sys.argv[1], encoding="utf-8") as handle:
        body = handle.read()

    result = classify_bot_comment(body)
    print(json.dumps({
        "category": result.category,
        "should_act": result.should_act,
        "reason": result.reason,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
