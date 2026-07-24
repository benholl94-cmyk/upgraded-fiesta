#!/usr/bin/env python3
"""
hardware_console.py — MUNIN Hardware-Console
=============================================
Direkter Kanal: Repo → Hardware (iPhone/Mobile)

Architektur:
  Repo (git) → hardware_console.py → SSE-Stream → iPhone Safari
                                   ↓
                              hm-gateway /tasks  (bidirektional)

Endpunkte:
  GET  /           → iPhone-optimierte Console-UI (HTML)
  GET  /stream     → Server-Sent Events (Live-Push: Status, Commits, Tasks)
  POST /inject     → Direktinjektion: Befehl/Payload → Hardware
  GET  /status     → JSON: aktueller Repo+Gateway-Status
  POST /gateway    → Weiterleitung an hm-gateway /tasks
  GET  /health     → Selbsttest

Env-Vars:
  HM_CONSOLE_PORT    — Bind-Port (Standard: 7799)
  HM_CONSOLE_BIND    — Bind-Adresse (Standard: 0.0.0.0 = LAN-erreichbar)
  HM_OWNER_TOKEN     — Gateway-Auth
  HM_GATEWAY_URL     — Gateway-URL (Standard: http://localhost:8080)
  HM_CONSOLE_SECRET  — Optionaler Console-Zugriffsschutz (Bearer-Token)

Starten:
  python3 scripts/hardware_console.py
  python3 scripts/hardware_console.py --port 7799 --bind 0.0.0.0
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT   = Path(__file__).parent.parent
STATE_FILE  = REPO_ROOT / ".claude" / "persona" / "munin-state.json"
STATUS_FILE = REPO_ROOT / ".claude" / "persona" / "munin-link-status.json"
LOG_FILE    = REPO_ROOT / ".claude" / "persona" / "console-log.json"

GATEWAY_URL   = os.environ.get("HM_GATEWAY_URL", "http://localhost:8080")
OWNER_TOKEN   = os.environ.get("HM_OWNER_TOKEN", "")
CONSOLE_SECRET = os.environ.get("HM_CONSOLE_SECRET", "")

# ── Event-Bus (SSE) ───────────────────────────────────────────────────────────

_clients: list[queue.Queue] = []
_clients_lock = threading.Lock()


def broadcast(event_type: str, data: dict) -> None:
    """Sendet ein SSE-Event an alle verbundenen Clients."""
    payload = json.dumps({"type": event_type, "ts": _now_iso(), **data})
    msg = f"event: {event_type}\ndata: {payload}\n\n"
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)
    _log_event(event_type, data)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log_event(event_type: str, data: dict) -> None:
    """Schreibt Events in console-log.json (Ring-Buffer, max 200 Einträge).
    Format: {"entries": [{ts, type, ...}, ...]} — kompatibel mit security_sentinel.py."""
    try:
        log: dict = {"entries": []}
        if LOG_FILE.exists():
            raw = json.loads(LOG_FILE.read_text())
            # Migration: flache Liste → dict mit entries
            if isinstance(raw, list):
                log = {"entries": raw}
            elif isinstance(raw, dict):
                log = raw
        log.setdefault("entries", [])
        log["entries"].append({"ts": _now_iso(), "type": event_type, **data})
        log["entries"] = log["entries"][-200:]  # Ring-Buffer
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── Git / Repo-Status ─────────────────────────────────────────────────────────

def _run_git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=REPO_ROOT, text=True,
            stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError:
        return ""


def get_repo_status() -> dict:
    branch   = _run_git("branch", "--show-current") or "unknown"
    tip      = _run_git("log", "-1", "--format=%h %s") or "—"
    unpushed = _run_git("rev-list", "origin/HEAD..HEAD", "--count") or "0"
    dirty    = bool(_run_git("status", "--porcelain"))
    return {
        "branch":   branch,
        "tip":      tip,
        "unpushed": int(unpushed),
        "dirty":    dirty,
    }


def get_munin_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def get_console_status() -> dict:
    repo  = get_repo_status()
    state = get_munin_state()
    gw_ok = _gateway_health()
    return {
        "ts":       _now_iso(),
        "repo":     repo,
        "focus":    state.get("currentFocus", {}),
        "write_mode": state.get("writeMode", "unknown"),
        "gateway":  {"ok": gw_ok, "url": GATEWAY_URL},
        "console":  {"version": "1.0", "uptime_s": int(time.time() - _START_TIME)},
    }


_START_TIME = time.time()


# ── Gateway-Verbindung ────────────────────────────────────────────────────────

def _gateway_health() -> bool:
    if not OWNER_TOKEN:
        return False
    try:
        req = urllib.request.Request(
            f"{GATEWAY_URL}/health",
            headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
        )
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def _gateway_post(path: str, body: dict) -> dict | None:
    if not OWNER_TOKEN:
        return None
    try:
        data = json.dumps(body).encode()
        req  = urllib.request.Request(
            f"{GATEWAY_URL}{path}", data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OWNER_TOKEN}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


# ── Hintergrund-Watcher ───────────────────────────────────────────────────────

def _watch_repo(interval: int = 10) -> None:
    """Pollt den Repo-Status und broadcastet Änderungen."""
    last = {}
    while True:
        try:
            current = get_repo_status()
            if current != last:
                broadcast("repo-update", {"repo": current})
                last = current
        except Exception:
            pass
        time.sleep(interval)


def _watch_status_file(interval: int = 5) -> None:
    """Pollt munin-link-status.json und broadcastet Änderungen."""
    last_ts = None
    while True:
        try:
            if STATUS_FILE.exists():
                ts = STATUS_FILE.stat().st_mtime
                if ts != last_ts:
                    data = json.loads(STATUS_FILE.read_text())
                    broadcast("munin-status", {"status": data})
                    last_ts = ts
        except Exception:
            pass
        time.sleep(interval)


# ── Console HTML ──────────────────────────────────────────────────────────────

CONSOLE_HTML = """\
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>MUNIN Hardware Console</title>
<style>
  :root {
    --bg:    #0d0f14;
    --panel: #151820;
    --border:#1e2535;
    --green: #00ff88;
    --cyan:  #00cfff;
    --yellow:#ffd54f;
    --red:   #ff5252;
    --dim:   #556080;
    --text:  #c8d0e0;
    --mono:  'SF Mono', 'Fira Mono', 'Courier New', monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text);
    font-family: var(--mono); font-size: 13px;
    min-height: 100dvh; padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
  }
  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 16px; border-bottom: 1px solid var(--border);
    background: var(--panel);
  }
  header h1 { font-size: 14px; color: var(--green); letter-spacing: 2px; }
  #conn-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--dim); transition: background 0.3s;
  }
  #conn-dot.live { background: var(--green); box-shadow: 0 0 6px var(--green); }
  #conn-dot.err  { background: var(--red); }

  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1px; background: var(--border);
    border-top: 1px solid var(--border);
  }
  @media (max-width: 500px) { .grid { grid-template-columns: 1fr; } }

  .panel {
    background: var(--panel); padding: 12px 14px;
  }
  .panel-title {
    font-size: 10px; letter-spacing: 2px; color: var(--dim);
    text-transform: uppercase; margin-bottom: 8px;
  }
  .val { color: var(--cyan); }
  .ok  { color: var(--green); }
  .warn{ color: var(--yellow); }
  .err { color: var(--red); }
  .row { display: flex; justify-content: space-between; margin-bottom: 4px; gap: 8px; }
  .row span:first-child { color: var(--dim); flex-shrink: 0; }

  #log {
    background: var(--bg); border-top: 1px solid var(--border);
    height: 220px; overflow-y: auto;
    font-size: 12px; line-height: 1.6;
    display: flex; flex-direction: column;
  }
  #log-inner { padding: 8px 14px; flex: 1; }
  .log-line { color: var(--dim); }
  .log-line .ts { color: #334; margin-right: 6px; }
  .log-line .ev { color: var(--cyan); margin-right: 6px; }
  .log-line.inject .ev { color: var(--yellow); }
  .log-line.error .ev  { color: var(--red); }

  .inject-bar {
    display: flex; gap: 8px; padding: 10px 14px;
    border-top: 1px solid var(--border); background: var(--panel);
  }
  #inject-input {
    flex: 1; background: var(--bg); color: var(--text);
    border: 1px solid var(--border); border-radius: 4px;
    padding: 6px 10px; font-family: var(--mono); font-size: 13px;
    outline: none;
  }
  #inject-input:focus { border-color: var(--cyan); }
  button {
    background: transparent; border: 1px solid var(--green);
    color: var(--green); border-radius: 4px; padding: 6px 14px;
    font-family: var(--mono); font-size: 12px; cursor: pointer;
    letter-spacing: 1px; transition: background 0.15s;
  }
  button:active { background: rgba(0,255,136,0.1); }
  #inject-type {
    background: var(--bg); color: var(--text);
    border: 1px solid var(--border); border-radius: 4px;
    padding: 6px 8px; font-family: var(--mono); font-size: 12px;
  }
