"""Tests for scripts/llm_key_manager.py — probe, rotation, active-file writing."""

from __future__ import annotations

import json
import pathlib
import socket
import sys
import tempfile
import threading
import time
import types
import unittest

# Make the scripts/ directory importable without installing.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import llm_key_manager as km


# ---------------------------------------------------------------------------
# Minimal mock HTTP server (same pattern as test_llm_chat_plugin.py)
# ---------------------------------------------------------------------------

def _make_mock_server(response_lines: list[str]) -> tuple[int, threading.Thread]:
    """Binds a one-shot TCP server on a random port, returns (port, thread)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.listen(1)

    def _serve():
        try:
            conn, _ = server.accept()
            conn.recv(4096)  # consume request
            for line in response_lines:
                conn.sendall(line.encode())
            conn.close()
        finally:
            server.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    return port, t


def _ok_response(content: str) -> list[str]:
    body = json.dumps({"choices": [{"message": {"content": content}}]})
    return [
        f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
    ]


def _error_response(code: int) -> list[str]:
    body = json.dumps({"error": "test error"})
    return [
        f"HTTP/1.1 {code} Error\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProbeSuccess(unittest.TestCase):
    def test_probe_returns_true_on_200(self):
        port, _ = _make_mock_server(_ok_response("pong"))
        ok, detail = km._probe(f"http://127.0.0.1:{port}/v1/chat/completions", "", "test-model")
        self.assertTrue(ok)
        self.assertIn("ok", detail)

    def test_probe_includes_reply_preview(self):
        port, _ = _make_mock_server(_ok_response("hello world"))
        ok, detail = km._probe(f"http://127.0.0.1:{port}/v1/chat/completions", "key", "m")
        self.assertTrue(ok)
        self.assertIn("hello world", detail)


class TestProbeFailure(unittest.TestCase):
    def test_probe_returns_false_on_http_error(self):
        port, _ = _make_mock_server(_error_response(401))
        ok, detail = km._probe(f"http://127.0.0.1:{port}/v1/chat/completions", "bad-key", "m")
        self.assertFalse(ok)
        self.assertIn("401", detail)

    def test_probe_returns_false_on_unreachable(self):
        ok, detail = km._probe("http://127.0.0.1:1/v1/chat/completions", "", "m")
        self.assertFalse(ok)
        self.assertTrue(detail.startswith("URLError") or "error" in detail.lower())


class TestNoKeySkip(unittest.TestCase):
    def test_check_skips_provider_without_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = pathlib.Path(tmpdir)
            providers_file = tmpdir / "providers.json"
            providers_file.write_text(json.dumps([
                {"name": "groq", "url": "http://127.0.0.1:1/v1/chat/completions",
                 "model": "x", "key_env": "GROQ_KEY_NONEXISTENT"}
            ]))
            active_file = tmpdir / "llm-active.json"

            orig_pf = km.PROVIDERS_FILE
            orig_af = km.ACTIVE_FILE
            orig_lf = km.LOG_FILE
            km.PROVIDERS_FILE = providers_file
            km.ACTIVE_FILE = active_file
            km.LOG_FILE = tmpdir / "log.json"
            try:
                winner = km.check_and_rotate(dry_run=True)
            finally:
                km.PROVIDERS_FILE = orig_pf
                km.ACTIVE_FILE = orig_af
                km.LOG_FILE = orig_lf

            self.assertIsNone(winner)


class TestWriteActive(unittest.TestCase):
    def test_write_and_read_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            active_file = pathlib.Path(tmpdir) / "llm-active.json"
            orig = km.ACTIVE_FILE
            km.ACTIVE_FILE = active_file
            try:
                km._write_active("groq", "http://example.com", "key123", "llama3")
                data = json.loads(active_file.read_text())
            finally:
                km.ACTIVE_FILE = orig

            self.assertTrue(data["ok"])
            self.assertEqual(data["provider"], "groq")
            self.assertEqual(data["key"], "key123")
            self.assertIn("checked_at", data)

    def test_write_inactive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            active_file = pathlib.Path(tmpdir) / "llm-active.json"
            orig = km.ACTIVE_FILE
            km.ACTIVE_FILE = active_file
            try:
                km._write_inactive("all failed")
                data = json.loads(active_file.read_text())
            finally:
                km.ACTIVE_FILE = orig

            self.assertFalse(data["ok"])
            self.assertEqual(data["reason"], "all failed")


class TestDryRun(unittest.TestCase):
    def test_dry_run_does_not_write_active_file(self):
        import os
        port, _ = _make_mock_server(_ok_response("pong"))
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = pathlib.Path(tmpdir)
            # Non-ollama provider with a key from the keys file so it isn't skipped.
            keys_file = tmpdir / "keys.json"
            keys_file.write_text(json.dumps({"mock-provider": "testkey"}))
            providers_file = tmpdir / "providers.json"
            providers_file.write_text(json.dumps([
                {"name": "mock-provider", "url": f"http://127.0.0.1:{port}/v1/chat/completions",
                 "model": "test", "key_env": "NONEXISTENT_ENV_VAR"}
            ]))
            active_file = tmpdir / "llm-active.json"

            orig_pf = km.PROVIDERS_FILE
            orig_af = km.ACTIVE_FILE
            orig_lf = km.LOG_FILE
            old_keys_env = os.environ.get("HM_LLM_KEYS_FILE")
            km.PROVIDERS_FILE = providers_file
            km.ACTIVE_FILE = active_file
            km.LOG_FILE = tmpdir / "log.json"
            os.environ["HM_LLM_KEYS_FILE"] = str(keys_file)
            try:
                winner = km.check_and_rotate(dry_run=True)
            finally:
                km.PROVIDERS_FILE = orig_pf
                km.ACTIVE_FILE = orig_af
                km.LOG_FILE = orig_lf
                if old_keys_env is None:
                    os.environ.pop("HM_LLM_KEYS_FILE", None)
                else:
                    os.environ["HM_LLM_KEYS_FILE"] = old_keys_env

            # dry_run must not write the active file even on success.
            self.assertFalse(active_file.exists())
            self.assertIsNotNone(winner)


if __name__ == "__main__":
    unittest.main()
