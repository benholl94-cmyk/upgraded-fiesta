#!/usr/bin/env python3
"""
Local system app chat bus.

Provides an internal, token-protected chat/event channel for local apps and
system components. It is not a WhatsApp client and does not connect to Meta
or third-party messaging networks.
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
import sqlite3
import sys
import time
from typing import Any
from urllib.parse import parse_qs, urlparse


SCHEMA_VERSION = "local_usr.sys.system_app_chat.v1"
ROOT = pathlib.Path(__file__).resolve().parents[3]
SYS_ROOT = ROOT / "local_usr" / "sys"
STATE_DIR = SYS_ROOT / "var" / "lib" / "system_app_chat"
DB_PATH = STATE_DIR / "chat.sqlite3"
CONFIG_PATH = SYS_ROOT / "etc" / "system_app_chat.config.json"
ADMIN_TOKEN_PATH = SYS_ROOT / "etc" / "system_app_chat.admin.token"
APP_TOKEN_DIR = SYS_ROOT / "etc" / "app_tokens"
VALIDATION_PATH = SYS_ROOT / "var" / "run" / "system_app_chat.validation.json"
EVENTS_PATH = SYS_ROOT / "var" / "log" / "system_app_chat.events.jsonl"
CHANNEL_DESCRIPTOR = SYS_ROOT / "etc" / "channels" / "system_app_chat.channel.json"

DEFAULT_ROUTES = {
    "/health": "public health check",
    "/regulation": "local summary of WhatsApp/DMA interoperability boundaries",
    "/apps": "admin: list registered apps",
    "/apps/heartbeat": "app: update heartbeat",
    "/messages": "app: post or poll channel messages",
    "/metrics": "admin: message and app counts",
}

MESSAGE_KINDS = {"text", "event", "metric", "command", "status", "audit"}
DEFAULT_CHANNELS = {"system", "ops", "apps", "progress", "optimization", "audit"}


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest_json(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload.setdefault("written_at_utc", utc_now())
    payload["content_sha256"] = digest_json({k: v for k, v in payload.items() if k != "content_sha256"})
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        return {"_read_error": str(exc)}


def append_event(event: dict[str, Any]) -> None:
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("captured_at_utc", utc_now())
    payload["event_sha256"] = digest_json(payload)
    with EVENTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")


def ensure_private_file(path: pathlib.Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def db_connect() -> sqlite3.Connection:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS apps (
              app_id TEXT PRIMARY KEY,
              display_name TEXT NOT NULL,
              token_sha256 TEXT NOT NULL,
              scopes TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at_utc TEXT NOT NULL,
              last_seen_at_utc TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
              message_id INTEGER PRIMARY KEY AUTOINCREMENT,
              channel TEXT NOT NULL,
              sender_app_id TEXT NOT NULL,
              recipient_app_id TEXT,
              kind TEXT NOT NULL,
              body TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              created_at_utc TEXT NOT NULL,
              body_sha256 TEXT NOT NULL,
              FOREIGN KEY(sender_app_id) REFERENCES apps(app_id)
            );
            CREATE INDEX IF NOT EXISTS idx_messages_channel_id
              ON messages(channel, message_id);
            CREATE INDEX IF NOT EXISTS idx_messages_recipient_id
              ON messages(recipient_app_id, message_id);
            CREATE TABLE IF NOT EXISTS app_offsets (
              app_id TEXT NOT NULL,
              channel TEXT NOT NULL,
              last_message_id INTEGER NOT NULL DEFAULT 0,
              updated_at_utc TEXT NOT NULL,
              PRIMARY KEY(app_id, channel),
              FOREIGN KEY(app_id) REFERENCES apps(app_id)
            );
            CREATE TABLE IF NOT EXISTS audit_log (
              audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
              actor TEXT NOT NULL,
              action TEXT NOT NULL,
              detail_json TEXT NOT NULL,
              created_at_utc TEXT NOT NULL
            );
            """
        )


