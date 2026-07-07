#!/usr/bin/env python3
"""Build and validate the sys/os mirror plus remote-access toolkit."""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import subprocess
import sys


SCHEMA_VERSION = "local_usr.sys.build_sys_os_remote.v1"
ROOT = pathlib.Path(__file__).resolve().parents[3]
SYS_ROOT = ROOT / "local_usr" / "sys"
REPORT_PATH = ROOT / "validation" / "SYS_OS_MIRROR_REMOTE_ACCESS_BUILD.json"


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_step(name: str, command: list[str]) -> dict:
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, timeout=60, check=False)
    return {
        "name": name,
        "command": command,
        "exit_code": completed.returncode,
        "ok": completed.returncode == 0,
        "stdout": completed.stdout.strip()[-4000:],
        "stderr": completed.stderr.strip()[-4000:],
    }


def main() -> int:
    steps = [
        ("compile_path_init", [sys.executable, "-m", "py_compile", "local_usr/sys/bin/path_init.py"]),
        ("compile_sys_os_mirror", [sys.executable, "-m", "py_compile", "local_usr/sys/bin/sys_os_mirror.py"]),
        ("compile_remote_access", [sys.executable, "-m", "py_compile", "local_usr/sys/bin/remote_access_gateway.py"]),
        ("compile_system_app_chat", [sys.executable, "-m", "py_compile", "local_usr/sys/bin/system_app_chat.py"]),
        ("compile_start_services", [sys.executable, "-m", "py_compile", "local_usr/sys/bin/start_services.py"]),
        ("compile_standalone_all_in_one_os", [sys.executable, "-m", "py_compile", "local_usr/sys/bin/standalone_all_in_one_os.py"]),
        ("compile_ios_restricted_migration", [sys.executable, "-m", "py_compile", "local_usr/sys/bin/ios_restricted_migration.py"]),
        ("compile_api_key_passes", [sys.executable, "-m", "py_compile", "local_usr/sys/bin/api_key_passes.py"]),
        ("compile_reasoned_installer_export", [sys.executable, "-m", "py_compile", "local_usr/sys/bin/reasoned_installer_export.py"]),
        ("path_init", [sys.executable, "local_usr/sys/bin/path_init.py"]),
        ("api_key_passes_init", [sys.executable, "local_usr/sys/bin/api_key_passes.py", "init"]),
        ("api_key_passes_validate", [sys.executable, "local_usr/sys/bin/api_key_passes.py", "validate"]),
        ("ios_restricted_migration_init", [sys.executable, "local_usr/sys/bin/ios_restricted_migration.py", "init"]),
        ("ios_restricted_migration_validate", [sys.executable, "local_usr/sys/bin/ios_restricted_migration.py", "validate"]),
        ("reasoned_installer_export", [sys.executable, "local_usr/sys/bin/reasoned_installer_export.py", "export"]),
        ("reasoned_installer_export_validate", [sys.executable, "local_usr/sys/bin/reasoned_installer_export.py", "validate"]),
        ("standalone_all_in_one_os_init", [sys.executable, "local_usr/sys/bin/standalone_all_in_one_os.py", "init"]),
        ("standalone_all_in_one_os_validate", [sys.executable, "local_usr/sys/bin/standalone_all_in_one_os.py", "validate"]),
        ("system_app_chat_init", [sys.executable, "local_usr/sys/bin/system_app_chat.py", "init"]),
        ("system_app_chat_self_test", [sys.executable, "local_usr/sys/bin/system_app_chat.py", "self-test"]),
        ("system_app_chat_validate", [sys.executable, "local_usr/sys/bin/system_app_chat.py", "validate"]),
        ("mirror_init", [sys.executable, "local_usr/sys/bin/sys_os_mirror.py", "init"]),
        ("mirror_create", [sys.executable, "local_usr/sys/bin/sys_os_mirror.py", "mirror"]),
        ("remote_init", [sys.executable, "local_usr/sys/bin/remote_access_gateway.py", "init"]),
        ("remote_validate", [sys.executable, "local_usr/sys/bin/remote_access_gateway.py", "validate"]),
    ]
    results = [run_step(name, command) for name, command in steps]
    report = {
        "schema_version": SCHEMA_VERSION,
        "built_at_utc": utc_now(),
        "root": str(ROOT),
        "sys_root": str(SYS_ROOT),
        "ok": all(item["ok"] for item in results),
        "steps": results,
        "entrypoints": {
            "path_init": "local_usr/sys/bin/path_init.py",
            "api_key_passes": "local_usr/sys/bin/api_key_passes.py",
            "ios_restricted_migration": "local_usr/sys/bin/ios_restricted_migration.py",
            "reasoned_installer_export": "local_usr/sys/bin/reasoned_installer_export.py",
            "sys_os_mirror": "local_usr/sys/bin/sys_os_mirror.py",
            "remote_access_gateway": "local_usr/sys/bin/remote_access_gateway.py",
            "system_app_chat": "local_usr/sys/bin/system_app_chat.py",
            "start_services": "local_usr/sys/bin/start_services.py",
            "standalone_all_in_one_os": "local_usr/sys/bin/standalone_all_in_one_os.py",
        },
        "remote_access": {
            "default_bind": "127.0.0.1",
            "default_port": 8765,
            "read_only": True,
            "shell_execution_enabled": False,
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report": str(REPORT_PATH)}, ensure_ascii=True, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