</style>
</head>
<body>
<header>
  <h1>◈ MUNIN CONSOLE</h1>
  <div style="display:flex;align-items:center;gap:8px">
    <span id="ts" style="color:var(--dim);font-size:11px"></span>
    <div id="conn-dot"></div>
  </div>
</header>

<div class="grid">
  <div class="panel">
    <div class="panel-title">Repo</div>
    <div class="row"><span>Branch</span><span class="val" id="r-branch">—</span></div>
    <div class="row"><span>Tip</span><span class="val" id="r-tip" style="font-size:11px;text-align:right;max-width:60%">—</span></div>
    <div class="row"><span>Unpushed</span><span id="r-unpushed">—</span></div>
    <div class="row"><span>Dirty</span><span id="r-dirty">—</span></div>
  </div>
  <div class="panel">
    <div class="panel-title">Gateway</div>
    <div class="row"><span>Status</span><span id="gw-status">—</span></div>
    <div class="row"><span>URL</span><span class="val" id="gw-url" style="font-size:11px">—</span></div>
    <div class="row"><span>Write-Mode</span><span class="ok" id="write-mode">—</span></div>
    <div class="row"><span>Focus</span><span class="val" id="focus" style="font-size:11px;text-align:right;max-width:60%">—</span></div>
  </div>