def init_config() -> dict[str, Any]:
    SYS_ROOT.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    APP_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    init_db()

    if CONFIG_PATH.exists():
        config = read_json(CONFIG_PATH)
    else:
        admin_token = secrets.token_urlsafe(32)
        ADMIN_TOKEN_PATH.write_text(admin_token + "\n", encoding="utf-8")
        ensure_private_file(ADMIN_TOKEN_PATH)
        config = {
            "schema_version": SCHEMA_VERSION,
            "bind": "127.0.0.1",
            "port": 8787,
            "db_path": str(DB_PATH),
            "admin_token_sha256": token_hash(admin_token),
            "admin_token_file": str(ADMIN_TOKEN_PATH),
            "routes": DEFAULT_ROUTES,
            "default_channels": sorted(DEFAULT_CHANNELS),
            "network_required": False,
            "whatsapp_network_client": False,
            "shell_execution_enabled": False,
            "startup_command": f"{sys.executable} local_usr/sys/bin/system_app_chat.py serve",
        }
        write_json(CONFIG_PATH, config)
        ensure_private_file(CONFIG_PATH)

    write_json(
        CHANNEL_DESCRIPTOR,
        {
            "schema_version": "local_usr.sys.channel.v1",
            "channel_id": "system_app_chat",
            "purpose": "Token-protected internal system/app chat and event bus",
            "source": "local apps via CLI or HTTP",
            "sink": "local_usr/sys/var/lib/system_app_chat/chat.sqlite3",
            "validation": "local_usr/sys/var/run/system_app_chat.validation.json",
            "status": "initialized",
        },
    )
    append_event({"event_type": "system_app_chat_initialized", "db_path": str(DB_PATH)})
    return read_json(CONFIG_PATH)


def audit(actor: str, action: str, detail: dict[str, Any]) -> None:
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO audit_log(actor, action, detail_json, created_at_utc) VALUES (?, ?, ?, ?)",
            (actor, action, stable_json(detail), utc_now()),
        )


def parse_scopes(scopes: str | list[str]) -> set[str]:
    if isinstance(scopes, str):
        items = [item.strip() for item in scopes.replace(";", ",").split(",")]
    else:
        items = [str(item).strip() for item in scopes]
    return {item for item in items if item}


def app_record(app_id: str) -> dict[str, Any] | None:
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM apps WHERE app_id = ?", (app_id,)).fetchone()
    return dict(row) if row else None


def require_valid_app(app_id: str, token: str, required_scope: str) -> dict[str, Any]:
    record = app_record(app_id)
    if not record or not record.get("enabled"):
        raise PermissionError("unknown or disabled app")
    if not hmac.compare_digest(token_hash(token), record["token_sha256"]):
        raise PermissionError("invalid app token")
    scopes = parse_scopes(record["scopes"])
    if required_scope not in scopes and "admin" not in scopes:
        raise PermissionError(f"missing scope: {required_scope}")
    with db_connect() as conn:
        conn.execute("UPDATE apps SET last_seen_at_utc = ? WHERE app_id = ?", (utc_now(), app_id))
    return record


def require_admin(token: str) -> None:
    config = init_config()
    expected = config.get("admin_token_sha256", "")
    if not expected or not hmac.compare_digest(token_hash(token), expected):
        raise PermissionError("invalid admin token")


