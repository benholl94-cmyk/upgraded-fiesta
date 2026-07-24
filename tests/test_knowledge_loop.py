"""Tests für scripts/knowledge_loop.py — Feeds, TextExtractor, Plugin-Protokoll."""
from __future__ import annotations

import io
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import knowledge_loop  # type: ignore


class TestLoadFeeds(unittest.TestCase):
    def test_returns_list(self):
        feeds = knowledge_loop._load_feeds()
        self.assertIsInstance(feeds, list)

    def test_enabled_feeds_have_required_keys(self):
        feeds = knowledge_loop._load_feeds()
        for f in feeds:
            self.assertIn("name", f)
            self.assertIn("url", f)
            self.assertIn("enabled", f)

    def test_at_least_one_enabled(self):
        feeds = knowledge_loop._load_feeds()
        enabled = [f for f in feeds if f.get("enabled")]
        self.assertTrue(len(enabled) >= 1, "At least one feed should be enabled")


class TestTextExtractor(unittest.TestCase):
    def test_extracts_paragraph_text(self):
        e = knowledge_loop._TextExtractor()
        e.feed("<p>Hello world</p>")
        self.assertIn("Hello world", e.result())

    def test_skips_script_content(self):
        e = knowledge_loop._TextExtractor()
        e.feed("<script>alert('xss')</script><p>safe</p>")
        result = e.result()
        self.assertIn("safe", result)
        self.assertNotIn("alert", result)

    def test_skips_style_content(self):
        e = knowledge_loop._TextExtractor()
        e.feed("<style>body{color:red}</style><span>text</span>")
        self.assertNotIn("color", e.result())

    def test_skips_nav_content(self):
        e = knowledge_loop._TextExtractor()
        e.feed("<nav>skip me</nav><main>keep me</main>")
        result = e.result()
        self.assertNotIn("skip me", result)
        self.assertIn("keep me", result)

    def test_nested_skip_tags(self):
        e = knowledge_loop._TextExtractor()
        e.feed("<script><div>inner</div></script><p>outer</p>")
        result = e.result()
        self.assertNotIn("inner", result)
        self.assertIn("outer", result)


class TestLoadState(unittest.TestCase):
    def test_returns_dict(self):
        state = knowledge_loop._load_state()
        self.assertIsInstance(state, dict)


class TestPluginProtocol(unittest.TestCase):
    def test_plugin_cmd_writes_valid_json(self):
        """knowledge_loop main() with 'plugin' arg must output one valid JSON line."""
        fake_stdin = io.StringIO('{"task_type": "knowledge-loop"}\n')
        fake_stdout = io.StringIO()

        with patch("sys.argv", ["knowledge_loop.py", "plugin"]), \
             patch("sys.stdin", fake_stdin), \
             patch("sys.stdout", fake_stdout), \
             patch.object(knowledge_loop, "run_loop", return_value=[]):
            try:
                knowledge_loop.main()
            except SystemExit:
                pass

        output = fake_stdout.getvalue().strip()
        self.assertTrue(output, "Plugin must write to stdout")
        result = json.loads(output)
        self.assertIn("ok", result)
        self.assertIn("result", result)
        self.assertIn("message", result)


if __name__ == "__main__":
    unittest.main()
