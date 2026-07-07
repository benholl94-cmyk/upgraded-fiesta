#!/usr/bin/env python3
"""Start and inspect local_usr/sys services."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any


SCHEMA_VERSION = "local_usr.sys.services.v1"
ROOT = pathlib.Path(__file__).resolve().parents[3]
SYS_ROOT = ROOT / "local_usr" / "sys"
RUN_DIR = SYS_ROOT / "var" / "run"
LOG_DIR = SYS_ROOT / "var" / "log"
STATE_PATH = RUN_DIR / "services.state.json"


SERVICES = {
    "system_app_chat": {
        "command": [sys.executable, "local_usr/sys/bin/system_app_chat.py", "serve"],
        "health_url": "http://127.0.0.1:8787/health",
        "pid_file": RUN_DIR / "system_app_chat.pid",
        "stdout_log": LOG_DIR / "system_app_chat.service.log",
        "stderr_log": LOG_DIR / "system_app_chat.service.err.log",
    },
    "remote_access_gateway": {
        "command": [sys.executable, "local_usr/sys/bin/remote_access_gateway.py", "serve"],
        "health_url": "http://127.0.0.1:8765/health",
        "pid_file": RUN_DIR / "remote_access_gateway.pid",
        "stdout_log": LOG_DIR / "remote_access_gateway.service.log",
        "stderr_log": LOG_DIR / "remote_access_gateway.service.err.log",
    },
}


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_pid(path: pathlib.Path) -> int | None:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None
    return value if value > 0 else None


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def health(url: str, timeout: float = 1.5) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            payload = json.loads(body) if body.strip().startswith("{") else {"raw": body}
            return {"ok": 200 <= response.status < 300, "status": response.status, "payload": payload}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - status must report diagnostics.
        return {"ok": False, "error": str(exc)}


def service_status(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    pid = read_pid(spec["pid_file"])
    health_result = health(spec["health_url"])
    return {
        "name": name,
        "pid": pid,
        "pid_alive": process_alive(pid) if pid else False,
        "health_url": spec["health_url"],
        "health": health_result,
        "stdout_log": str(spec["stdout_log"]),
        "stderr_log": str(spec["stderr_log"]),
    }


def start_service(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    current = service_status(name, spec)
    if current["health"]["ok"]:
        current["started"] = False
        current["reason"] = "already healthy"
        return current

    pid = current["pid"]
    if pid and not current["pid_alive"]:
        try:
            spec["pid_file"].unlink()
        except FileNotFoundError:
            pass

    spec["stdout_log"].parent.mkdir(parents=True, exist_ok=True)
    stdout = spec["stdout_log"].open("ab")
    stderr = spec["stderr_log"].open("ab")
    process = subprocess.Popen(
        spec["command"],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
    spec["pid_file"].write_text(f"{process.pid}\n", encoding="utf-8")

    final_health = {"ok": False, "error": "health check not attempted"}
    for _ in range(20):
        time.sleep(0.2)
        final_health = health(spec["health_url"])
        if final_health["ok"]:
            break
    time.sleep(0.5)

    status = service_status(name, spec)
    status["started"] = True
    status["spawned_pid"] = process.pid
    status["health"] = final_health if status["pid_alive"] else health(spec["health_url"])
    if not status["pid_alive"]:
        status["error"] = "process exited after startup"
    return status


def stop_service(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    pid = read_pid(spec["pid_file"])
    result = {"name": name, "pid": pid, "stopped": False}
    if not pid:
        result["reason"] = "pid file missing"
        return result
    if not process_alive(pid):
        spec["pid_file"].unlink(missing_ok=True)
        result["reason"] = "process already exited"
        return result
    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        time.sleep(0.1)
        if not process_alive(pid):
            spec["pid_file"].unlink(missing_ok=True)
            result["stopped"] = True
            return result
    result["reason"] = "process still alive after SIGTERM"
    return result


def run(command: str) -> dict[str, Any]:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if command == "start":
        services = [start_service(name, spec) for name, spec in SERVICES.items()]
    elif command == "status":
        services = [service_status(name, spec) for name, spec in SERVICES.items()]
    elif command == "stop":
        services = [stop_service(name, spec) for name, spec in SERVICES.items()]
    else:
        raise ValueError(f"unknown command: {command}")

    report = {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "checked_at_utc": utc_now(),
        "ok": all(item.get("health", {}).get("ok", item.get("stopped", False)) for item in services),
        "services": services,
    }
    write_json(STATE_PATH, report)
    return report


def foreground() -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    services = [start_service(name, spec) for name, spec in SERVICES.items()]
    report = {
        "schema_version": SCHEMA_VERSION,
        "command": "foreground",
        "checked_at_utc": utc_now(),
        "ok": all(item.get("health", {}).get("ok") and item.get("pid_alive") for item in services),
        "services": services,
    }
    write_json(STATE_PATH, report)
    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
    if not report["ok"]:
        return 2
    try:
        while True:
            time.sleep(5)
            status = run("status")
            if not status["ok"]:
                restarted = [start_service(name, spec) for name, spec in SERVICES.items()]
                status = {
                    "schema_version": SCHEMA_VERSION,
                    "command": "foreground-restart",
                    "checked_at_utc": utc_now(),
                    "ok": all(item.get("health", {}).get("ok") and item.get("pid_alive") for item in restarted),
                    "services": restarted,
                }
                write_json(STATE_PATH, status)
                print(json.dumps(status, ensure_ascii=True, indent=2), flush=True)
                if not status["ok"]:
                    return 2
    except KeyboardInterrupt:
        stop_report = run("stop")
        print(json.dumps(stop_report, ensure_ascii=True, indent=2), flush=True)
        return 0 if stop_report["ok"] else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start and inspect local_usr/sys services.")
    parser.add_argument("command", choices=["start", "status", "stop", "foreground"])
    args = parser.parse_args(argv)
    if args.command == "foreground":
        return foreground()
    report = run(args.command)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
