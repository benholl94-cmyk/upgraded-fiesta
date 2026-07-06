from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Add the scripts directory to the path so we can import the module directly.
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import build_github_app_url as script  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs) -> argparse.Namespace:
    """Return a Namespace populated with script defaults, overridden by kwargs."""
    defaults = {
        "name": "heavy-metal-control-plane",
        "description": "Self-made GitHub App for Heavy Metal repository automation.",
        "homepage_url": "https://github.com/settings/apps",
        "webhook_url": "",
        "callback_url": "",
        "setup_url": "",
        "organization": "",
        "public": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# base_url
# ---------------------------------------------------------------------------

class TestBaseUrl:
    def test_no_organization_returns_user_url(self):
        url = script.base_url("")
        assert url == "https://github.com/settings/apps/new"

    def test_organization_returns_org_url(self):
        url = script.base_url("my-org")
        assert url == "https://github.com/organizations/my-org/settings/apps/new"

    def test_empty_string_is_same_as_no_org(self):
        assert script.base_url("") == script.base_url("")

    def test_org_name_embedded_correctly(self):
        url = script.base_url("acme-corp")
        assert "/organizations/acme-corp/" in url

    def test_org_url_ends_with_apps_new(self):
        url = script.base_url("some-org")
        assert url.endswith("/settings/apps/new")

    def test_user_url_ends_with_apps_new(self):
        url = script.base_url("")
        assert url.endswith("/settings/apps/new")


# ---------------------------------------------------------------------------
# build_query – presence of required fields
# ---------------------------------------------------------------------------

class TestBuildQueryDefaults:
    def setup_method(self):
        self.args = _make_args()
        self.qs = parse_qs(script.build_query(self.args))

    def test_name_included(self):
        assert self.qs["name"] == ["heavy-metal-control-plane"]

    def test_description_included(self):
        assert "description" in self.qs

    def test_url_included(self):
        assert self.qs["url"] == ["https://github.com/settings/apps"]

    def test_public_defaults_to_false(self):
        assert self.qs["public"] == ["false"]

    def test_webhook_active_false_when_no_webhook_url(self):
        assert self.qs["webhook_active"] == ["false"]

    def test_webhook_url_absent_when_not_provided(self):
        assert "webhook_url" not in self.qs

    def test_callback_url_absent_when_not_provided(self):
        assert "callback_urls[]" not in self.qs

    def test_setup_url_absent_when_not_provided(self):
        assert "setup_url" not in self.qs


class TestBuildQueryPermissions:
    def setup_method(self):
        self.args = _make_args()
        self.qs = parse_qs(script.build_query(self.args))

    def test_checks_permission_write(self):
        assert self.qs["checks"] == ["write"]

    def test_contents_permission_read(self):
        assert self.qs["contents"] == ["read"]

    def test_metadata_permission_read(self):
        assert self.qs["metadata"] == ["read"]

    def test_pull_requests_permission_write(self):
        assert self.qs["pull_requests"] == ["write"]

    def test_all_default_permissions_present(self):
        for key in script.DEFAULT_PERMISSIONS:
            assert key in self.qs, f"Missing permission: {key}"


class TestBuildQueryEvents:
    def setup_method(self):
        self.args = _make_args()
        self.qs = parse_qs(script.build_query(self.args))

    def test_events_key_present(self):
        assert "events[]" in self.qs

    def test_all_default_events_present(self):
        events = self.qs["events[]"]
        for event in script.DEFAULT_EVENTS:
            assert event in events, f"Missing event: {event}"

    def test_event_count_matches_default(self):
        assert len(self.qs["events[]"]) == len(script.DEFAULT_EVENTS)


# ---------------------------------------------------------------------------
# build_query – webhook
# ---------------------------------------------------------------------------

class TestBuildQueryWebhook:
    def test_webhook_active_true_when_url_provided(self):
        args = _make_args(webhook_url="https://example.com/hook")
        qs = parse_qs(script.build_query(args))
        assert qs["webhook_active"] == ["true"]

    def test_webhook_url_included_when_provided(self):
        args = _make_args(webhook_url="https://example.com/hook")
        qs = parse_qs(script.build_query(args))
        assert qs["webhook_url"] == ["https://example.com/hook"]

    def test_webhook_active_false_when_empty_string(self):
        args = _make_args(webhook_url="")
        qs = parse_qs(script.build_query(args))
        assert qs["webhook_active"] == ["false"]

    def test_webhook_url_absent_when_empty(self):
        args = _make_args(webhook_url="")
        qs = parse_qs(script.build_query(args))
        assert "webhook_url" not in qs


# ---------------------------------------------------------------------------
# build_query – optional fields
# ---------------------------------------------------------------------------

class TestBuildQueryOptionalFields:
    def test_callback_url_included_when_provided(self):
        args = _make_args(callback_url="https://example.com/callback")
        qs = parse_qs(script.build_query(args))
        assert "https://example.com/callback" in qs["callback_urls[]"]

    def test_setup_url_included_when_provided(self):
        args = _make_args(setup_url="https://example.com/setup")
        qs = parse_qs(script.build_query(args))
        assert qs["setup_url"] == ["https://example.com/setup"]

    def test_public_true_when_flag_set(self):
        args = _make_args(public=True)
        qs = parse_qs(script.build_query(args))
        assert qs["public"] == ["true"]

    def test_custom_name(self):
        args = _make_args(name="my-custom-app")
        qs = parse_qs(script.build_query(args))
        assert qs["name"] == ["my-custom-app"]

    def test_all_optional_fields_together(self):
        args = _make_args(
            webhook_url="https://example.com/hook",
            callback_url="https://example.com/callback",
            setup_url="https://example.com/setup",
            public=True,
        )
        qs = parse_qs(script.build_query(args))
        assert qs["webhook_active"] == ["true"]
        assert qs["webhook_url"] == ["https://example.com/hook"]
        assert "https://example.com/callback" in qs["callback_urls[]"]
        assert qs["setup_url"] == ["https://example.com/setup"]
        assert qs["public"] == ["true"]


# ---------------------------------------------------------------------------
# build_query – output is a valid query string
# ---------------------------------------------------------------------------

class TestBuildQueryFormat:
    def test_returns_string(self):
        args = _make_args()
        result = script.build_query(args)
        assert isinstance(result, str)

    def test_no_leading_question_mark(self):
        args = _make_args()
        result = script.build_query(args)
        assert not result.startswith("?")

    def test_parseable_as_query_string(self):
        args = _make_args()
        result = script.build_query(args)
        parsed = parse_qs(result)
        assert len(parsed) > 0

    def test_special_chars_in_description_are_encoded(self):
        args = _make_args(description="foo & bar <baz>")
        result = script.build_query(args)
        # The raw special characters must not appear literally in the query
        # string -- only their percent-encoded form. (Checking the whole
        # query string for "&" would be wrong: every other param is joined
        # with a literal "&" separator, so that character is expected to
        # appear -- what matters is that it's absent from the *encoded
        # description value itself*.)
        description_value = parse_qs(result)["description"][0]
        assert description_value == "foo & bar <baz>"
        encoded_segment = [pair for pair in result.split("&") if pair.startswith("description=")][0]
        assert "&" not in encoded_segment
        assert "<" not in encoded_segment
        assert ">" not in encoded_segment


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_default_events_is_list(self):
        assert isinstance(script.DEFAULT_EVENTS, list)

    def test_default_events_not_empty(self):
        assert len(script.DEFAULT_EVENTS) > 0

    def test_default_events_contains_push(self):
        assert "push" in script.DEFAULT_EVENTS

    def test_default_events_contains_pull_request(self):
        assert "pull_request" in script.DEFAULT_EVENTS

    def test_default_events_contains_check_run(self):
        assert "check_run" in script.DEFAULT_EVENTS

    def test_default_events_contains_check_suite(self):
        assert "check_suite" in script.DEFAULT_EVENTS

    def test_default_events_contains_workflow_run(self):
        assert "workflow_run" in script.DEFAULT_EVENTS

    def test_default_permissions_is_dict(self):
        assert isinstance(script.DEFAULT_PERMISSIONS, dict)

    def test_default_permissions_not_empty(self):
        assert len(script.DEFAULT_PERMISSIONS) > 0

    def test_default_permissions_checks_write(self):
        assert script.DEFAULT_PERMISSIONS["checks"] == "write"

    def test_default_permissions_contents_read(self):
        assert script.DEFAULT_PERMISSIONS["contents"] == "read"

    def test_default_permissions_metadata_read(self):
        assert script.DEFAULT_PERMISSIONS["metadata"] == "read"

    def test_default_permissions_pull_requests_write(self):
        assert script.DEFAULT_PERMISSIONS["pull_requests"] == "write"


# ---------------------------------------------------------------------------
# main() – subprocess integration
# ---------------------------------------------------------------------------

_SCRIPT_PATH = str(_SCRIPTS_DIR / "build_github_app_url.py")


class TestMainSubprocess:
    def _run(self, *extra_args: str) -> str:
        proc = subprocess.run(
            [sys.executable, _SCRIPT_PATH, *extra_args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return proc.stdout.strip()

    def test_default_output_starts_with_user_base_url(self):
        url = self._run()
        assert url.startswith("https://github.com/settings/apps/new?")

    def test_org_flag_changes_base_url(self):
        url = self._run("--organization", "acme")
        assert url.startswith("https://github.com/organizations/acme/settings/apps/new?")

    def test_output_is_single_line(self):
        url = self._run()
        assert "\n" not in url

    def test_output_contains_name_param(self):
        url = self._run("--name", "test-app")
        parsed = parse_qs(urlparse(url).query)
        assert parsed["name"] == ["test-app"]

    def test_output_contains_webhook_url_when_provided(self):
        url = self._run("--webhook-url", "https://example.com/hook")
        parsed = parse_qs(urlparse(url).query)
        assert parsed["webhook_url"] == ["https://example.com/hook"]
        assert parsed["webhook_active"] == ["true"]

    def test_public_flag_sets_public_true(self):
        url = self._run("--public")
        parsed = parse_qs(urlparse(url).query)
        assert parsed["public"] == ["true"]

    def test_default_public_is_false(self):
        url = self._run()
        parsed = parse_qs(urlparse(url).query)
        assert parsed["public"] == ["false"]

    def test_output_url_is_parseable(self):
        url = self._run()
        result = urlparse(url)
        assert result.scheme == "https"
        assert result.netloc == "github.com"

    def test_all_default_events_in_output(self):
        url = self._run()
        parsed = parse_qs(urlparse(url).query)
        for event in script.DEFAULT_EVENTS:
            assert event in parsed["events[]"], f"Missing event in output: {event}"

    def test_all_default_permissions_in_output(self):
        url = self._run()
        parsed = parse_qs(urlparse(url).query)
        for perm, level in script.DEFAULT_PERMISSIONS.items():
            assert parsed[perm] == [level], f"Wrong level for permission: {perm}"
