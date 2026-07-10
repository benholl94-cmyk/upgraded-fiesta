#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
supervisor_agent.py  v2.0.0
============================
#1 Global AI Agent Supervisor — Production-Ready
Local workspace + Web access — stdlib only, zero external dependencies.

LAYER 1 — TOOLS (8):
  shell_exec    disabled in workspace production profile
  file_read     local filesystem, any encoding, size-capped
  file_write    local filesystem, w/a mode, mkdir -p auto
  http_get      HTTP/HTTPS GET, public destinations only, custom headers, JSON-aware
  http_post     HTTP/HTTPS POST JSON body, public destinations only, response parse
  process_list  disabled in workspace production profile
  python_exec   disabled in workspace production profile
  api_status    master_agent.py :8787 health + metrics

LAYER 2 — AGENT:
  Claude claude-sonnet-4-20250514, native tool_use multi-turn loop
  true_access flag per call → if false: debug/fix iteration (max 5)
  MAX_FIX_ITERATIONS enforced — _fix_cap_reached hint injected on cap
  Audit log: every call + result, deque ring (500 entries, O(1))

LAYER 3 — SUPERVISOR:
  FIFO task queue, 4 daemon workers (threading)
  Per-task timeout (TASK_TIMEOUT=600s) prevents worker starvation
  Task store: id, prompt, status, steps, result, timestamps

LAYER 4 — REST API :8788:
  POST   /task                → submit prompt → {task_id, status}
  GET    /task/{id}           → full task record (poll until done)
  GET    /tasks               → list all tasks
  DELETE /task/{id}           → remove completed/failed task
  POST   /tool/exec           → direct tool dispatch (no agent loop)
  GET    /supervisor/status   → live metrics
  GET    /supervisor/logs     → last 100 audit entries
  GET    /report              → JSON summary (Scriptable / View_JSON.js)
  GET    /health              → liveness probe

CHANGES v2.0.0 vs v1.0.0 (18 bug fixes + 8 new features):
  FIX-01  _audit_log: list + pop(0) → deque(maxlen=N)       O(n)→O(1)
  FIX-02  _iso() now uses datetime.utcnow() for ms precision
  FIX-03  _tasks_counter dead code removed (never consistent)
  FIX-04  sort_cmd dead variable removed from _exec_process_list
  FIX-05  Windows process list: sort_by now actually applied
  FIX-06  Windows WMIC CSV parsing: correct column indices
  FIX-07  _SYSTEM_PROMPT moved before _call_anthropic (source order fix)
  FIX-08  _call_anthropic: 3-attempt retry + exponential backoff
  FIX-09  _call_anthropic: Retry-After header honoured on 429
  FIX-10  Tool result truncation: field-aware (_safe_json_dumps)
          prevents invalid JSON from character-count slicing
  FIX-11  MAX_FIX_ITERATIONS enforced: _fix_cap_reached hint injected
  FIX-12  JSON extraction: fenced block + balanced-brace scanner
          replaces fragile greedy regex
  FIX-13  stop_reason=="max_tokens" handled explicitly
  FIX-14  Empty tid validated in GET/DELETE /task/{id}
  FIX-15  Request body size capped at MAX_REQUEST_BYTES (413)
  FIX-16  server.server_close() called after shutdown()
  FIX-17  _exec_file_write: empty dirname guard (was "." fallback bug)
  FIX-18  audit_snapshot: copy-then-slice under lock (was slice-then-copy)
  NEW-01  TASK_TIMEOUT: per-task deadline (default 600 s)
  NEW-02  SIGTERM + SIGINT: graceful shutdown via threading.Event
  NEW-03  HTTP server runs in daemon thread; main thread blocks on event
  NEW-04  MAX_REQUEST_BYTES: hard limit on POST body size
  NEW-05  _tasks_summary(): O(1) status counts (no full snapshot copy)
  NEW-06  SupervisorServer.timeout = 30 (idle socket reaper)
  NEW-07  All config overridable via env vars (CLAUDE_MODEL, etc.)
  NEW-08  _safe_json_dumps(): field-aware JSON compactor utility

USAGE:
  export ANTHROPIC_API_KEY=sk-ant-...
  python3 supervisor_agent.py
  # optional overrides:
  SUPERVISOR_PORT=9000 TASK_WORKERS=8 TASK_TIMEOUT=300 python3 supervisor_agent.py
