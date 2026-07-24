"""Tests for plugins/router_plugin.py — skill detection and provider resolution."""

from __future__ import annotations

import json
import pathlib
import socket
import sys
import threading
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "plugins"))

import router_plugin as rp


def _make_mock_server(reply_content: str, status: int = 200) -> tuple[int, threading.Thread]:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)

    def _serve():
        try:
            conn, _ = srv.accept()
            conn.recv(8192)
            body = json.dumps({"choices": [{"message": {"content": reply_content}}]})
            resp = (
                f"HTTP/1.1 {status} {'OK' if status == 200 else 'Error'}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n\r\n{body}"
            )
            conn.sendall(resp.encode("utf-8"))
            conn.close()
        finally:
            srv.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    return port, t


DEFAULT_SKILLS = {
    "skills": {
        "code":     {"keywords": ["def ", "function", "bug"], "providers": ["ollama"]},
        "research": {"keywords": ["what is", "explain"],      "providers": ["ollama"]},
        "general":  {"keywords": [],                          "providers": ["ollama"]},
    },
    "default_skill": "general",
}


class TestSkillDetection(unittest.TestCase):
    def test_code_keyword_detected(self):
        self.assertEqual(rp._detect_skill("please fix this bug in my code", DEFAULT_SKILLS), "code")

    def test_research_keyword_detected(self):
        self.assertEqual(rp._detect_skill("what is machine learning?", DEFAULT_SKILLS), "research")

    def test_falls_back_to_general(self):
        self.assertEqual(rp._detect_skill("hello there", DEFAULT_SKILLS), "general")

    def test_case_insensitive(self):
        self.assertEqual(rp._detect_skill("What Is rust?", DEFAULT_SKILLS), "research")


class TestProviderResolution(unittest.TestCase):
    def test_ollama_returns_none_when_not_enabled(self):
        import os
        old = os.environ.pop("HM_OLLAMA_ENABLE", None)
        try:
            result = rp._try_ollama()
        finally:
            if old:
                os.environ["HM_OLLAMA_ENABLE"] = old
        self.assertIsNone(result)

    def test_ollama_resolves_when_enabled(self):
        import os
        os.environ["HM_OLLAMA_ENABLE"] = "true"
        try:
            result = rp._try_ollama()
        finally:
            del os.environ["HM_OLLAMA_ENABLE"]
        self.assertIsNotNone(result)
        url, key, model = result
        self.assertIn("11434", url)
        self.assertEqual(key, "")

    def test_pollinations_always_resolves(self):
        url, key, model = rp._try_pollinations("openai")
        self.assertIn("pollinations", url)
        self.assertEqual(key, "")
        self.assertEqual(model, "openai")

    def test_active_returns_none_when_no_file(self):
        import os
        orig = rp.ACTIVE_FILE
        rp.ACTIVE_FILE = pathlib.Path("/nonexistent/llm-active.json")
        try:
            result = rp._try_active()
        finally:
            rp.ACTIVE_FILE = orig
        self.assertIsNone(result)


class TestRouterCallsProvider(unittest.TestCase):
    def test_routes_to_active_provider_via_mock(self):
        import io, os, tempfile

        port, _ = _make_mock_server("router reply here")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "ok": True, "provider": "test", "url": f"http://127.0.0.1:{port}/v1/chat/completions",
                "key": "", "model": "test-model",
            }, f)
            active_path = pathlib.Path(f.name)

        skills_config = {
            "skills": {
                "general": {"keywords": [], "providers": ["active"]},
            },
            "default_skill": "general",
        }

        orig_active = rp.ACTIVE_FILE
        rp.ACTIVE_FILE = active_path
        request_line = json.dumps({"payload": {"message": "hello"}}) + "\n"
        captured = io.StringIO()
        orig_stdin, orig_stdout = sys.stdin, sys.stdout
        sys.stdin = io.StringIO(request_line)
        sys.stdout = captured

        try:
            # Patch skills loader
            orig_load = rp._load_skills
            rp._load_skills = lambda: skills_config
            rp.main()
        finally:
            rp.ACTIVE_FILE = orig_active
            rp._load_skills = orig_load
            sys.stdin = orig_stdin
            sys.stdout = orig_stdout
            active_path.unlink(missing_ok=True)

        result = json.loads(captured.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["reply"], "router reply here")


if __name__ == "__main__":
    unittest.main()
