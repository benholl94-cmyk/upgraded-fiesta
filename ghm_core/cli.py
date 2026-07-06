#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import sys
import urllib.error
import urllib.request
import http.server

VERSION = "0.1.0"
REQUIRED_DIRS = ["data", "logs", "runs", "datasets", "docs", "exports", "settings", "tmp"]

# The exact, and only, fields collect_diagnostics_fields() ever gathers.
# Keep this list and the consent prompt in cmd_report_diagnostics in sync --
# never add a field here without updating what the prompt discloses.
DIAGNOSTICS_FIELDS = ("os_name", "os_version", "python_version", "architecture")


def collect_diagnostics_fields() -> dict[str, str]:
    return {
        "os_name": platform.system(),
        "os_version": platform.release(),
        "python_version": platform.python_version(),
        "architecture": platform.machine(),
    }


def ensure_workspace(path: str) -> pathlib.Path:
    root = pathlib.Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / ".ghm_workspace.json").write_text(json.dumps({"ok": True, "version": VERSION, "workspace": str(root)}, indent=2) + "\n")
    return root


def cmd_init(args):
    root = ensure_workspace(args.workspace)
    print(json.dumps({"ok": True, "workspace": str(root)}, indent=2))
    return 0


def cmd_status(args):
    root = ensure_workspace(args.workspace)
    print(json.dumps({"ok": True, "workspace": str(root), "required_dirs": REQUIRED_DIRS}, indent=2))
    return 0


def cmd_serve(args):
    root = ensure_workspace(args.workspace)
    os.chdir(root)
    print(json.dumps({"ok": True, "url": f"http://{args.host}:{args.port}", "workspace": str(root)}, sort_keys=True), flush=True)
    http.server.test(HandlerClass=QuietHandler, port=args.port, bind=args.host)
    return 0


def cmd_report_diagnostics(args) -> int:
    fields = collect_diagnostics_fields()
    destination = f"{args.gateway_url.rstrip('/')}/diagnostics"

    print("This will send exactly these fields, nothing else, to your own gateway:")
    print(json.dumps(fields, indent=2, sort_keys=True))
    print(f"Destination: {destination}")

    if not args.yes:
        if not sys.stdin.isatty():
            print(json.dumps({"ok": False, "sent": False, "reason": "no_consent_non_interactive_run_with_--yes_to_send"}))
            return 1
        answer = input("Send this? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print(json.dumps({"ok": True, "sent": False, "reason": "declined"}))
            return 0

    token = os.environ.get("HM_OWNER_TOKEN")
    if not token:
        print(json.dumps({"ok": False, "sent": False, "reason": "HM_OWNER_TOKEN is not set"}))
        return 1

    request = urllib.request.Request(
        destination,
        data=json.dumps(fields).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = json.loads(error.read().decode("utf-8")) if error.fp else {}
        print(json.dumps({"ok": False, "sent": False, "http_status": error.code, "response": body}, indent=2))
        return 1
    except urllib.error.URLError as error:
        print(json.dumps({"ok": False, "sent": False, "reason": str(error.reason)}))
        return 1

    print(json.dumps({"ok": True, "sent": True, "response": body}, indent=2))
    return 0


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def handle_one_request(self):
        try:
            return super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            return


def build_parser():
    p = argparse.ArgumentParser(prog="python3 -m ghm_core.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in [("init-workspace", cmd_init), ("doctor", cmd_status), ("status", cmd_status), ("serve", cmd_serve)]:
        sp = sub.add_parser(name)
        sp.add_argument("--workspace", required=True)
        sp.add_argument("--host", default="127.0.0.1")
        sp.add_argument("--port", type=int, default=18789)
        sp.set_defaults(func=fn)

    diag = sub.add_parser("report-diagnostics", help="Send opt-in diagnostics (OS, Python version, architecture) to your gateway")
    diag.add_argument("--gateway-url", default="http://127.0.0.1:8080")
    diag.add_argument("--yes", action="store_true", help="Skip the interactive prompt and send immediately")
    diag.set_defaults(func=cmd_report_diagnostics)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