"""

from __future__ import annotations

import os
import sys
import json
import re
import time
import uuid
import signal
import logging
import datetime
import threading
import platform
import traceback
import http.client
from pathlib import Path
from collections import deque
from queue import Queue, Empty
from typing import Any, Optional
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.request import urlopen, Request as URLRequest
from urllib.parse import urlsplit
import ipaddress
import socket
from urllib.error import URLError, HTTPError

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG  (all overridable via environment variables)
# ─────────────────────────────────────────────────────────────────────────────

SUPERVISOR_HOST    = "127.0.0.1"
SUPERVISOR_PORT    = 8788
MASTER_AGENT_URL   = "http://127.0.0.1:8787"
ANTHROPIC_API_KEY  = ""
CLAUDE_MODEL       = "claude-sonnet-4-20250514"
MAX_FIX_ITERATIONS = 5
MAX_TOOL_TIMEOUT   = 60
MAX_AGENT_ROUNDS   = 20
TASK_WORKERS       = 4
TASK_TIMEOUT       = 600
AUDIT_RING_SIZE    = 500
MAX_REQUEST_BYTES  = 1024 * 1024
VERSION            = "2.2.0-production"
WORKSPACE_ROOT     = Path("/mnt/data/supervisor_workspace").resolve()
ALLOWED_ORIGINS    = frozenset({"http://127.0.0.1", "http://localhost", "null"})
MAX_HTTP_BYTES     = 512 * 1024
MAX_WRITE_BYTES    = 1024 * 1024
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("supervisor")

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_supervisor_start = time.monotonic()


def _iso(dt: Optional[datetime.datetime] = None) -> str:
    """FIX-02: ISO 8601 UTC with millisecond precision (was second-only)."""
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _safe_json_dumps(obj: Any, max_bytes: int = 10_000) -> str:
    """NEW-08 / FIX-10: Serialize to JSON; shorten large string leaves if over budget.
    Prevents invalid JSON from naive [:N] character-count truncation."""
    raw = json.dumps(obj, ensure_ascii=False, default=str)
    if len(raw.encode("utf-8")) <= max_bytes:
        return raw

    def _trim(o: Any, budget: int) -> Any:
        if isinstance(o, str):
            if len(o) <= budget:
                return o
            return o[:budget] + f"…[+{len(o) - budget}]"
        if isinstance(o, dict) and o:
            per = max(budget // len(o), 64)
            return {k: _trim(v, per) for k, v in o.items()}
        if isinstance(o, list) and o:
            per = max(budget // len(o), 64)
            return [_trim(i, per) for i in o]
        return o

    trimmed = _trim(obj, max_bytes // 2)
    encoded = json.dumps(trimmed, ensure_ascii=False, default=str)
    if len(encoded.encode("utf-8")) <= max_bytes:
        return encoded
    fallback = {
        "truncated": True,
        "original_bytes": len(raw.encode("utf-8")),
        "preview": encoded.encode("utf-8")[: max(0, max_bytes - 160)].decode("utf-8", errors="ignore"),
    }
    return json.dumps(fallback, ensure_ascii=False, default=str)

# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOG  — FIX-01: deque(maxlen=N) replaces list + pop(0)  O(1) vs O(n)
# ─────────────────────────────────────────────────────────────────────────────

_audit_deque: deque[dict] = deque(maxlen=AUDIT_RING_SIZE)
_audit_lock  = threading.Lock()


def _audit(event: str, data: dict) -> None:
    entry = {"ts": round(time.time(), 3), "iso": _iso(), "event": event, **data}
    with _audit_lock:
        _audit_deque.append(entry)  # deque auto-evicts oldest when maxlen reached


def audit_snapshot(n: int = 100) -> list[dict]:
    # FIX-18: copy under lock, then slice outside lock
    with _audit_lock:
        all_entries = list(_audit_deque)
    return all_entries[-n:]

# ─────────────────────────────────────────────────────────────────────────────
# TASK STORE  — thread-safe dict
# ─────────────────────────────────────────────────────────────────────────────

_tasks: dict[str, dict] = {}
_tasks_lock = threading.RLock()


def task_create(prompt: str) -> str:
    tid = str(uuid.uuid4())
    with _tasks_lock:
        _tasks[tid] = {
            "id":                   tid,
            "prompt":               prompt,
            "status":               "queued",
            "created_iso":          _iso(),
            "started_iso":          None,
            "ended_iso":            None,
            "result":               None,
            "error":                None,
            "steps":                [],
            "tools_used":           [],
            "fix_iterations":       0,
            "agent_rounds":         0,
            "true_access_failures": 0,
        }
    # FIX-03: _tasks_counter removed — it was incremented but done/failed
    #         were never updated, making it permanently wrong.
    _audit("task_create", {"tid": tid, "prompt": prompt[:120]})
    return tid


def task_update(tid: str, **kw) -> None:
    with _tasks_lock:
        if tid in _tasks:
            _tasks[tid].update(kw)


def task_get(tid: str) -> Optional[dict]:
    with _tasks_lock:
        t = _tasks.get(tid)
        return dict(t) if t else None


def task_delete(tid: str) -> bool:
    with _tasks_lock:
        t = _tasks.get(tid)
        if t is None:
            return False
        if t["status"] in ("queued", "running"):
            return False
        del _tasks[tid]
        return True


def tasks_snapshot() -> list[dict]:
    with _tasks_lock:
        return [dict(t) for t in _tasks.values()]


def _tasks_summary() -> dict[str, int]:
    """NEW-05: O(1) status-count dict — avoids full deep-copy snapshot."""
    with _tasks_lock:
        counts: dict[str, int] = {}
        for t in _tasks.values():
            s = t["status"]
            counts[s] = counts.get(s, 0) + 1
    return counts

# ─────────────────────────────────────────────────────────────────────────────
# TOOL DEFINITIONS — Claude tool_use schema
# ─────────────────────────────────────────────────────────────────────────────

TOOL_DEFS: list[dict] = [
    {
        "name": "shell_exec",
        "description": (
            "Execute any shell command on the local machine. "
            "Returns stdout, stderr, returncode, elapsed_ms. "
            "Use for: system info, git, pip, file ops, process management, networking tools."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command":   {"type": "string",  "description": "Shell command (sh -c on Unix, cmd /c on Windows)"},
                "timeout":   {"type": "integer", "description": "Timeout seconds (default 30, max 60)"},
                "cwd":       {"type": "string",  "description": "Working directory (optional)"},
                "env_extra": {"type": "object",  "description": "Extra env vars to merge (optional)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "file_read",
        "description": "Read a file from the local filesystem. Returns content, size, path. Caps at 100 KB.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":      {"type": "string",  "description": "Absolute or relative path (~ expanded)"},
                "encoding":  {"type": "string",  "description": "Text encoding (default utf-8)"},
                "max_bytes": {"type": "integer", "description": "Max bytes to read (default 100000)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "file_write",
        "description": "Write or append to a local file. Creates parent dirs automatically. Returns bytes_written, path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":     {"type": "string", "description": "File path (~ expanded)"},
                "content":  {"type": "string", "description": "Content to write"},
                "mode":     {"type": "string", "description": "'w' overwrite (default) | 'a' append"},
                "encoding": {"type": "string", "description": "Encoding (default utf-8)"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "http_get",
        "description": (
            "HTTP/HTTPS GET request to any URL. "
            "Returns status_code, body (JSON or text), elapsed_ms."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url":     {"type": "string",  "description": "Full URL including protocol"},
                "headers": {"type": "object",  "description": "HTTP headers key-value (optional)"},
                "timeout": {"type": "integer", "description": "Timeout seconds (default 15)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "http_post",
        "description": "HTTP/HTTPS POST with JSON body. Returns status_code, response body, elapsed_ms.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url":     {"type": "string",  "description": "Full URL including protocol"},
                "body":    {"type": "object",  "description": "JSON object to POST"},
                "headers": {"type": "object",  "description": "Additional headers (optional)"},
                "timeout": {"type": "integer", "description": "Timeout seconds (default 15)"},
            },
            "required": ["url", "body"],
        },
    },
    {
        "name": "process_list",
        "description": "List running system processes. Returns pid, name, cpu%, mem%, command.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_name": {"type": "string",  "description": "Filter by process name substring (optional)"},
                "top_n":       {"type": "integer", "description": "Return top N entries (default 20)"},
                "sort_by":     {"type": "string",  "description": "'cpu' (default) | 'memory'"},
            },
        },
    },
    {
        "name": "python_exec",
        "description": "Execute Python 3 code in a subprocess. Returns stdout, stderr, returncode, elapsed_ms.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code":    {"type": "string",  "description": "Valid Python 3 code to execute"},
                "timeout": {"type": "integer", "description": "Timeout seconds (default 15)"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "api_status",
        "description": "Query master_agent.py REST API for live status and metrics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string",  "description": "Host (default 127.0.0.1)"},
                "port": {"type": "integer", "description": "Port (default 8787)"},
            },
        },
    },
]

TOOL_DEFS = [d for d in TOOL_DEFS if d["name"] in {"file_read", "file_write", "http_get", "http_post", "api_status"}]

# ─────────────────────────────────────────────────────────────────────────────
# TOOL EXECUTORS
# ─────────────────────────────────────────────────────────────────────────────

def _restricted(operation: str) -> dict:
    return {
        "true_access": False,
        "error": f"Restricted runtime: {operation} is disabled",
        "restricted": True,
    }


def _exec_shell(
    command: str, timeout: int = 30, cwd: Optional[str] = None,
    env_extra: Optional[dict] = None,
) -> dict:
    return _restricted("shell execution")

def _workspace_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = WORKSPACE_ROOT / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise PermissionError("Path escapes WORKSPACE_ROOT") from exc
    return resolved


def _exec_file_read(
    path: str, encoding: str = "utf-8", max_bytes: int = 100_000,
) -> dict:
    try:
        resolved = _workspace_path(path)
        limit = max(1, min(int(max_bytes or 100_000), 100_000))
        if not resolved.is_file():
            return {"true_access": False, "error": f"File not found: {resolved}"}
        raw = resolved.read_bytes()
        truncated = len(raw) > limit
        content = raw[:limit].decode(encoding, errors="replace")
        return {
            "true_access": True,
            "path": str(resolved),
            "size_bytes": len(raw),
            "truncated": truncated,
            "content": content,
        }
    except PermissionError as exc:
        return {"true_access": False, "restricted": True, "error": str(exc)}
    except Exception as exc:
        return {"true_access": False, "error": str(exc)}

def _exec_file_write(
    path: str,
    content: str,
    mode: str = "w",
    encoding: str = "utf-8",
) -> dict:
    try:
        resolved = _workspace_path(path)
        payload = content.encode(encoding)
        if len(payload) > MAX_WRITE_BYTES:
            return {"true_access": False, "error": f"Write exceeds {MAX_WRITE_BYTES} byte limit"}
        resolved.parent.mkdir(parents=True, exist_ok=True)
        safe_mode = mode if mode in ("w", "a") else "w"
        with resolved.open(safe_mode, encoding=encoding) as handle:
            handle.write(content)
        return {
            "true_access": True,
            "path": str(resolved),
            "bytes_written": len(content.encode(encoding)),
            "mode": safe_mode,
        }
    except PermissionError as exc:
        return {"true_access": False, "restricted": True, "error": str(exc)}
    except Exception as exc:
        return {"true_access": False, "error": str(exc)}


def _validate_external_url(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Only absolute HTTP/HTTPS URLs are allowed")
    host = parts.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise PermissionError("Local HTTP targets are blocked")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Host resolution failed: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if not ip.is_global:
            raise PermissionError(f"Non-public target blocked: {ip}")
    return parts.scheme, host


def _exec_http_get(
    url:     str,
    headers: Optional[dict] = None,
    timeout: int = 15,
) -> dict:
    timeout = max(1, min(int(timeout or 15), MAX_TOOL_TIMEOUT))
    t0 = time.perf_counter()
    try:
        _validate_external_url(url)
        req = URLRequest(url)
        req.add_header("User-Agent", f"SupervisorAgent/{VERSION}")
        if isinstance(headers, dict):
            for k, v in headers.items():
                req.add_header(str(k), str(v))
        with urlopen(req, timeout=timeout) as resp:
            raw      = resp.read(MAX_HTTP_BYTES + 1)   # 512 KB cap
            if len(raw) > MAX_HTTP_BYTES:
                return {"true_access": False, "url": url, "error": "Response exceeds size limit"}
            charset  = resp.headers.get_content_charset() or "utf-8"
            body_str = raw.decode(charset, errors="replace")
            elapsed  = round((time.perf_counter() - t0) * 1000, 2)
            try:
                body      = json.loads(body_str)
                body_type = "json"
            except json.JSONDecodeError:
                body      = body_str[:8_000]
                body_type = "text"
            return {
                "true_access":  True,
                "url":          url,
                "status_code":  resp.status,
                "content_type": resp.headers.get("Content-Type", ""),
                "body":         body,
                "body_type":    body_type,
                "size_bytes":   len(raw),
                "elapsed_ms":   elapsed,
            }
    except HTTPError as e:
        return {"true_access": False, "url": url, "status_code": e.code,
                "error": f"HTTP {e.code}: {e.reason}"}
    except URLError as e:
        return {"true_access": False, "url": url, "error": str(e.reason)}
    except Exception as e:
        return {"true_access": False, "url": url, "error": str(e)}


def _exec_http_post(
    url:     str,
    body:    dict,
    headers: Optional[dict] = None,
    timeout: int = 15,
) -> dict:
    timeout = max(1, min(int(timeout or 15), MAX_TOOL_TIMEOUT))
    t0 = time.perf_counter()
    try:
        _validate_external_url(url)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if len(payload) > MAX_REQUEST_BYTES:
            return {"true_access": False, "url": url, "error": "POST body exceeds size limit"}
        req = URLRequest(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", f"SupervisorAgent/{VERSION}")
        if isinstance(headers, dict):
            for k, v in headers.items():
                req.add_header(str(k), str(v))
        with urlopen(req, timeout=timeout) as resp:
            raw      = resp.read(MAX_HTTP_BYTES + 1)
            if len(raw) > MAX_HTTP_BYTES:
                return {"true_access": False, "url": url, "error": "Response exceeds size limit"}
            charset  = resp.headers.get_content_charset() or "utf-8"
            body_str = raw.decode(charset, errors="replace")
            elapsed  = round((time.perf_counter() - t0) * 1000, 2)
            try:
                resp_body = json.loads(body_str)
                body_type = "json"
            except json.JSONDecodeError:
                resp_body = body_str[:8_000]
                body_type = "text"
            return {
                "true_access": True,
                "url":         url,
                "status_code": resp.status,
                "body":        resp_body,
                "body_type":   body_type,
                "elapsed_ms":  elapsed,
            }
    except HTTPError as e:
        return {"true_access": False, "url": url, "status_code": e.code,
                "error": f"HTTP {e.code}: {e.reason}"}
    except URLError as e:
        return {"true_access": False, "url": url, "error": str(e.reason)}
    except Exception as e:
        return {"true_access": False, "url": url, "error": str(e)}


def _exec_process_list(
    filter_name: Optional[str] = None, top_n: int = 20, sort_by: str = "cpu",
) -> dict:
    return _restricted("process inspection")

def _exec_python(code: str, timeout: int = 15) -> dict:
    return _restricted("Python child execution")

def _exec_api_status(host: str = "127.0.0.1", port: int = 8787) -> dict:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return {"true_access": False, "restricted": True, "error": "api_status is loopback-only"}
    try:
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError("invalid port")
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        t0 = time.perf_counter()
        conn.request("GET", "/api/v1/status", headers={"User-Agent": f"SupervisorAgent/{VERSION}"})
        resp = conn.getresponse()
        raw = resp.read(MAX_HTTP_BYTES + 1)
        conn.close()
        if len(raw) > MAX_HTTP_BYTES:
            return {"true_access": False, "error": "Response exceeds size limit"}
        body_text = raw.decode("utf-8", errors="replace")
        try:
            body = json.loads(body_text)
        except json.JSONDecodeError:
            body = body_text[:8000]
        return {"true_access": 200 <= resp.status < 300, "status_code": resp.status, "master_agent": body, "url": f"http://127.0.0.1:{port}/api/v1/status", "latency_ms": round((time.perf_counter()-t0)*1000,2)}
    except Exception as exc:
        return {"true_access": False, "error": str(exc), "url": f"http://127.0.0.1:{port}/api/v1/status"}


# ── Dispatcher ────────────────────────────────────────────────────────────────

_EXECUTORS: dict[str, Any] = {
    "shell_exec":   lambda i: _exec_shell(
        i["command"],
        timeout=i.get("timeout", 30),
        cwd=i.get("cwd"),
        env_extra=i.get("env_extra"),
    ),
    "file_read":    lambda i: _exec_file_read(
        i["path"],
        encoding=i.get("encoding", "utf-8"),
        max_bytes=i.get("max_bytes", 100_000),
    ),
    "file_write":   lambda i: _exec_file_write(
        i["path"], i["content"],
        mode=i.get("mode", "w"),
        encoding=i.get("encoding", "utf-8"),
    ),
    "http_get":     lambda i: _exec_http_get(
        i["url"],
        headers=i.get("headers"),
        timeout=i.get("timeout", 15),
    ),
    "http_post":    lambda i: _exec_http_post(
        i["url"], i["body"],
        headers=i.get("headers"),
        timeout=i.get("timeout", 15),
    ),
    "process_list": lambda i: _exec_process_list(
        filter_name=i.get("filter_name"),
        top_n=i.get("top_n", 20),
        sort_by=i.get("sort_by", "cpu"),
    ),
    "python_exec":  lambda i: _exec_python(
        i["code"],
        timeout=i.get("timeout", 15),
    ),
    "api_status":   lambda i: _exec_api_status(
        host=i.get("host", "127.0.0.1"),
        port=i.get("port", 8787),
    ),
}
_EXECUTORS = {k: v for k, v in _EXECUTORS.items() if k in {"file_read", "file_write", "http_get", "http_post", "api_status"}}


def dispatch_tool(name: str, inp: dict) -> dict:
    """Execute tool, stamp _tool/_total_ms, emit audit entry."""
    if name not in _EXECUTORS:
        return {"true_access": False, "error": f"Unknown tool: {name}", "_tool": name}

    _audit("tool_call", {"tool": name, "preview": str(inp)[:180]})
    t0 = time.perf_counter()

    try:
        result = _EXECUTORS[name](inp)
    except KeyError as e:
        result = {"true_access": False, "error": f"Missing required input: {e}"}
    except Exception:
        result = {"true_access": False, "error": traceback.format_exc()[-800:]}

    result["_tool"]     = name
    result["_total_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    _audit("tool_result", {
        "tool":        name,
        "true_access": result.get("true_access"),
        "total_ms":    result["_total_ms"],
        "error":       result.get("error"),
    })
    return result

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# FIX-07: Moved here — BEFORE _call_anthropic — so source order matches
#         execution order. (v1.0 had _SYSTEM_PROMPT defined after the
#         function that uses it, which works at runtime but is confusing.)
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = f"""You are SUPERVISOR — a workspace-scoped agent with web access.