</div>

<div id="log"><div id="log-inner"></div></div>

<div class="inject-bar">
  <select id="inject-type">
    <option value="inject">inject</option>
    <option value="broadcast">broadcast</option>
    <option value="task">task</option>
    <option value="ping">ping</option>
  </select>
  <input id="inject-input" type="text" placeholder='Befehl oder JSON-Payload...' autocomplete="off" autocorrect="off" spellcheck="false">
  <button onclick="sendInject()">▶ SEND</button>
</div>

<script>
const $ = id => document.getElementById(id);
let evtSrc = null;

function log(ev, msg, cls='') {
  const d = new Date().toTimeString().slice(0,8);
  const line = document.createElement('div');
  line.className = 'log-line ' + cls;
  line.innerHTML = `<span class="ts">${d}</span><span class="ev">[${ev}]</span>${escHtml(msg)}`;
  $('log-inner').appendChild(line);
  $('log').scrollTop = $('log').scrollHeight;
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function updateTs() {
  $('ts').textContent = new Date().toTimeString().slice(0,8);
}
setInterval(updateTs, 1000);
updateTs();

function connect() {
  if (evtSrc) evtSrc.close();
  evtSrc = new EventSource('/stream');
  $('conn-dot').className = '';

  evtSrc.onopen = () => {
    $('conn-dot').className = 'live';
    log('SSE', 'Verbunden — Live-Stream aktiv');
    fetchStatus();
  };

  evtSrc.onerror = () => {
    $('conn-dot').className = 'err';
    log('SSE', 'Verbindung unterbrochen — reconnect in 5s', 'error');
    setTimeout(connect, 5000);
  };

  evtSrc.addEventListener('repo-update', e => {
    const d = JSON.parse(e.data);
    applyRepo(d.repo);
    log('repo-update', `branch=${d.repo.branch} tip=${d.repo.tip}`);
  });

  evtSrc.addEventListener('munin-status', e => {
    const d = JSON.parse(e.data);
    log('munin-status', JSON.stringify(d.status?.message || d.status));
  });

  evtSrc.addEventListener('inject', e => {
    const d = JSON.parse(e.data);
    log('inject', JSON.stringify(d), 'inject');
  });

  evtSrc.addEventListener('heartbeat', e => {
    $('conn-dot').className = 'live';
  });
}

function applyRepo(repo) {
  if (!repo) return;
  $('r-branch').textContent = repo.branch || '—';
  $('r-tip').textContent = repo.tip || '—';
  const up = repo.unpushed || 0;
  $('r-unpushed').textContent = up;
  $('r-unpushed').className = up > 0 ? 'warn' : 'ok';
  $('r-dirty').textContent = repo.dirty ? 'ja' : 'nein';
  $('r-dirty').className = repo.dirty ? 'warn' : 'ok';
}

function fetchStatus() {
  fetch('/status').then(r => r.json()).then(d => {
    applyRepo(d.repo);
    $('gw-status').textContent = d.gateway?.ok ? 'online' : 'offline';
    $('gw-status').className   = d.gateway?.ok ? 'ok' : 'err';
    $('gw-url').textContent    = d.gateway?.url || '—';
    $('write-mode').textContent = d.write_mode || '—';
    const f = d.focus || {};
    $('focus').textContent = f.goal ? f.goal.slice(0,40) : '—';
  }).catch(() => {});
}

function sendInject() {
  const type    = $('inject-type').value;
  const payload = $('inject-input').value.trim();
  if (!payload) return;

  fetch('/inject', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({type, payload}),
  }).then(r => r.json()).then(d => {
    log('inject', `→ ${JSON.stringify(d)}`, 'inject');
    $('inject-input').value = '';
  }).catch(e => log('inject', 'Fehler: ' + e, 'error'));
}

