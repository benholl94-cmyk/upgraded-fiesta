#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import socket

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "ashell_fullstack"
RUNS = ROOT / "runs"
DB = DATA / "state.sqlite3"


def init() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute("create table if not exists events(id integer primary key, ts real, path text, body text)")
        db.execute("create table if not exists kv(key text primary key, value text)")
        db.commit()


def free_port(host: str, port: int) -> int:
    while True:
        with socket() as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                port += 1


class Gateway(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def reply(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/health", "/ready"):
            self.reply(200, {"ok": True, "runtime": "a-shell-native", "db": str(DB)})
        elif self.path == "/state":
            with sqlite3.connect(DB) as db:
                rows = db.execute("select count(*) from events").fetchone()[0]
            self.reply(200, {"ok": True, "events": rows})
        else:
            self.reply(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        size = int(self.headers.get("content-length", "0") or "0")
        body = self.rfile.read(size).decode(errors="replace") if size else ""
        with sqlite3.connect(DB) as db:
            db.execute("insert into events(ts,path,body) values(?,?,?)", (time.time(), self.path, body))
            db.commit()
        self.reply(200, {"ok": True, "stored": True, "path": self.path})


def serve(server: ThreadingHTTPServer) -> None:
    server.serve_forever()


def main() -> int:
    init()
    host = "127.0.0.1"
    gateway_port = free_port(host, 8080)
    ui_port = free_port(host, 3000 if gateway_port != 3000 else 3001)

    gateway = ThreadingHTTPServer((host, gateway_port), Gateway)
    ui = ThreadingHTTPServer((host, ui_port), partial(SimpleHTTPRequestHandler, directory=str(ROOT / "ui")))
    threading.Thread(target=serve, args=(gateway,), daemon=True).start()
    threading.Thread(target=serve, args=(ui,), daemon=True).start()

    runtime = {
        "ok": True,
        "gateway_url": f"http://{host}:{gateway_port}",
        "ui_url": f"http://{host}:{ui_port}",
        "db": str(DB),
    }
    (RUNS / "ashell_fullstack_runtime.json").write_text(json.dumps(runtime, indent=2), encoding="utf-8")
    print(json.dumps(runtime, indent=2), flush=True)
    print("CTRL+C stops the a-Shell fullstack.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        gateway.shutdown()
        ui.shutdown()
        print("stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
