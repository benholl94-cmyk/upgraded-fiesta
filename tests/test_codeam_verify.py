"""Die vier Beweise von `codeam_cli.py verify` — und ob sie fallen koennen.

`verify` meldete lange `ok`, nachdem es **einen** von vier Beweisen gefuehrt
hatte: `/health` antwortet. Das sagt, dass ein Prozess lebt. Es sagt nicht,
dass der Zugang gesperrt ist, und nicht, dass sich das System befehligen
laesst — also genau das nicht, was den Weg operativ macht. Eine Pruefung, die
gruen meldet und weniger prueft als das eigene Release, ist schlimmer als
keine: man verlaesst sich darauf.

Gepruefft wird hier gegen einen **hermetischen** HTTP-Server im selben
Prozess, nicht gegen ein echtes Gateway. Der Grund ist der Gegentest: um zu
zeigen, dass `gesperrt` faellt, muss ein Server antworten, der *offen* ist —
und ein absichtlich offenes Gateway auf einem echten Port zu starten waere
genau die Sorte Aktion, die man nicht in einer Testsuite haben will.
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import codeam_cli as cc  # noqa: E402

TOKEN = "test-token-not-a-real-secret"
UMGEBUNG = {"HM_OWNER_TOKEN": TOKEN}


class Lage:
    """Was der Testserver gerade sein soll."""
    offen = False           # antwortet /health auch ohne Token mit 200?
    chat_bricht_ab = False  # Stream ohne [DONE]
    dispatch = "plugin_dispatched"


def _handler(lage: Lage):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # kein Testrauschen
            pass

        def _senden(self, code: int, koerper: str):
            roh = koerper.encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(roh)))
            self.end_headers()
            self.wfile.write(roh)

        def _hat_token(self) -> bool:
            return self.headers.get("Authorization") == f"Bearer {TOKEN}"

        def do_GET(self):
            if not self._hat_token() and not lage.offen:
                return self._senden(401, '{"error":"unauthorized"}')
            self._senden(200, '{"status":"online"}')

        def do_POST(self):
            laenge = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(laenge)
            if self.path == "/chat":
                text = 'data: {"typ": "token", "text": "T0"}\n\n'
                if not lage.chat_bricht_ab:
                    text += ('data: {"typ": "ende", "text": "", '
                             '"meta": {"tier": "T0"}}\n\ndata: [DONE]\n\n')
                return self._senden(200, text)
            antwort = {"accepted": True, "dispatch": lage.dispatch}
            if lage.dispatch != "plugin_dispatched":
                antwort["dispatch_reason"] = "no plugin registered"
            self._senden(202, json.dumps(antwort))
    return H


@pytest.fixture
def server():
    lage = Lage()
    srv = HTTPServer(("127.0.0.1", 0), _handler(lage))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    k = {"dienst": {"port": srv.server_address[1],
                    "auth": {"env": "HM_OWNER_TOKEN"},
                    "health": {"pfad": "/health"},
                    "chat": {"pfad": "/chat"}}}
    yield k, lage
    srv.shutdown()


# ---------------------------------------------------------------------------
# Der gesperrte Zugang — die einzige Pruefung, deren Erfolg ein Fehlercode ist
# ---------------------------------------------------------------------------

def test_a_locked_gateway_passes(server):
    k, _ = server
    s = cc._gesperrt(k)
    assert s.stand == cc.OK, s.detail


def test_an_open_gateway_is_caught(server):
    """Der Gegentest, der zaehlt. Ein 200 ohne Token ist ein offenes Gateway —
    und das faellt sonst niemandem auf, weil jede andere Pruefung weiter
    gruen meldet."""
    k, lage = server
    lage.offen = True
    s = cc._gesperrt(k)
    assert s.stand == cc.FEHLT
    assert "401" in s.detail


# ---------------------------------------------------------------------------
# Der Befehlskanal
# ---------------------------------------------------------------------------

def test_a_complete_stream_passes_and_names_the_tier(server):
    k, _ = server
    s = cc._chat(k, UMGEBUNG)
    assert s.stand == cc.OK
    assert "T0" in s.detail


def test_a_stream_that_stops_early_is_caught(server):
    """Ein Stream, der beginnt und abbricht, sieht am Anfang genauso aus wie
    einer, der traegt — deshalb ist `[DONE]` das Kriterium, nicht das erste
    Byte."""
    k, lage = server
    lage.chat_bricht_ab = True
    s = cc._chat(k, UMGEBUNG)
    assert s.stand == cc.FEHLT
    assert "DONE" in s.detail


# ---------------------------------------------------------------------------
# Der Dispatch
# ---------------------------------------------------------------------------

def test_a_dispatched_task_passes(server):
    k, _ = server
    assert cc._dispatch(k, UMGEBUNG).stand == cc.OK


def test_accepted_but_undispatched_is_not_a_pass(server):
    """`202 accepted` allein ist wertlos: genau das hat das Gateway
    monatelang geantwortet, waehrend jeder Task ins Leere lief. Alle sechs
    Cronjobs liefen, keiner erreichte ein Plugin, beide Seiten meldeten
    Erfolg."""
    k, lage = server
    lage.dispatch = "unhandled"
    s = cc._dispatch(k, UMGEBUNG)
    assert s.stand == cc.FEHLT
    assert "unhandled" in s.detail


# ---------------------------------------------------------------------------
# Dass verify sie ueberhaupt fuehrt
# ---------------------------------------------------------------------------

def test_verify_runs_all_four_proofs_not_just_health():
    """Ein Weg, der weniger prueft als sein eigenes Release, meldet gruen und
    traegt nicht. Dieselben vier fuehrt `.github/workflows/release.yml` am
    Containerimage."""
    quelle = (REPO / "scripts" / "codeam_cli.py").read_text(encoding="utf-8")
    block = quelle.partition("def verify(")[2].partition("\ndef ")[0]
    for beweis in ("_health", "_gesperrt", "_chat", "_dispatch"):
        assert beweis in block, f"verify fuehrt {beweis} nicht"


def test_the_release_workflow_proves_the_same_four():
    wf = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for beweis in ("/health", "401", "DONE", "plugin_dispatched"):
        assert beweis in wf
