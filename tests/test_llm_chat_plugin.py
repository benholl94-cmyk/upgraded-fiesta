from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "llm_chat_plugin.py"


def _run_plugin(request: dict, env: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(request) + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 0
    return json.loads(proc.stdout.strip())


def _base_env(**overrides: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("HM_LLM_")}
    # Point active-provider file to /dev/null so tests are isolated from any
    # llm-active.json that may exist in the workspace from key-manager runs.
    env["HM_LLM_ACTIVE_FILE"] = "/dev/null"
    env.update(overrides)
    return env


def test_refuses_without_explicit_enable() -> None:
    response = _run_plugin(
        {"task_type": "llm-chat", "objective": "hi", "payload": {"message": "hi"}},
        _base_env(HM_LLM_API_URL="http://127.0.0.1:1/v1/chat/completions", HM_LLM_API_KEY="k", HM_LLM_MODEL="m"),
    )
    assert response["ok"] is False
    assert "HM_LLM_ENABLE" in response["result"]["reason"]


def test_refuses_when_enabled_but_missing_config() -> None:
    response = _run_plugin(
        {"task_type": "llm-chat", "objective": "hi", "payload": {"message": "hi"}},
        _base_env(HM_LLM_ENABLE="true"),
    )
    assert response["ok"] is False
    assert "HM_LLM_API_URL" in response["result"]["reason"]


class _MockChatCompletions(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - required BaseHTTPRequestHandler name
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        assert self.headers.get("Authorization") == "Bearer test-key"
        assert body["model"] == "test-model"
        reply = f"echo: {body['messages'][0]['content']}"
        response = json.dumps({"choices": [{"message": {"content": reply}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args) -> None:  # silence test output
        pass


class _MockServerErrorHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = json.dumps({"error": "boom"}).encode("utf-8")
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def _serve_once(handler_cls) -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    return server, url


def test_successful_round_trip_against_a_hermetic_local_mock_server() -> None:
    server, url = _serve_once(_MockChatCompletions)
    try:
        response = _run_plugin(
            {"task_type": "llm-chat", "objective": "hi", "payload": {"message": "hello there"}},
            _base_env(HM_LLM_ENABLE="true", HM_LLM_API_URL=url, HM_LLM_API_KEY="test-key", HM_LLM_MODEL="test-model"),
        )
    finally:
        server.server_close()
    assert response["ok"] is True
    assert response["result"]["reply"] == "echo: hello there"


def test_upstream_error_status_is_surfaced_not_masked() -> None:
    server, url = _serve_once(_MockServerErrorHandler)
    try:
        response = _run_plugin(
            {"task_type": "llm-chat", "objective": "hi", "payload": {"message": "hello there"}},
            _base_env(HM_LLM_ENABLE="true", HM_LLM_API_URL=url, HM_LLM_API_KEY="test-key", HM_LLM_MODEL="test-model"),
        )
    finally:
        server.server_close()
    assert response["ok"] is False
    assert response["result"]["http_status"] == 500


def test_unreachable_url_is_reported_not_silently_swallowed() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        free_port = sock.getsockname()[1]

    response = _run_plugin(
        {"task_type": "llm-chat", "objective": "hi", "payload": {"message": "hello"}},
        _base_env(
            HM_LLM_ENABLE="true",
            HM_LLM_API_URL=f"http://127.0.0.1:{free_port}/v1/chat/completions",
            HM_LLM_API_KEY="test-key",
            HM_LLM_MODEL="test-model",
        ),
    )
    assert response["ok"] is False
    assert "reason" in response["result"]
