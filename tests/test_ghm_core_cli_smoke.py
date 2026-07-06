from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys


def test_doctor(tmp_path: pathlib.Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "ghm_core.cli", "doctor", "--workspace", str(tmp_path / "generated_heavy_metal")],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True


def test_report_diagnostics_collects_only_disclosed_fields() -> None:
    from ghm_core.cli import DIAGNOSTICS_FIELDS, collect_diagnostics_fields

    fields = collect_diagnostics_fields()
    assert set(fields.keys()) == set(DIAGNOSTICS_FIELDS)
    assert all(isinstance(value, str) and value for value in fields.values())


def test_report_diagnostics_refuses_to_send_without_consent() -> None:
    # Piping stdin (not a TTY) with no --yes must never send anything, and
    # must fail loudly (nonzero exit) rather than silently no-op.
    env = dict(os.environ, HM_OWNER_TOKEN="unused-should-not-be-read")
    proc = subprocess.run(
        [sys.executable, "-m", "ghm_core.cli", "report-diagnostics", "--gateway-url", "http://127.0.0.1:1"],
        text=True,
        input="",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.returncode == 1
    last_line = proc.stdout.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert payload == {
        "ok": False,
        "sent": False,
        "reason": "no_consent_non_interactive_run_with_--yes_to_send",
    }


def test_report_diagnostics_requires_owner_token_even_with_yes() -> None:
    env = {k: v for k, v in os.environ.items() if k != "HM_OWNER_TOKEN"}
    proc = subprocess.run(
        [sys.executable, "-m", "ghm_core.cli", "report-diagnostics", "--yes", "--gateway-url", "http://127.0.0.1:1"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.returncode == 1
    last_line = proc.stdout.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert payload == {"ok": False, "sent": False, "reason": "HM_OWNER_TOKEN is not set"}
