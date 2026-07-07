#!/usr/bin/env python3
"""
Token-protected local remote-access gateway for sys/os mirror artifacts.

The gateway provides read-only access to status, manifests, validation reports,
and mirror archives. It intentionally does not expose shell execution.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import hmac
import http.server
import json
import os
import pathlib
import secrets
import socketserver
import sys
from urllib.parse import urlparse


SCHEMA_VERSION = "local_usr.sys.remote_access.v1"
ROOT = pathlib.Path(__file__).resolve().parents[3]
SYS_ROOT = ROOT / "local_usr" / "sys"
CONFIG_PATH = SYS_ROOT / "etc" / "remote_access.config.json"
VALIDATION_PATH = SYS_ROOT / "var" / "run" / "remote_access.validation.json"
EVENTS_PATH = SYS_ROOT / "var" / "log" / "remote_access.events.jsonl"
MIRROR_STATE = SYS_ROOT / "var" / "lib" / "sys_os_mirror"


ROUTES = {
    "/health": "local health status",
    "/manifest": "sys manifest",
    "/mirror/manifest": "latest mirror manifest",
    "/mirror/validation": "mirror validation",
    "/remote/validation": "remote access validation",
    "/archive/latest": "latest mirror archive download",
}


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def stable_json(value) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest_json(value) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload.setdefault("written_at_utc", utc_now())
    payload["content_sha256"] = digest_json({k: v for k, v in payload.items() if k != "content_sha256"})
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        return {"_read_error": str(exc)}


def append_event(event: dict) -> None:
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("captured_at_utc", utc_now())
    payload["event_sha256"] = digest_json(payload)
    with EVENTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def init_config() -> dict:
    if CONFIG_PATH.exists():
        return read_json(CONFIG_PATH)
    token = secrets.token_urlsafe(32)
    config = {
        "schema_version": SCHEMA_VERSION,
        "bind": "127.0.0.1",
        "port": 8765,
        "token_sha256": token_hash(token),
        "token_file": str(SYS_ROOT / "etc" / "remote_access.token"),
        "read_only": True,
        "shell_execution_enabled": False,
        "routes": ROUTES,
        "startup_command": f"{sys.executable} local_usr/sys/bin/remote_access_gateway.py serve",
    }
    write_json(CONFIG_PATH, config)
    token_path = pathlib.Path(config["token_file"])
    token_path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(token_path, 0o600)
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    append_event({"event_type": "remote_access_initialized", "bind": config["bind"], "port": config["port"]})
    return config


def latest_archive() -> pathlib.Path | None:
    archive_dir = MIRROR_STATE / "archives"
    if not archive_dir.exists():
        return None
    archives = sorted(archive_dir.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime_ns)
    return archives[-1] if archives else None


def validate() -> dict:
    config = read_json(CONFIG_PATH)
    errors: list[str] = []
    warnings: list[str] = []
    if not config:
        errors.append(f"missing config: {CONFIG_PATH}")
    token_file = pathlib.Path(config.get("token_file", "")) if config else pathlib.Path()
    if not token_file.exists():
        errors.append(f"missing token file: {token_file}")
    else:
        token = token_file.read_text(encoding="utf-8").strip()
        if token_hash(token) != config.get("token_sha256"):
            errors.append("token hash mismatch")
    if config.get("shell_execution_enabled") is not False:
        errors.append("shell execution must remain disabled")
    if not (SYS_ROOT / "etc" / "sys_manifest.json").exists():
        errors.append("sys manifest missing")
    if not (MIRROR_STATE / "manifest.json").exists():
        warnings.append("mirror manifest missing; run sys_os_mirror.py mirror")
    if latest_archive() is None:
        warnings.append("mirror archive missing; run sys_os_mirror.py mirror")
    result = {
        "schema_version": SCHEMA_VERSION,
        "ok": not errors,
        "validated_at_utc": utc_now(),
        "config_path": str(CONFIG_PATH),
        "bind": config.get("bind"),
        "port": config.get("port"),
        "routes": ROUTES,
        "latest_archive": str(latest_archive()) if latest_archive() else None,
        "errors": errors,
        "warnings": warnings,
    }
    write_json(VALIDATION_PATH, result)
    append_event({"event_type": "remote_access_validated", "ok": result["ok"], "errors": errors, "warnings": warnings})
    return result


class GatewayHandler(http.server.BaseHTTPRequestHandler):
    server_version = "LocalUsrSysRemoteAccess/1.0"

    def log_message(self, fmt: str, *args) -> None:
        append_event({"event_type": "http_request", "client": self.client_address[0], "message": fmt % args})

    def _authorized(self) -> bool:
        config = self.server.config  # type: ignore[attr-defined]
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        provided = auth.removeprefix("Bearer ").strip()
        expected = config.get("token_sha256", "")
        return hmac.compare_digest(token_hash(provided), expected)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: pathlib.Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self._send_json(404, {"ok": False, "error": "file not found"})
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(200, {"ok": True, "schema_version": SCHEMA_VERSION, "time_utc": utc_now(), "routes": ROUTES})
            return
        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "missing or invalid bearer token"})
            return
        if path == "/manifest":
            self._send_json(200, read_json(SYS_ROOT / "etc" / "sys_manifest.json"))
        elif path == "/mirror/manifest":
            self._send_json(200, read_json(MIRROR_STATE / "manifest.json"))
        elif path == "/mirror/validation":
            self._send_json(200, read_json(SYS_ROOT / "var" / "run" / "sys_os_mirror.validation.json"))
        elif path == "/remote/validation":
            self._send_json(200, validate())
        elif path == "/archive/latest":
            archive = latest_archive()
            if archive is None:
                self._send_json(404, {"ok": False, "error": "no archive available"})
            else:
                self._send_file(archive, "application/gzip")
        else:
            self._send_json(404, {"ok": False, "error": "unknown route", "routes": ROUTES})


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def serve() -> int:
    config = init_config()
    result = validate()
    if not result["ok"]:
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 2
    bind = config.get("bind", "127.0.0.1")
    port = int(config.get("port", 8765))
    with ReusableTCPServer((bind, port), GatewayHandler) as httpd:
        httpd.config = config  # type: ignore[attr-defined]
        append_event({"event_type": "remote_access_started", "bind": bind, "port": port})
        print(json.dumps({"ok": True, "bind": bind, "port": port, "routes": ROUTES}, ensure_ascii=True, indent=2), flush=True)
        httpd.serve_forever()
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a read-only local remote-access gateway.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("validate")
    sub.add_parser("status")
    sub.add_parser("serve")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.command == "init":
        print(json.dumps(init_config(), ensure_ascii=True, indent=2))
        return 0
    if args.command == "validate":
        result = validate()
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0 if result["ok"] else 2
    if args.command == "status":
        print(json.dumps({"config": read_json(CONFIG_PATH), "validation": read_json(VALIDATION_PATH)}, ensure_ascii=True, indent=2))
        return 0
    if args.command == "serve":
        return serve()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
