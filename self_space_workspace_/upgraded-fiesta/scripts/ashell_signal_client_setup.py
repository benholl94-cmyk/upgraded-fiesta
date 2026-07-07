#!/usr/bin/env python3
"""Create and validate a mobile/a-Shell Signal gateway client config.

This helper does not require Docker and does not start signal-cli. It is intended
for iPhone a-Shell as the control-plane client for a remote or tunneled gateway.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
SETTINGS_DIR = ROOT / "settings"
LOCAL_CONFIG = SETTINGS_DIR / "signal-cli-client.local.json"


def http_get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return res.status, res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:  # network and TLS errors should be readable in a-Shell
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:9922", help="Signal gateway base URL")
    parser.add_argument("--write", action="store_true", help="Write settings/signal-cli-client.local.json")
    parser.add_argument("--check", action="store_true", help="Check GET /v1/about on the gateway")
    args = parser.parse_args()

    gateway = args.gateway.rstrip("/")
    config = {
        "signal_cli": {
            "enabled": True,
            "role": "iphone_a_shell_client",
            "gateway_base_url": gateway,
            "about_endpoint": f"{gateway}/v1/about",
            "send_endpoint": f"{gateway}/v2/send",
            "requires_remote_docker_host": True,
        }
    }

    if args.write:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        LOCAL_CONFIG.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {LOCAL_CONFIG}")

    if args.check:
        status, body = http_get(f"{gateway}/v1/about")
        print(json.dumps({"gateway": gateway, "status": status, "body": body[:500]}, ensure_ascii=False))
        return 0 if 200 <= status < 400 else 2

    print(json.dumps(config, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