$('inject-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendInject();
});

connect();
setInterval(fetchStatus, 30000);
</script>
</body>
</html>
"""


# ── HTTP-Handler ──────────────────────────────────────────────────────────────

def _check_auth(handler: "ConsoleHandler") -> bool:
    """Prüft Console-Zugriffsschutz wenn HM_CONSOLE_SECRET gesetzt."""
    if not CONSOLE_SECRET:
        return True
    auth = handler.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if token == CONSOLE_SECRET:
        return True
    handler.send_response(401)
    handler.send_header("Content-Type", "application/json")
    handler.end_headers()
    handler.wfile.write(b'{"error":"unauthorized"}')
    return False


class ConsoleHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Unterdrücke Standard-HTTP-Log

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/console":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(CONSOLE_HTML.encode())

        elif path == "/stream":
            self._sse_stream()

        elif path == "/status":
            if not _check_auth(self):
                return
            self._json(get_console_status())

        elif path == "/health":
            self._json({"ok": True, "ts": _now_iso()})

        elif path == "/log":
            if not _check_auth(self):
                return
            if LOG_FILE.exists():
                self._json(json.loads(LOG_FILE.read_text()))
            else:
                self._json([])

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path    = self.path.split("?")[0]
        length  = int(self.headers.get("Content-Length", 0))
        body    = self.rfile.read(length)

        try:
            data = json.loads(body) if body else {}
        except Exception:
            self._json({"error": "invalid JSON"}, 400)
            return

        if path == "/inject":
            if not _check_auth(self):
                return
            self._handle_inject(data)

        elif path == "/gateway":
            if not _check_auth(self):
                return
            result = _gateway_post("/tasks", data)
            self._json(result or {"error": "gateway not reachable"})

        else:
            self.send_response(404)
            self.end_headers()

    def _handle_inject(self, data: dict) -> None:
        """Verarbeitet eine direkte Injektion und broadcastet sie."""
        inject_type = data.get("type", "inject")
        payload     = data.get("payload", "")

        result: dict = {"type": inject_type, "payload": payload, "ts": _now_iso()}

        if inject_type == "task":
            # Payload als Task-Type interpretieren: "echo:hello" → type=echo, payload=hello
            parts = str(payload).split(":", 1)
            task_type    = parts[0].strip()
            task_payload = parts[1].strip() if len(parts) > 1 else ""
            gw = _gateway_post("/tasks", {"task_type": task_type, "payload": task_payload})
            result["gateway"] = gw

        elif inject_type == "broadcast":
            # In munin-link-status.json schreiben
            try:
                repo = get_repo_status()
                status = {
                    "ts": _now_iso(), "message": payload, "repo": repo,
                    "source": "hardware-console",
                }
                STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
                STATUS_FILE.write_text(json.dumps(status, indent=2) + "\n")
                result["written"] = str(STATUS_FILE.relative_to(REPO_ROOT))
            except Exception as e:
                result["error"] = str(e)

        elif inject_type == "ping":
            result["pong"] = _now_iso()

        # SSE-Broadcast an alle verbundenen Clients
        broadcast("inject", result)
        self._json(result)

    def _sse_stream(self) -> None:
        """Öffnet einen SSE-Stream für diesen Client."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q: queue.Queue = queue.Queue(maxsize=100)
        with _clients_lock:
            _clients.append(q)

        # Initialer Status-Push
        try:
            status = get_console_status()
            init_msg = f"event: init\ndata: {json.dumps(status)}\n\n"
            self.wfile.write(init_msg.encode())
            self.wfile.flush()
        except Exception:
            pass

        try:
            while True:
                try:
                    msg = q.get(timeout=20)
                    self.wfile.write(msg.encode())
                    self.wfile.flush()
                except queue.Empty:
                    # Heartbeat senden um Verbindung aufrechtzuerhalten
                    hb = f"event: heartbeat\ndata: {json.dumps({'ts': _now_iso()})}\n\n"
                    self.wfile.write(hb.encode())
                    self.wfile.flush()
        except Exception:
            pass
        finally:
            with _clients_lock:
                if q in _clients:
                    _clients.remove(q)

    def _json(self, data: dict | list, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="MUNIN Hardware Console")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("HM_CONSOLE_PORT", "7799")))
    parser.add_argument("--bind", default=os.environ.get("HM_CONSOLE_BIND", "0.0.0.0"))
    parser.add_argument("--watch-interval", type=int, default=10,
                        help="Repo-Poll-Intervall in Sekunden (Standard: 10)")
    args = parser.parse_args()

    # Hintergrund-Watcher starten
    for target, kwargs in [
        (_watch_repo,        {"interval": args.watch_interval}),
        (_watch_status_file, {"interval": 5}),
    ]:
        t = threading.Thread(target=target, kwargs=kwargs, daemon=True)
        t.start()

    server = HTTPServer((args.bind, args.port), ConsoleHandler)

    # LAN-IP für iPhone ermitteln
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        lan_ip = args.bind

    print(f"\n\033[1m\033[96m◈ MUNIN Hardware Console\033[0m")
    print(f"  Lokal   : \033[92mhttp://localhost:{args.port}\033[0m")
    print(f"  iPhone  : \033[93mhttp://{lan_ip}:{args.port}\033[0m")
    if CONSOLE_SECRET:
        print(f"  Auth    : \033[93mHM_CONSOLE_SECRET gesetzt (Bearer-Token)\033[0m")
    else:
        print(f"  Auth    : \033[91m⚠ Kein HM_CONSOLE_SECRET — öffentlich erreichbar\033[0m")
    if OWNER_TOKEN:
        print(f"  Gateway : \033[92m{GATEWAY_URL} (Token gesetzt)\033[0m")
    else:
        print(f"  Gateway : \033[91m⚠ HM_OWNER_TOKEN fehlt — Gateway-Befehle deaktiviert\033[0m")
    print(f"\n  \033[2mStrg+C zum Beenden\033[0m\n")

    broadcast("startup", {"message": "Hardware Console gestartet", "url": f"http://{lan_ip}:{args.port}"})

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\033[2mConsole beendet.\033[0m")


if __name__ == "__main__":
    main()