def register_app(app_id: str, display_name: str, scopes: str, rotate: bool = False) -> dict[str, Any]:
    init_config()
    clean_id = app_id.strip()
    if not clean_id or any(char.isspace() for char in clean_id) or "/" in clean_id:
        raise ValueError("app_id must be non-empty and contain no whitespace or slash")
    scope_set = parse_scopes(scopes)
    allowed_scopes = {"send", "read", "heartbeat", "admin"}
    invalid = sorted(scope_set - allowed_scopes)
    if invalid:
        raise ValueError(f"invalid scopes: {', '.join(invalid)}")
    if not scope_set:
        raise ValueError("at least one scope required")

    existing = app_record(clean_id)
    if existing and not rotate:
        return {
            "ok": True,
            "created": False,
            "app_id": clean_id,
            "display_name": existing["display_name"],
            "scopes": sorted(parse_scopes(existing["scopes"])),
            "token_file": str(APP_TOKEN_DIR / f"{clean_id}.token"),
            "token_returned": False,
        }

    token = secrets.token_urlsafe(32)
    now = utc_now()
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO apps(app_id, display_name, token_sha256, scopes, enabled, created_at_utc)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(app_id) DO UPDATE SET
              display_name = excluded.display_name,
              token_sha256 = excluded.token_sha256,
              scopes = excluded.scopes,
              enabled = 1
            """,
            (clean_id, display_name.strip() or clean_id, token_hash(token), ",".join(sorted(scope_set)), now),
        )
    token_path = APP_TOKEN_DIR / f"{clean_id}.token"
    token_path.write_text(token + "\n", encoding="utf-8")
    ensure_private_file(token_path)
    audit("system", "app_registered", {"app_id": clean_id, "scopes": sorted(scope_set), "rotated": bool(existing)})
    append_event({"event_type": "app_registered", "app_id": clean_id, "rotated": bool(existing)})
    return {
        "ok": True,
        "created": existing is None,
        "app_id": clean_id,
        "display_name": display_name.strip() or clean_id,
        "scopes": sorted(scope_set),
        "token": token,
        "token_file": str(token_path),
        "token_returned": True,
    }


def validate_json_object(raw: str | None) -> str:
    if raw is None or raw == "":
        return "{}"
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("metadata must be a JSON object")
    return stable_json(value)


def post_message(
    app_id: str,
    token: str,
    channel: str,
    body: str,
    kind: str = "text",
    recipient_app_id: str | None = None,
    metadata_json: str | None = None,
) -> dict[str, Any]:
    init_config()
    require_valid_app(app_id, token, "send")
    clean_channel = channel.strip()
    if not clean_channel or "/" in clean_channel or any(char.isspace() for char in clean_channel):
        raise ValueError("channel must be non-empty and contain no whitespace or slash")
    if kind not in MESSAGE_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(sorted(MESSAGE_KINDS))}")
    if recipient_app_id and not app_record(recipient_app_id):
        raise ValueError(f"unknown recipient_app_id: {recipient_app_id}")
    clean_body = body.strip()
    if not clean_body:
        raise ValueError("body must not be empty")
    if len(clean_body.encode("utf-8")) > 128 * 1024:
        raise ValueError("body exceeds 128 KiB")
    metadata = validate_json_object(metadata_json)
    now = utc_now()
    with db_connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages(channel, sender_app_id, recipient_app_id, kind, body, metadata_json, created_at_utc, body_sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (clean_channel, app_id, recipient_app_id, kind, clean_body, metadata, now, hashlib.sha256(clean_body.encode()).hexdigest()),
        )
        message_id = int(cur.lastrowid)
    append_event({"event_type": "message_posted", "message_id": message_id, "channel": clean_channel, "sender_app_id": app_id})
    return {"ok": True, "message_id": message_id, "channel": clean_channel, "created_at_utc": now}


def message_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    return item


def poll_messages(app_id: str, token: str, channel: str, after: int | None, limit: int, update_offset: bool = True) -> dict[str, Any]:
    init_config()
    require_valid_app(app_id, token, "read")
    clean_channel = channel.strip()
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    with db_connect() as conn:
        if after is None:
            row = conn.execute(
                "SELECT last_message_id FROM app_offsets WHERE app_id = ? AND channel = ?",
                (app_id, clean_channel),
            ).fetchone()
            after = int(row["last_message_id"]) if row else 0
        rows = conn.execute(
            """
            SELECT * FROM messages
            WHERE channel = ?
              AND message_id > ?
              AND (recipient_app_id IS NULL OR recipient_app_id = ? OR sender_app_id = ?)
            ORDER BY message_id ASC
            LIMIT ?
            """,
            (clean_channel, after, app_id, app_id, limit),
        ).fetchall()
        messages = [message_to_dict(row) for row in rows]
        last_id = messages[-1]["message_id"] if messages else after
        if update_offset:
            conn.execute(
                """
                INSERT INTO app_offsets(app_id, channel, last_message_id, updated_at_utc)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(app_id, channel) DO UPDATE SET
                  last_message_id = excluded.last_message_id,
                  updated_at_utc = excluded.updated_at_utc
                """,
                (app_id, clean_channel, int(last_id), utc_now()),
            )
    return {"ok": True, "channel": clean_channel, "after": after, "last_message_id": int(last_id), "messages": messages}


def heartbeat(app_id: str, token: str, metadata_json: str | None = None) -> dict[str, Any]:
    require_valid_app(app_id, token, "heartbeat")
    metadata = json.loads(validate_json_object(metadata_json))
    audit(app_id, "heartbeat", metadata)
    return {"ok": True, "app_id": app_id, "seen_at_utc": utc_now()}


def list_apps() -> dict[str, Any]:
    init_config()
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT app_id, display_name, scopes, enabled, created_at_utc, last_seen_at_utc FROM apps ORDER BY app_id"
        ).fetchall()
    apps = []
    for row in rows:
        item = dict(row)
        item["scopes"] = sorted(parse_scopes(item["scopes"]))
        apps.append(item)
    return {"ok": True, "apps": apps}


def metrics() -> dict[str, Any]:
    init_config()
    with db_connect() as conn:
        app_count = conn.execute("SELECT COUNT(*) AS c FROM apps WHERE enabled = 1").fetchone()["c"]
        message_count = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
        channel_rows = conn.execute("SELECT channel, COUNT(*) AS c, MAX(message_id) AS last_id FROM messages GROUP BY channel").fetchall()
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "time_utc": utc_now(),
        "enabled_app_count": int(app_count),
        "message_count": int(message_count),
        "channels": [dict(row) for row in channel_rows],
    }


def regulation_summary() -> dict[str, Any]:
    return {
        "ok": True,
        "source_scope": "official Meta/WhatsApp and EU DMA interoperability model",
        "software_boundary": {
            "is_whatsapp_client": False,
            "uses_whatsapp_private_protocol": False,
            "connects_to_meta_servers": False,
            "purpose": "internal app/system communication and operational optimization",
        },
        "constraints": [
            "WhatsApp third-party chats are optional for eligible European users.",
            "Interoperating providers must meet technical and security requirements and use equivalent end-to-end encryption.",
            "Public WhatsApp interoperability is not a generic local bot/API permission.",
            "This software therefore exposes only a local internal chat bus unless a lawful provider agreement and production keys are configured outside this module.",
        ],
    }


def validate() -> dict[str, Any]:
    init_config()
    errors: list[str] = []
    warnings: list[str] = []
    config = read_json(CONFIG_PATH)
    if not config:
        errors.append(f"missing config: {CONFIG_PATH}")
    if config.get("whatsapp_network_client") is not False:
        errors.append("whatsapp_network_client must remain false")
    if config.get("shell_execution_enabled") is not False:
        errors.append("shell execution must remain disabled")
    if not DB_PATH.exists():
        errors.append(f"missing database: {DB_PATH}")
    if not CHANNEL_DESCRIPTOR.exists():
        errors.append(f"missing channel descriptor: {CHANNEL_DESCRIPTOR}")
    try:
        with db_connect() as conn:
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
        required = {"apps", "messages", "app_offsets", "audit_log"}
        missing = sorted(required - tables)
        if missing:
            errors.append(f"missing db tables: {', '.join(missing)}")
    except sqlite3.Error as exc:
        errors.append(f"sqlite validation failed: {exc}")
    if not ADMIN_TOKEN_PATH.exists():
        warnings.append("admin token file missing; init will recreate only if config is absent")
    result = {
        "schema_version": SCHEMA_VERSION,
        "ok": not errors,
        "validated_at_utc": utc_now(),
        "root": str(ROOT),
        "db_path": str(DB_PATH),
        "config_path": str(CONFIG_PATH),
        "routes": DEFAULT_ROUTES,
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics() if not errors else {},
    }
    write_json(VALIDATION_PATH, result)
    append_event({"event_type": "system_app_chat_validated", "ok": result["ok"], "errors": errors, "warnings": warnings})
    return result


class ChatHandler(http.server.BaseHTTPRequestHandler):
    server_version = "LocalUsrSysAppChat/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        append_event({"event_type": "http_request", "client": self.client_address[0], "message": fmt % args})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 256 * 1024:
            raise ValueError("request body exceeds 256 KiB")
        if length == 0:
            return {}
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _bearer(self) -> str:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return ""
        return auth.removeprefix("Bearer ").strip()

    def _app_id(self) -> str:
        return self.headers.get("X-App-Id", "").strip()

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_error(self, exc: Exception) -> None:
        status = 403 if isinstance(exc, PermissionError) else 400
        self._send_json(status, {"ok": False, "error": str(exc)})

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/health":
                self._send_json(200, {"ok": True, "schema_version": SCHEMA_VERSION, "time_utc": utc_now(), "routes": DEFAULT_ROUTES})
                return
            if parsed.path == "/regulation":
                self._send_json(200, regulation_summary())
                return
            if parsed.path == "/apps":
                require_admin(self._bearer())
                self._send_json(200, list_apps())
                return
            if parsed.path == "/messages":
                channel = query.get("channel", ["system"])[0]
                after_raw = query.get("after", [None])[0]
                after = int(after_raw) if after_raw is not None else None
                limit = int(query.get("limit", ["50"])[0])
                self._send_json(200, poll_messages(self._app_id(), self._bearer(), channel, after, limit))
                return
            if parsed.path == "/metrics":
                require_admin(self._bearer())
                self._send_json(200, metrics())
                return
            self._send_json(404, {"ok": False, "error": "unknown route", "routes": DEFAULT_ROUTES})
        except Exception as exc:  # noqa: BLE001
            self._handle_error(exc)

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            body = self._read_json()
            if parsed.path == "/messages":
                self._send_json(
                    200,
                    post_message(
                        self._app_id(),
                        self._bearer(),
                        str(body.get("channel", "system")),
                        str(body.get("body", "")),
                        str(body.get("kind", "text")),
                        body.get("recipient_app_id"),
                        stable_json(body.get("metadata", {})),
                    ),
                )
                return
            if parsed.path == "/apps/heartbeat":
                self._send_json(200, heartbeat(self._app_id(), self._bearer(), stable_json(body.get("metadata", {}))))
                return
            self._send_json(404, {"ok": False, "error": "unknown route", "routes": DEFAULT_ROUTES})
        except Exception as exc:  # noqa: BLE001
            self._handle_error(exc)


class ReusableThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def serve() -> int:
    config = init_config()
    result = validate()
    if not result["ok"]:
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 2
    bind = str(config.get("bind", "127.0.0.1"))
    port = int(config.get("port", 8787))
    with ReusableThreadingTCPServer((bind, port), ChatHandler) as httpd:
        append_event({"event_type": "system_app_chat_started", "bind": bind, "port": port})
        print(json.dumps({"ok": True, "bind": bind, "port": port, "routes": DEFAULT_ROUTES}, ensure_ascii=True, indent=2), flush=True)
        httpd.serve_forever()
    return 0


def self_test() -> dict[str, Any]:
    init_config()
    app = register_app("system_app_chat_selftest", "System App Chat Self Test", "send,read,heartbeat", rotate=True)
    token = app["token"]
    heartbeat_result = heartbeat(app["app_id"], token, '{"source":"self-test"}')
    posted = post_message(app["app_id"], token, "system", "system_app_chat self-test message", "status", None, '{"source":"self-test"}')
    polled = poll_messages(app["app_id"], token, "system", int(posted["message_id"]) - 1, 10, update_offset=False)
    result = {
        "schema_version": SCHEMA_VERSION,
        "ok": bool(heartbeat_result["ok"] and posted["ok"] and polled["messages"]),
        "tested_at_utc": utc_now(),
        "registered_app": app["app_id"],
        "posted_message_id": posted["message_id"],
        "polled_count": len(polled["messages"]),
    }
    append_event({"event_type": "system_app_chat_self_test", "ok": result["ok"], "message_id": posted["message_id"]})
    return result


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2))


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local system/app chat bus.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("validate")
    sub.add_parser("self-test")
    sub.add_parser("serve")
    sub.add_parser("regulation")
    sub.add_parser("metrics")

    register = sub.add_parser("register")
    register.add_argument("--app-id", required=True)
    register.add_argument("--display-name", default="")
    register.add_argument("--scopes", default="send,read,heartbeat")
    register.add_argument("--rotate", action="store_true")

    post = sub.add_parser("post")
    post.add_argument("--app-id", required=True)
    post.add_argument("--token", required=True)
    post.add_argument("--channel", default="system")
    post.add_argument("--kind", default="text")
    post.add_argument("--to-app")
    post.add_argument("--metadata-json", default="{}")
    post.add_argument("body")

    poll = sub.add_parser("poll")
    poll.add_argument("--app-id", required=True)
    poll.add_argument("--token", required=True)
    poll.add_argument("--channel", default="system")
    poll.add_argument("--after", type=int)
    poll.add_argument("--limit", type=int, default=50)
    poll.add_argument("--no-offset", action="store_true")

    beat = sub.add_parser("heartbeat")
    beat.add_argument("--app-id", required=True)
    beat.add_argument("--token", required=True)
    beat.add_argument("--metadata-json", default="{}")

    apps = sub.add_parser("apps")
    apps.add_argument("--admin-token", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if args.command == "init":
            print_json(init_config())
            return 0
        if args.command == "validate":
            result = validate()
            print_json(result)
            return 0 if result["ok"] else 2
        if args.command == "self-test":
            result = self_test()
            print_json(result)
            return 0 if result["ok"] else 2
        if args.command == "serve":
            return serve()
        if args.command == "regulation":
            print_json(regulation_summary())
            return 0
        if args.command == "metrics":
            print_json(metrics())
            return 0
        if args.command == "register":
            print_json(register_app(args.app_id, args.display_name or args.app_id, args.scopes, args.rotate))
            return 0
        if args.command == "post":
            print_json(post_message(args.app_id, args.token, args.channel, args.body, args.kind, args.to_app, args.metadata_json))
            return 0
        if args.command == "poll":
            print_json(poll_messages(args.app_id, args.token, args.channel, args.after, args.limit, update_offset=not args.no_offset))
            return 0
        if args.command == "heartbeat":
            print_json(heartbeat(args.app_id, args.token, args.metadata_json))
            return 0
        if args.command == "apps":
            require_admin(args.admin_token)
            print_json(list_apps())
            return 0
    except Exception as exc:  # noqa: BLE001
        print_json({"ok": False, "error": str(exc)})
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
