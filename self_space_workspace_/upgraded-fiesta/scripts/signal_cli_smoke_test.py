#!/usr/bin/env python3
"""Smoke-test the signal-cli REST gateway without requiring non-stdlib packages."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise SystemExit(f"missing environment variable: {name}")
    return value


def request(method: str, url: str, payload: dict | None = None) -> tuple[int, str]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body


def main() -> int:
    base_url = env("SIGNAL_API_BASE_URL", "http://127.0.0.1:9922").rstrip("/")

    status, body = request("GET", f"{base_url}/v1/about")
    print(json.dumps({"check": "about", "status": status, "body": body[:500]}, ensure_ascii=False))
    if status >= 400:
        return 2

    if "--send" not in sys.argv:
        print("send check skipped; pass --send to send SIGNAL_TEST_MESSAGE")
        return 0

    number = env("SIGNAL_ACCOUNT_NUMBER")
    recipient = env("SIGNAL_TEST_RECIPIENT")
    message = env("SIGNAL_TEST_MESSAGE", "upgraded-fiesta signal-cli smoke test")
    payload = {"number": number, "recipients": [recipient], "message": message}
    status, body = request("POST", f"{base_url}/v2/send", payload)
    print(json.dumps({"check": "send", "status": status, "body": body[:1000]}, ensure_ascii=False))
    return 0 if status < 400 else 3


if __name__ == "__main__":
    raise SystemExit(main())
