from __future__ import annotations

import importlib.util
import pathlib
import sys

_SCRIPT_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "pr-bot-triage"
    / "scripts"
    / "classify_bot_comment.py"
)
_spec = importlib.util.spec_from_file_location("classify_bot_comment", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module  # dataclasses needs the module registered to resolve types
_spec.loader.exec_module(_module)
classify_bot_comment = _module.classify_bot_comment


# Real (trimmed) comment bodies observed on benholl94-cmyk/upgraded-fiesta#50,
# not synthetic guesses -- these are the actual recurring shapes.

RATE_LIMIT_COMMENT = """
<!-- This is an auto-generated comment: rate limited by coderabbit.ai -->

> [!WARNING]
> ## Review limit reached
>
> `@benholl94-cmyk`, you've reached your PR review limit, so we couldn't start this review.
>
> **Next review available in:** **10 minutes**
"""

RATE_LIMIT_WITH_STALE_WALKTHROUGH = """
<!-- This is an auto-generated comment: rate limited by coderabbit.ai -->

> [!WARNING]
> ## Review limit reached
>
> `@benholl94-cmyk`, you've reached your PR review limit, so we couldn't start this review.

<!-- walkthrough_start -->
## Walkthrough

This PR adds an `hm-agent` runtime that dispatches tasks through plugins...

**Estimated code review effort:** 4 (Complex) | ~60 minutes
<!-- walkthrough_end -->
"""

TIMEOUT_ERROR_COMMENT = """
<!-- This is an auto-generated reply by CodeRabbit -->
Request timed out after 900000ms (requestId=0fa7ca04-05ed-4523-9e5c-c1cf9af4227b)
"""

UNIT_TEST_GENERATION_FAILED = """
<details>
<summary>🧪 Generate unit tests (beta)</summary>

❌ Error creating Unit Test PR.
- [ ] Create PR with unit tests
- [ ] Commit unit tests in branch `claude/env-points-anchors-localization-flyoos`

</details>
"""

ACTIONABLE_REVIEW_COMMENT = """
**Actionable comments posted: 3**

<details>
<summary>🧹 Nitpick comments (4)</summary>
...
</details>
"""

CLEAN_REVIEW_COMMENT = """
**Actionable comments posted: 0**

Nothing further to flag in this diff.
"""

WALKTHROUGH_ONLY_COMMENT = """
<!-- walkthrough_start -->
<details>
<summary>📝 Walkthrough</summary>

## Walkthrough

This PR adds an `hm-agent` runtime that dispatches tasks through plugins and
records outcomes in memory, wires it into `hm-gateway` with graceful shutdown
handling.

**Estimated code review effort:** 4 (Complex) | ~60 minutes
</details>
<!-- walkthrough_end -->
"""

RESOLUTION_ACK_COMMENT = """
**Handle accept() failures without aborting the gateway** `accepted?` returns
from `main` on any `TcpListener::accept()` error...

<!-- cr-comment:v1:29df223d058e68dc5dde56ac -->

_Source: Coding guidelines_

<!-- This is an auto-generated comment by CodeRabbit -->

✅ Addressed in commit 75f70ad
"""

LEARNING_ACK_COMMENT = """
`@benholl94-cmyk`, that's a fair point — good catch that this was already a
latent issue with the `echo` plugin, not something introduced here.

<details>
<summary>✏️ Learnings added</summary>

```
Learnt from: benholl94-cmyk
Repo: benholl94-cmyk/upgraded-fiesta PR: 50
```
</details>
"""

UNKNOWN_COMMENT = """
Hey, can someone take a look at whether this actually needs a database
migration before merging?
"""


def test_rate_limit_notice_is_not_actionable():
    result = classify_bot_comment(RATE_LIMIT_COMMENT)
    assert result.category == "rate_limited"
    assert result.should_act is False


def test_rate_limit_with_stale_walkthrough_is_still_rate_limited():
    # The rate-limit signal must win even when a full walkthrough is
    # re-posted in the same comment -- that walkthrough is stale, not new.
    result = classify_bot_comment(RATE_LIMIT_WITH_STALE_WALKTHROUGH)
    assert result.category == "rate_limited"
    assert result.should_act is False


def test_request_timeout_is_bot_infra_error():
    result = classify_bot_comment(TIMEOUT_ERROR_COMMENT)
    assert result.category == "bot_infra_error"
    assert result.should_act is False


def test_unit_test_generation_failure_is_bot_infra_error():
    result = classify_bot_comment(UNIT_TEST_GENERATION_FAILED)
    assert result.category == "bot_infra_error"
    assert result.should_act is False


def test_actionable_review_with_findings_should_act():
    result = classify_bot_comment(ACTIONABLE_REVIEW_COMMENT)
    assert result.category == "actionable_review"
    assert result.should_act is True
    assert "3" in result.reason


def test_clean_review_with_zero_findings_is_not_actionable():
    result = classify_bot_comment(CLEAN_REVIEW_COMMENT)
    assert result.category == "clean_review"
    assert result.should_act is False


def test_walkthrough_only_comment_is_informational():
    result = classify_bot_comment(WALKTHROUGH_ONLY_COMMENT)
    assert result.category == "walkthrough_summary"
    assert result.should_act is False


def test_resolution_ack_is_not_actionable():
    result = classify_bot_comment(RESOLUTION_ACK_COMMENT)
    assert result.category == "resolution_ack"
    assert result.should_act is False


def test_learning_ack_is_not_actionable():
    result = classify_bot_comment(LEARNING_ACK_COMMENT)
    assert result.category == "learning_ack"
    assert result.should_act is False


def test_unrecognized_comment_defaults_to_should_act():
    # Safety property: anything that doesn't match a known noise pattern
    # must default to "read it", never to "safe to ignore".
    result = classify_bot_comment(UNKNOWN_COMMENT)
    assert result.category == "unknown"
    assert result.should_act is True


def test_classification_is_case_insensitive():
    result = classify_bot_comment(RATE_LIMIT_COMMENT.upper())
    assert result.category == "rate_limited"
