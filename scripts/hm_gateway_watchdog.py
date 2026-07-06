#!/usr/bin/env python3
"""Single-shot health check for a running hm-gateway, with restart-on-hang.

systemd's `Restart=on-failure` (see deploy/hm-gateway.service) only recovers
from a crashed process; it does nothing for a process that is still alive
but wedged (deadlocked, out of file descriptors, etc.) and no longer
answering requests. This script is meant to be invoked periodically (via
deploy/hm-gateway-watchdog.timer) to close that gap: it makes one
authenticated GET /health request, and if it fails, asks systemd to restart
the unit.

Stdlib only, one-shot, no daemon of its own -- systemd's timer owns the
schedule.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


def check_health(url: str, token: str, timeout: float) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return False, f"unexpected_status_{response.status}"
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return False, f"http_error_{error.code}"
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        return False, f"unreachable: {error}"
    except json.JSONDecodeError as error:
        return False, f"invalid_json: {error}"

    if body.get("status") not in ("online", "zero_staked"):
        return False, f"unexpected_status_field: {body.get('status')!r}"
    return True, "healthy"


def main() -> int:
    url = os.environ.get("HM_WATCHDOG_HEALTH_URL", "http://127.0.0.1:8080/health")
    token = os.environ.get("HM_OWNER_TOKEN")
    unit = os.environ.get("HM_WATCHDOG_UNIT", "hm-gateway.service")
    timeout = float(os.environ.get("HM_WATCHDOG_TIMEOUT_SECONDS", "5"))
    restart_on_failure = os.environ.get("HM_WATCHDOG_RESTART", "true").lower() == "true"

    if not token:
        print(json.dumps({"ok": False, "reason": "HM_OWNER_TOKEN is not set"}))
        return 1

    healthy, reason = check_health(url, token, timeout)
    result = {"ok": healthy, "reason": reason, "url": url, "unit": unit, "restarted": False}

    if healthy:
        print(json.dumps(result))
        return 0

    if restart_on_failure:
        proc = subprocess.run(
            ["systemctl", "restart", unit],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        result["restarted"] = proc.returncode == 0
        if proc.returncode != 0:
            result["restart_error"] = proc.stderr.strip()

    print(json.dumps(result))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