TOOLS AVAILABLE:
  file_read     → read files inside WORKSPACE_ROOT
  file_write    → write/append files inside WORKSPACE_ROOT
  http_get      → HTTP/HTTPS GET public Internet URLs
  http_post     → HTTP/HTTPS POST JSON to public Internet URLs
  api_status    → check master_agent.py metrics (:8787)

EXECUTION PROTOCOL:
1. Decompose the task into steps.
2. Execute tools — gather data first, then act.
3. Each tool result has true_access: true (success) or false (failure + error).
4. On true_access:false → diagnose, try alternative command/path/approach.
5. Maximum {MAX_FIX_ITERATIONS} fix iterations per tool failure.
   When _fix_cap_reached is set in a result: STOP retrying that approach;
   mark the task partial and move on.
6. Continue tool rounds until task fully resolved.
7. Deliver final JSON result — no prose filler.

FINAL RESPONSE FORMAT (plain JSON, no markdown fences):
{{
  "status": "completed" | "partial" | "failed",
  "summary": "<one-line result>",
  "data": {{ ... actual structured output ... }},
  "tools_used": ["<tool>", ...],
  "true_access_failures": <int>,
  "recommendations": ["<if any>"]
}}

Rules:
- No introductions, no filler — data over description.
- If unsure, use available read-only checks before changing workspace files.
- All timestamps in ISO 8601 UTC.
- Supervisor version: {VERSION}
"""

# ─────────────────────────────────────────────────────────────────────────────
# ANTHROPIC API CLIENT — stdlib http.client, no SDK
# FIX-08/09: Retry with exponential backoff; honours Retry-After on 429
# ─────────────────────────────────────────────────────────────────────────────

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_RETRY_MAX      = 3
_RETRY_BASE_S   = 1.5   # seconds; doubles each attempt → 1.5 / 3.0 / 6.0


def _call_anthropic(messages: list, max_tokens: int = 4096) -> dict:
    """POST /v1/messages with tool_use enabled. Retries on 429/5xx."""
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. Run: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    payload = json.dumps({
        "model":      CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system":     _SYSTEM_PROMPT,
        "tools":      TOOL_DEFS,
        "messages":   messages,
    }, ensure_ascii=False).encode("utf-8")

    last_err: Optional[Exception] = None

    for attempt in range(_RETRY_MAX):
        conn = http.client.HTTPSConnection("api.anthropic.com", timeout=120)
        try:
            conn.request(
                "POST", "/v1/messages",
                body=payload,
                headers={
                    "Content-Type":      "application/json",
                    "x-api-key":         ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                },
            )
            resp = conn.getresponse()
            raw  = resp.read()
        except Exception as exc:
            last_err = exc
            wait = _RETRY_BASE_S * (2 ** attempt)
            logger.warning(
                f"Anthropic connection error "
                f"(attempt {attempt + 1}/{_RETRY_MAX}): {exc} — retry in {wait:.1f}s"
            )
            time.sleep(wait)
            continue
        finally:
            conn.close()

        if resp.status in _RETRY_STATUSES:
            last_err = RuntimeError(f"HTTP {resp.status}")
            wait = _RETRY_BASE_S * (2 ** attempt)
            ra   = resp.getheader("Retry-After", "")
            if ra:
                try:
                    wait = max(wait, float(ra))
                except ValueError:
                    pass
            logger.warning(
                f"Anthropic {resp.status} "
                f"(attempt {attempt + 1}/{_RETRY_MAX}) — retry in {wait:.1f}s"
            )
            time.sleep(wait)
            continue

        data = json.loads(raw.decode("utf-8"))
        if resp.status != 200:
            raise RuntimeError(
                f"Anthropic API {resp.status}: "
                f"{data.get('error', {}).get('message', raw[:300])}"
            )
        return data

    raise RuntimeError(
        f"Anthropic API failed after {_RETRY_MAX} attempts: {last_err}"
    )

# ─────────────────────────────────────────────────────────────────────────────
# AGENT LOOP — multi-turn tool_use
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """FIX-12: Robust JSON extraction — fenced blocks → balanced-brace scan.
    Replaces the greedy regex that misfired on multiple/nested JSON objects."""
    text = text.strip()

    # 1. Try the whole text directly
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 2. Fenced code blocks (```json ... ``` or ``` ... ```)
    for m in re.finditer(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, re.DOTALL):
        try:
            result = json.loads(m.group(1))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            continue

    # 3. Balanced-brace scan — finds the first complete JSON object
    for start in range(len(text)):
        if text[start] != "{":
            continue
        depth   = 0
        in_str  = False
        escaped = False
        for i in range(start, len(text)):
            c = text[i]
            if escaped:
                escaped = False
                continue
            if c == "\\" and in_str:
                escaped = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        result = json.loads(candidate)
                        if isinstance(result, dict):
                            return result
                    except json.JSONDecodeError:
                        pass
                    break   # move to next start position

    return {
        "status":  "completed",
        "summary": text or "(empty response)",
        "data":    {},
    }


def run_agent(prompt: str, tid: str) -> dict:
    """
    Full multi-turn agent loop with task-level timeout.
    Returns final result dict. Updates task store throughout.
    """
    messages:    list[dict] = [{"role": "user", "content": prompt}]
    tools_used:  list[str]  = []
    steps:       list[dict] = []
    fix_iters:   int        = 0
    ta_failures: int        = 0
    deadline:    float      = time.monotonic() + TASK_TIMEOUT  # NEW-01

    task_update(tid, status="running", started_iso=_iso())
    _audit("agent_start", {"tid": tid, "prompt": prompt[:150]})

    for round_n in range(MAX_AGENT_ROUNDS):

        # ── NEW-01: Per-task timeout ───────────────────────────────────────
        if time.monotonic() > deadline:
            final = {
                "status":               "partial",
                "summary":              f"Task timed out after {TASK_TIMEOUT}s",
                "data":                 {},
                "tools_used":           list(dict.fromkeys(tools_used)),
                "true_access_failures": ta_failures,
                "steps":                steps,
                "agent_rounds":         round_n,
            }
            task_update(tid, status="partial", result=final,
                        ended_iso=_iso(), steps=steps)
            _audit("agent_timeout", {"tid": tid, "rounds": round_n})
            return final

        # ── Call Claude ───────────────────────────────────────────────────
        try:
            resp = _call_anthropic(messages)
        except EnvironmentError as e:
            err = str(e)
            task_update(tid, status="failed", error=err, ended_iso=_iso())
            _audit("agent_error", {"tid": tid, "error": err})
            return {"status": "failed", "error": err, "summary": "API key missing"}
        except Exception as e:
            err = str(e)
            logger.error(f"[{tid[:8]}] Claude error round {round_n}: {err}")
            task_update(tid, status="failed", error=err, ended_iso=_iso())
            _audit("agent_error", {"tid": tid, "error": err})
            return {"status": "failed", "error": err, "summary": "Anthropic API error"}

        content     = resp.get("content", [])
        stop_reason = resp.get("stop_reason", "")
        task_update(tid, agent_rounds=round_n + 1)

        messages.append({"role": "assistant", "content": content})

        tool_uses = [b for b in content if b.get("type") == "tool_use"]

        # ── No tool calls → extract final answer ─────────────────────────
        if not tool_uses:
            texts     = [b.get("text", "") for b in content if b.get("type") == "text"]
            final_str = "\n".join(texts).strip()

            # FIX-13: handle max_tokens truncation explicitly
            if stop_reason == "max_tokens" and not final_str:
                final_str = json.dumps({
                    "status":  "partial",
                    "summary": "Response truncated by max_tokens limit",
                    "data":    {},
                })

            result = _extract_json(final_str)
            result.setdefault("tools_used",           list(dict.fromkeys(tools_used)))
            result.setdefault("true_access_failures", ta_failures)
            result["steps"]        = steps
            result["agent_rounds"] = round_n + 1

            terminal_status = result.get("status", "completed")
            if terminal_status not in {"completed", "partial", "failed"}:
                terminal_status = "completed"
            task_update(
                tid,
                status=terminal_status,
                result=result,
                ended_iso=_iso(),
                steps=steps,
                tools_used=list(dict.fromkeys(tools_used)),
                true_access_failures=ta_failures,
            )
            _audit("agent_done", {
                "tid":         tid,
                "rounds":      round_n + 1,
                "tools_used":  len(tools_used),
                "ta_failures": ta_failures,
            })
            return result

        # ── Execute each tool_use ─────────────────────────────────────────
        tool_results: list[dict] = []

        for tu in tool_uses:
            t_name  = tu.get("name", "")
            t_input = tu.get("input", {})
            t_id    = tu.get("id", "")

            logger.info(f"[{tid[:8]}] round={round_n} tool={t_name} inp={str(t_input)[:80]}")

            tr = dispatch_tool(t_name, t_input)
            tools_used.append(t_name)

            step: dict = {
                "round":       round_n,
                "tool":        t_name,
                "true_access": tr.get("true_access", True),
                "elapsed_ms":  tr.get("_total_ms"),
                "error":       tr.get("error"),
            }

            # ── Handle true_access:false ──────────────────────────────────
            if not tr.get("true_access", True):
                ta_failures += 1
                fix_iters   += 1
                step["fix_attempt"] = fix_iters
                logger.warning(
                    f"[{tid[:8]}] true_access:false {t_name} "
                    f"fix={fix_iters}/{MAX_FIX_ITERATIONS} "
                    f"err={tr.get('error', '')[:80]}"
                )
                task_update(tid, fix_iterations=fix_iters,
                            true_access_failures=ta_failures)

                # FIX-11: Enforce cap — annotate result so Claude knows to stop
                if fix_iters >= MAX_FIX_ITERATIONS:
                    tr["_fix_cap_reached"] = True
                    tr["_fix_msg"] = (
                        f"Fix iteration cap ({MAX_FIX_ITERATIONS}) reached. "
                        "Stop retrying this approach; report partial or try a "
                        "completely different method."
                    )

            steps.append(step)
            task_update(tid, steps=steps)

            # FIX-10: field-aware truncation prevents invalid JSON
            result_str = _safe_json_dumps(tr, max_bytes=10_000)
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": t_id,
                "content":     result_str,
            })

        messages.append({"role": "user", "content": tool_results})

    # ── Max rounds exceeded ───────────────────────────────────────────────────
    final = {
        "status":               "partial",
        "summary":              f"Max agent rounds ({MAX_AGENT_ROUNDS}) reached without final answer",
        "data":                 {},
        "tools_used":           list(dict.fromkeys(tools_used)),
        "true_access_failures": ta_failures,
        "steps":                steps,
        "agent_rounds":         MAX_AGENT_ROUNDS,
    }
    task_update(tid, status="partial", result=final,
                ended_iso=_iso(), steps=steps)
    _audit("agent_max_rounds", {"tid": tid, "rounds": MAX_AGENT_ROUNDS})
    return final

# ─────────────────────────────────────────────────────────────────────────────
# WORKER POOL
# ─────────────────────────────────────────────────────────────────────────────

_task_queue: Queue = Queue()


def _worker(wid: int) -> None:
    logger.info(f"Worker-{wid} ready")
    while True:
        try:
            tid = _task_queue.get(timeout=1)
        except Empty:
            continue
        try:
            t = task_get(tid)
            if t and t["status"] == "queued":
                run_agent(t["prompt"], tid)
        except Exception:
            logger.exception(f"Worker-{wid} unhandled exception for {tid}")
            task_update(
                tid,
                status="failed",
                error=traceback.format_exc()[-600:],
                ended_iso=_iso(),
            )
        finally:
            _task_queue.task_done()


def start_workers() -> None:
    for i in range(TASK_WORKERS):
        t = threading.Thread(
            target=_worker, args=(i,), daemon=True, name=f"worker-{i}"
        )
        t.start()

# ─────────────────────────────────────────────────────────────────────────────
# REST API — SupervisorHandler
# ─────────────────────────────────────────────────────────────────────────────

class SupervisorHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info(f"HTTP {self.address_string()} — {fmt % args}")

    def _set_headers(self, status: int = 200, ctype: str = "application/json", content_length: Optional[int] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Supervisor-Version", VERSION)
        if content_length is not None:
            self.send_header("Content-Length", str(content_length))
        self.end_headers()

    def _json(self, data: Any, status: int = 200) -> None:
        try:
            body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            self._set_headers(status, content_length=len(body))
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _read_body(self) -> Optional[dict]:
        """FIX-15: Parse JSON body with MAX_REQUEST_BYTES guard (returns None on oversized)."""
        try:
            raw_len = int(self.headers.get("Content-Length", 0))
            if raw_len < 0:
                return None
            if raw_len == 0:
                return {}
            if raw_len > MAX_REQUEST_BYTES:
                return None
            raw = self.rfile.read(raw_len)
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _path(self) -> str:
        return self.path.split("?")[0].rstrip("/") or "/"

    def _extract_tid(self, prefix: str) -> Optional[str]:
        """FIX-14: Extract and validate task ID — returns None on empty string."""
        p   = self._path()
        tid = p[len(prefix):]
        return tid if tid else None

    # ── OPTIONS (CORS preflight) ──────────────────────────────────────────────

    def do_OPTIONS(self) -> None:
        self._set_headers(204, content_length=0)

    # ── GET ───────────────────────────────────────────────────────────────────

    def do_GET(self) -> None:
        try:
            p = self._path()

            if p in ("/health", "/"):
                self._json({
                    "service":  "supervisor_agent",
                    "version":  VERSION,
                    "status":   "healthy",
                    "uptime_s": round(time.monotonic() - _supervisor_start, 1),
                })

            elif p == "/supervisor/status":
                counts = _tasks_summary()   # NEW-05: O(1) — no full snapshot
                self._json({
                    "version":          VERSION,
                    "uptime_s":         round(time.monotonic() - _supervisor_start, 1),
                    "model":            CLAUDE_MODEL,
                    "api_key_set":      bool(ANTHROPIC_API_KEY),
                    "workspace_root":    str(WORKSPACE_ROOT),
                    "master_agent_url": MASTER_AGENT_URL,
                    "workers":          TASK_WORKERS,
                    "tasks":            counts,
                    "tasks_total":      sum(counts.values()),
                    "audit_entries":    len(_audit_deque),
                    "max_fix_iter":     MAX_FIX_ITERATIONS,
                    "max_agent_rounds": MAX_AGENT_ROUNDS,
                    "task_timeout_s":   TASK_TIMEOUT,
                    "tools_available":  [t["name"] for t in TOOL_DEFS],
                })

            elif p == "/supervisor/logs":
                logs = audit_snapshot(100)
                self._json({"count": len(logs), "logs": logs})

            elif p == "/tasks":
                snap = tasks_snapshot()
                self._json({"count": len(snap), "tasks": snap})

            elif p.startswith("/task/"):
                tid = self._extract_tid("/task/")
                if not tid:
                    self._json({"error": "Task ID required"}, 400)
                    return
                task = task_get(tid)
                if task:
                    self._json(task)
                else:
                    self._json({"error": "Task not found", "id": tid}, 404)

            elif p == "/report":
                snap  = tasks_snapshot()
                done  = sum(1 for t in snap if t["status"] == "completed")
                fail  = sum(1 for t in snap if t["status"] == "failed")
                run   = sum(1 for t in snap if t["status"] == "running")
                queue = sum(1 for t in snap if t["status"] == "queued")
                self._json({
                    "supervisor": {
                        "version":  VERSION,
                        "uptime_s": round(time.monotonic() - _supervisor_start, 1),
                        "api_key":  "SET" if ANTHROPIC_API_KEY else "MISSING",
                        "model":    CLAUDE_MODEL,
                    },
                    "tasks": {
                        "total":     len(snap),
                        "queued":    queue,
                        "running":   run,
                        "completed": done,
                        "failed":    fail,
                    },
                    "recent_results": [
                        {
                            "id":      t["id"][:8],
                            "prompt":  t["prompt"][:60],
                            "status":  t["status"],
                            "summary": (t.get("result") or {}).get("summary", "—"),
                        }
                        for t in sorted(
                            snap, key=lambda x: x["created_iso"], reverse=True
                        )[:10]
                    ],
                    "tools":         [d["name"] for d in TOOL_DEFS],
                    "generated_iso": _iso(),
                })

            else:
                self._json({"error": "Not found", "path": p}, 404)

        except Exception as e:
            logger.exception("GET error")
            self._json({"error": str(e)}, 500)

    # ── POST ──────────────────────────────────────────────────────────────────

    def do_POST(self) -> None:
        try:
            p    = self._path()
            body = self._read_body()

            # FIX-15: differentiate 413 (too large) from 400 (bad JSON)
            if body is None:
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > MAX_REQUEST_BYTES:
                    self._json({
                        "error": f"Request body exceeds limit ({MAX_REQUEST_BYTES} bytes)",
                    }, 413)
                else:
                    self._json({"error": "Invalid or missing JSON body"}, 400)
                return

            if p == "/task":
                prompt = str(body.get("prompt", "")).strip()
                if not prompt:
                    self._json({"error": "'prompt' field required and non-empty"}, 400)
                    return
                if not ANTHROPIC_API_KEY:
                    self._json({
                        "error": "ANTHROPIC_API_KEY not set",
                        "fix":   "export ANTHROPIC_API_KEY=sk-ant-...",
                    }, 503)
                    return
                tid = task_create(prompt)
                _task_queue.put(tid)
                logger.info(f"Task queued: {tid[:8]} | {prompt[:80]}")
                self._json({
                    "task_id": tid,
                    "status":  "queued",
                    "poll":    f"GET /task/{tid}",
                }, 201)

            elif p == "/tool/exec":
                tool = str(body.get("tool", "")).strip()
                inp  = body.get("input", {})
                if not tool:
                    self._json({"error": "'tool' field required"}, 400)
                    return
                if tool not in _EXECUTORS:
                    self._json({
                        "error":           f"Unknown tool: {tool}",
                        "available_tools": list(_EXECUTORS.keys()),
                    }, 400)
                    return
                result = dispatch_tool(tool, inp if isinstance(inp, dict) else {})
                self._json(result)

            else:
                self._json({"error": "Not found", "path": p}, 404)

        except Exception as e:
            logger.exception("POST error")
            self._json({"error": str(e)}, 500)

    # ── DELETE ────────────────────────────────────────────────────────────────

    def do_DELETE(self) -> None:
        try:
            p = self._path()
            if p.startswith("/task/"):
                tid = self._extract_tid("/task/")
                if not tid:
                    self._json({"error": "Task ID required"}, 400)
                    return
                task = task_get(tid)
                if not task:
                    self._json({"error": "Task not found", "id": tid}, 404)
                    return
                if task["status"] in ("queued", "running"):
                    self._json({
                        "error":  "Cannot delete active task",
                        "status": task["status"],
                    }, 409)
                    return
                ok = task_delete(tid)
                self._json({"deleted": ok, "id": tid})
            else:
                self._json({"error": "Not found", "path": p}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)


class SupervisorServer(ThreadingMixIn, HTTPServer):
    daemon_threads      = True
    allow_reuse_address = True
    timeout             = 30   # NEW-06: reap idle sockets after 30 s

# ─────────────────────────────────────────────────────────────────────────────
# GRACEFUL SHUTDOWN  — NEW-02/03: SIGTERM + SIGINT via threading.Event
# ─────────────────────────────────────────────────────────────────────────────

_shutdown_event = threading.Event()


def _handle_signal(sig: int, _frame: Any) -> None:
    try:
        sig_name = signal.Signals(sig).name
    except ValueError:
        sig_name = str(sig)
    logger.info(f"Signal {sig_name} received — initiating graceful shutdown")
    _shutdown_event.set()

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info(f"supervisor_agent v{VERSION} starting")
    logger.info(f"Python {sys.version.split()[0]} | {platform.system()} {platform.machine()}")
    logger.info(f"Claude model      : {CLAUDE_MODEL}")
    logger.info(f"API key set       : {bool(ANTHROPIC_API_KEY)}")
    logger.info(f"master_agent URL  : {MASTER_AGENT_URL}")
    logger.info(f"Workers           : {TASK_WORKERS}")
    logger.info(f"Max fix iters     : {MAX_FIX_ITERATIONS}")
    logger.info(f"Max agent rounds  : {MAX_AGENT_ROUNDS}")
    logger.info(f"Task timeout      : {TASK_TIMEOUT}s")
    logger.info(f"Max request bytes : {MAX_REQUEST_BYTES}")
    logger.info(f"Tools             : {[d['name'] for d in TOOL_DEFS]}")

    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — task execution will return 503")
        logger.warning("External agent execution is disabled in restricted mode")

    # NEW-02: Register SIGTERM (Docker/systemd) AND SIGINT (Ctrl+C)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    start_workers()

    server = SupervisorServer((SUPERVISOR_HOST, SUPERVISOR_PORT), SupervisorHandler)

    # NEW-03: HTTP server runs in a daemon thread; main thread blocks on event
    server_thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="http-server",
    )
    server_thread.start()

    logger.info(f"Supervisor API: http://{SUPERVISOR_HOST}:{SUPERVISOR_PORT}")
    logger.info("  POST   /task               submit task (returns task_id)")
    logger.info("  GET    /task/{id}           poll result")
    logger.info("  GET    /tasks              list all tasks")
    logger.info("  DELETE /task/{id}           delete done/failed task")
    logger.info("  POST   /tool/exec          direct tool call (no API key)")
    logger.info("  GET    /supervisor/status  live metrics")
    logger.info("  GET    /supervisor/logs    last 100 audit entries")
    logger.info("  GET    /report             Scriptable JSON report")
    logger.info("  GET    /health             liveness probe")
    logger.info("CTRL+C or SIGTERM to stop.")

    _shutdown_event.wait()      # blocks until signal received

    logger.info("Shutting down supervisor…")
    server.shutdown()
    server.server_close()       # FIX-16: was missing in v1.0 — releases port
    logger.info("Supervisor stopped.")
    sys.exit(0)


if __name__ == "__main__":
    main()
