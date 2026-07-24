"""Tests for plugins/fetch_url_plugin.py."""

from __future__ import annotations

import io
import json
import pathlib
import socket
import sys
import threading
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "plugins"))

import fetch_url_plugin as fup


def _make_mock_server(response: str) -> tuple[int, threading.Thread]:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)

    def _serve():
        try:
            conn, _ = srv.accept()
            conn.recv(4096)
            conn.sendall(response.encode("utf-8"))
            conn.close()
        finally:
            srv.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    return port, t


def _html_response(body: str) -> str:
    html = f"<html><head><title>T</title></head><body>{body}</body></html>"
    return (
        f"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
        f"Content-Length: {len(html)}\r\n\r\n{html}"
    )


class TestTextExtractor(unittest.TestCase):
    def test_strips_script_and_style(self):
        ex = fup._TextExtractor()
        ex.feed("<p>Hello</p><script>alert(1)</script><style>body{}</style><p>World</p>")
        self.assertEqual(ex.result(), "Hello World")

    def test_skips_nav_and_footer(self):
        ex = fup._TextExtractor()
        ex.feed("<nav>Menu</nav><main>Content</main><footer>Footer</footer>")
        self.assertEqual(ex.result(), "Content")

    def test_strips_nested_skip_tags(self):
        ex = fup._TextExtractor()
        ex.feed("<script><script>inner</script></script>visible")
        self.assertNotIn("inner", ex.result())
        self.assertIn("visible", ex.result())


class TestFetchPlugin(unittest.TestCase):
    def _run_plugin(self, payload: dict, env_patch: dict | None = None) -> dict:
        import os
        request_line = json.dumps({"payload": payload}) + "\n"
        captured = io.StringIO()

        orig_env = {}
        for k, v in (env_patch or {}).items():
            orig_env[k] = os.environ.get(k)
            os.environ[k] = v
        try:
            orig_stdin = sys.stdin
            orig_stdout = sys.stdout
            sys.stdin = io.StringIO(request_line)
            sys.stdout = captured
            fup.main()
        finally:
            sys.stdin = orig_stdin
            sys.stdout = orig_stdout
            for k, orig in orig_env.items():
                if orig is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = orig

        return json.loads(captured.getvalue())

    def test_missing_url_returns_not_ok(self):
        result = self._run_plugin({})
        self.assertFalse(result["ok"])
        self.assertIn("url", result["result"].get("reason", ""))

    def test_successful_html_fetch(self):
        port, _ = _make_mock_server(_html_response("<p>Hello world</p>"))
        result = self._run_plugin({"url": f"http://127.0.0.1:{port}/"})
        self.assertTrue(result["ok"])
        self.assertIn("Hello world", result["result"]["text"])
        self.assertGreater(result["result"]["chars"], 0)

    def test_http_error_surfaces_status_code(self):
        body = json.dumps({"error": "forbidden"})
        resp = f"HTTP/1.1 403 Forbidden\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        port, _ = _make_mock_server(resp)
        result = self._run_plugin({"url": f"http://127.0.0.1:{port}/"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["result"]["http_status"], 403)

    def test_unreachable_host_is_reported(self):
        result = self._run_plugin({"url": "http://127.0.0.1:1/nope"})
        self.assertFalse(result["ok"])

    def test_max_chars_truncates(self):
        long_content = "X" * 2000
        port, _ = _make_mock_server(_html_response(f"<p>{long_content}</p>"))
        result = self._run_plugin({"url": f"http://127.0.0.1:{port}/", "max_chars": 500})
        self.assertTrue(result["ok"])
        self.assertLessEqual(result["result"]["chars"], 500)


if __name__ == "__main__":
    unittest.main()
