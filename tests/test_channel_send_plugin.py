"""Tests des Kanal-Versands.

Geprueft wird gegen einen **hermetischen lokalen Server**, nie gegen Telegram,
Slack, Discord oder Meta. Ein Test, der ein echtes Konto braucht, laeuft in CI
nie und beweist deshalb nichts.

Was hier NICHT behauptet wird: dass eine Nachricht bei einem echten Anbieter
ankommt. Dafuer braucht es Zugangsdaten, und die hat nur der Master. Bewiesen
wird die Verdrahtung — Zielwahl, Kopfzeilen, Koerper, Fehlerrichtung.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "channel_send_plugin.py"
sys.path.insert(0, str(REPO / "plugins"))

import channel_send_plugin as csp  # noqa: E402


def _lauf(req: dict, env: dict | None = None) -> dict:
    import os
    e = dict(os.environ)
    for k in list(e):
        if k.startswith(("HM_TELEGRAM", "HM_SLACK", "HM_DISCORD", "HM_WHATSAPP")):
            del e[k]
    e.update(env or {})
    p = subprocess.run([sys.executable, str(PLUGIN)], input=json.dumps(req),
                       capture_output=True, text=True, timeout=30, env=e)
    return json.loads(p.stdout)


# ---------------------------------------------------------------------------
# Verweigerung ist laut
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("task_type,var", [
    ("telegram-message", "HM_TELEGRAM_BOT_TOKEN"),
    ("slack-message", "HM_SLACK_BOT_TOKEN"),
    ("discord-message", "HM_DISCORD_BOT_TOKEN"),
    ("whatsapp-message", "HM_WHATSAPP_BOT_TOKEN"),
])
def test_a_missing_token_refuses_loudly_and_says_where_to_get_one(task_type, var):
    """Ein Kanal, der schweigend nicht sendet, ist schlimmer als keiner —
    man verlaesst sich auf ihn."""
    r = _lauf({"task_type": task_type, "payload": {"chat_id": 1, "channel": "C",
                                                   "channel_id": "1", "to": "49",
                                                   "phone_number_id": "1",
                                                   "text": "x"}})
    assert r["ok"] is False
    assert var in r["message"]
    assert "http" in r["message"], "keine Bezugsquelle genannt"


def test_an_incomplete_payload_names_the_missing_field():
    r = _lauf({"task_type": "discord-message", "payload": {"text": "hi"}},
              {"HM_DISCORD_BOT_TOKEN": "t"})
    assert r["ok"] is False
    assert "channel_id" in r["message"]


def test_an_unknown_task_type_is_refused():
    r = _lauf({"task_type": "signal-message", "payload": {}})
    assert r["ok"] is False


def test_broken_json_does_not_crash_the_protocol():
    """Eine kaputte Zeile muss eine gueltige Antwortzeile ergeben — sonst
    liest hm-plugins 'produced no output' und die Ursache ist verloren."""
    p = subprocess.run([sys.executable, str(PLUGIN)], input="{kaputt",
                       capture_output=True, text=True, timeout=30)
    assert json.loads(p.stdout)["ok"] is False


# ---------------------------------------------------------------------------
# Verdrahtung gegen einen echten HTTP-Server (lokal, hermetisch)
# ---------------------------------------------------------------------------

class _Mock(BaseHTTPRequestHandler):
    gesehen: dict = {}
    antwort: tuple = (200, {"ok": True, "result": "zugestellt"})

    def do_POST(self):
        laenge = int(self.headers.get("Content-Length", 0))
        _Mock.gesehen = {
            "pfad": self.path,
            "auth": self.headers.get("Authorization"),
            "ctype": self.headers.get("Content-Type"),
            "body": json.loads(self.rfile.read(laenge) or b"{}"),
        }
        code, body = _Mock.antwort
        roh = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Mock)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_slack_sends_the_right_body_and_header(server, monkeypatch):
    monkeypatch.setenv("HM_SLACK_BOT_TOKEN", "xoxb-geheim")
    monkeypatch.setitem(csp.KANAELE["slack-message"], "url", lambda t: server + "/x")
    ok, result, msg = csp.senden("slack-message", {"channel": "C42", "text": "hallo"})
    assert ok, msg
    assert _Mock.gesehen["auth"] == "Bearer xoxb-geheim"
    assert _Mock.gesehen["ctype"] == "application/json"
    assert _Mock.gesehen["body"] == {"channel": "C42", "text": "hallo"}


def test_a_provider_error_inside_a_200_is_not_a_success(server, monkeypatch):
    """Slack antwortet mit HTTP 200 UND {"ok": false}. Wer nur den Statuscode
    prueft, meldet jeden Fehler als Erfolg — das ist der teure Irrtum hier."""
    monkeypatch.setenv("HM_SLACK_BOT_TOKEN", "x")
    monkeypatch.setitem(csp.KANAELE["slack-message"], "url", lambda t: server + "/x")
    _Mock.antwort = (200, {"ok": False, "error": "channel_not_found"})
    try:
        ok, result, msg = csp.senden("slack-message", {"channel": "C", "text": "t"})
        assert ok is False
        assert result.get("error") == "channel_not_found"
    finally:
        _Mock.antwort = (200, {"ok": True, "result": "zugestellt"})


def test_an_http_error_is_reported_with_its_status(server, monkeypatch):
    monkeypatch.setenv("HM_SLACK_BOT_TOKEN", "x")
    monkeypatch.setitem(csp.KANAELE["slack-message"], "url", lambda t: server + "/x")
    _Mock.antwort = (401, {"error": "invalid_auth"})
    try:
        ok, result, msg = csp.senden("slack-message", {"channel": "C", "text": "t"})
        assert ok is False and result.get("status") == 401
    finally:
        _Mock.antwort = (200, {"ok": True, "result": "zugestellt"})


def test_the_token_never_appears_in_the_answer(server, monkeypatch):
    """Die Antwort landet in hm-memory und im Audit-Log."""
    monkeypatch.setenv("HM_SLACK_BOT_TOKEN", "xoxb-streng-geheim")
    monkeypatch.setitem(csp.KANAELE["slack-message"], "url", lambda t: server + "/x")
    ok, result, msg = csp.senden("slack-message", {"channel": "C", "text": "t"})
    assert "xoxb-streng-geheim" not in json.dumps({"r": result, "m": msg})


def test_a_dry_run_is_never_reported_as_delivery():
    ok, result, msg = csp.senden("telegram-message", {"chat_id": 1, "text": "x"})
    # ohne Token: Verweigerung, kein Trockenlauf
    assert ok is False


# ---------------------------------------------------------------------------
# Zusammenhang: die Task-Typen zeigen wirklich hierher
# ---------------------------------------------------------------------------

def test_the_manifest_routes_every_channel_here_and_not_to_echo():
    """Der eigentliche Befund, der zu dieser Datei fuehrte: alle vier
    Kanal-Task-Typen zeigten auf echo_plugin.py. Wer eine Nachricht schickte,
    bekam sie gespiegelt und sendete nichts."""
    manifest = json.loads((REPO / "config" / "plugins.json").read_text())
    ziele = {p["task_type"]: p["command"] for p in manifest["plugins"]}
    for tt in ("telegram-message", "discord-message", "slack-message",
               "whatsapp-message"):
        assert tt in ziele, f"{tt} nicht registriert"
        assert ziele[tt][-1].endswith("channel_send_plugin.py"), \
            f"{tt} zeigt auf {ziele[tt]}"


def test_every_registered_channel_is_implemented():
    manifest = json.loads((REPO / "config" / "plugins.json").read_text())
    registriert = {p["task_type"] for p in manifest["plugins"]
                   if p["command"][-1].endswith("channel_send_plugin.py")}
    assert registriert == set(csp.KANAELE), \
        f"Manifest und Implementierung driften: {registriert ^ set(csp.KANAELE)}"
