from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "hm_gateway_watchdog.py"


def test_missing_owner_token_refuses() -> None:
    env = {k: v for k, v in os.environ.items() if k != "HM_OWNER_TOKEN"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.returncode == 1
    assert json.loads(proc.stdout.strip()) == {"ok": False, "reason": "HM_OWNER_TOKEN is not set"}


def test_unreachable_gateway_reports_unhealthy_without_restarting() -> None:
    env = dict(
        os.environ,
        HM_OWNER_TOKEN="unused",
        HM_WATCHDOG_HEALTH_URL="http://127.0.0.1:1/health",
        HM_WATCHDOG_RESTART="false",
    )
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout.strip())
    assert payload["ok"] is False
    assert payload["restarted"] is False


def test_healthy_gateway_reports_ok(tmp_path: pathlib.Path) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    gateway_bin = repo_root / "target" / "debug" / "hm-gateway"
    if not gateway_bin.is_file():
        import pytest
        pytest.skip("hm-gateway debug binary not built")

    env = dict(
        os.environ,
        HM_OWNER_TOKEN="watchdog-smoke-token",
        HM_GATEWAY_BIND="127.0.0.1:18333",
        HM_STORAGE_ROOT=str(tmp_path / "storage"),
    )
    gateway = subprocess.Popen([str(gateway_bin)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(20):
            time.sleep(0.25)
            check = subprocess.run(
                [
                    sys.executable, str(SCRIPT),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(
                    env,
                    HM_WATCHDOG_HEALTH_URL="http://127.0.0.1:18333/health",
                    HM_WATCHDOG_RESTART="false",
                ),
            )
            if check.returncode == 0:
                break
        else:
            raise AssertionError(f"gateway never became healthy; last check: {check.stdout!r} {check.stderr!r}")

        payload = json.loads(check.stdout.strip())
        assert payload == {
            "ok": True,
            "reason": "healthy",
            "url": "http://127.0.0.1:18333/health",
            "unit": "hm-gateway.service",
            "restarted": False,
        }
    finally:
        gateway.terminate()
        gateway.wait(timeout=5)
