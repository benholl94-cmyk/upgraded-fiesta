#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import urllib.error
import urllib.request

VERSION = "1.0.0"
ROOT = pathlib.Path(__file__).resolve().parents[2]
SETTINGS_DIR = ROOT / "settings"
CONFIG_PATH = SETTINGS_DIR / "signal-cli-client.local.json"
VERSION_PATH = SETTINGS_DIR / "signal-gateway-workaround.version"


def http_get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return res.status, res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind iPhone/a-Shell client to the fixed signal-gateway-v1 workaround")
    parser.add_argument("--gateway", default="http://127.0.0.1:9922")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    gateway = args.gateway.rstrip("/")
    config = {
        "signal_cli": {
            "enabled": True,
            "workaround_id": "signal-gateway-v1",
            "workaround_version": VERSION,
            "role": "iphone_a_shell_client",
            "gateway_base_url": gateway,
            "about_endpoint": f"{gateway}/v1/about",
            "send_endpoint": f"{gateway}/v2/send",
            "server_side_transport_required": True,
        }
    }

    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    VERSION_PATH.write_text(VERSION + "\n", encoding="utf-8")
    print(f"wrote {CONFIG_PATH}")
    print(f"wrote {VERSION_PATH}")

    if args.check:
        status, body = http_get(f"{gateway}/v1/about")
        print(json.dumps({"workaround": "signal-gateway-v1", "version": VERSION, "gateway": gateway, "status": status, "body": body[:500]}, ensure_ascii=False))
        return 0 if 200 <= status < 400 else 2

    print(json.dumps(config, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
