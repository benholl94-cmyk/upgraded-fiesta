#!/usr/bin/env python3
"""
Initialize a standalone local_usr/sys control-plane path.

This script is intentionally stdlib-only and network-free. It creates missing
data/channels/live-sets from real local observations, not fabricated external
data.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = "local_usr.sys.path_init.v1"
LIVE_SET_SCHEMA = "local_usr.sys.live_set.v1"
CHANNEL_SCHEMA = "local_usr.sys.channel.v1"
DATASET_SCHEMA = "local_usr.sys.dataset.v1"

ROOT = pathlib.Path(__file__).resolve().parents[3]
SYS_ROOT = ROOT / "local_usr" / "sys"
STREAMPipe = ROOT / "logs" / "git" / "local" / "streampipe.cli"


REQUIRED_DIRS = [
    "bin",
    "etc",
    "etc/channels",
    "etc/datasets",
    "etc/anchors",
    "etc/policies",
    "etc/app_tokens",
    "var",
    "var/lib",
    "var/lib/anchors",
    "var/lib/channels",
    "var/lib/data",
    "var/lib/live_sets",
    "var/lib/system_app_chat",
    "var/log",
    "var/run",
    "usr",
    "usr/share",
    "usr/share/manifests",
    "tmp",
]


CHANNELS = {
    "git_local": {
        "purpose": "Local git/lg2 event capture channel",
        "source": "logs/git/local/events.jsonl",
        "sink": "local_usr/sys/var/lib/channels/git_local.events.jsonl",
        "validation": "logs/git/local/validation.json",
    },
    "runtime": {
        "purpose": "Local Python and shell runtime capability channel",
        "source": "local observations",
        "sink": "local_usr/sys/var/lib/channels/runtime.events.jsonl",
        "validation": "local_usr/sys/var/lib/live_sets/runtime.live.json",
    },
    "control_plane": {
        "purpose": "Local control-plane status and path readiness channel",
        "source": "local_usr/sys/var/run/state.json",
        "sink": "local_usr/sys/var/lib/channels/control_plane.events.jsonl",
        "validation": "local_usr/sys/var/lib/live_sets/control_plane.live.json",
    },
    "bridge": {
        "purpose": "Bridge readiness channel without assuming provider credentials",
        "source": "environment and local config presence",
        "sink": "local_usr/sys/var/lib/channels/bridge.events.jsonl",
        "validation": "local_usr/sys/var/lib/live_sets/bridge.live.json",
    },
    "system_app_chat": {
        "purpose": "Token-protected internal system/app chat and event bus",
        "source": "local apps via CLI or HTTP",
        "sink": "local_usr/sys/var/lib/system_app_chat/chat.sqlite3",
        "validation": "local_usr/sys/var/run/system_app_chat.validation.json",
    },
    "flyoos_env_points_anchors_localization": {
        "purpose": "Local anchor map for claude/env-points-anchors-localization-flyoos",
        "source": "local environment names, workspace paths, and control-plane observations",
        "sink": "local_usr/sys/var/lib/anchors/flyoos_env_points_anchors_localization.anchor.json",
        "validation": "local_usr/sys/var/lib/live_sets/flyoos_env_points_anchors_localization.live.json",
    },
}


DATASETS = {
    "path_inventory": {
        "purpose": "Materialized inventory of required local_usr/sys paths",
        "file": "local_usr/sys/var/lib/data/path_inventory.dataset.json",
    },
    "command_inventory": {
        "purpose": "Detected local command support for mobile control-plane operation",
        "file": "local_usr/sys/var/lib/data/command_inventory.dataset.json",
    },
    "streampipe_state": {
        "purpose": "Standalone streampipe local git/log state summary",
        "file": "local_usr/sys/var/lib/data/streampipe_state.dataset.json",
    },
    "app_chat_state": {
        "purpose": "Local system app chat registry and message-count summary",
        "file": "local_usr/sys/var/lib/data/app_chat_state.dataset.json",
    },
    "flyoos_anchor_state": {
        "purpose": "Materialized local anchor state for claude/env-points-anchors-localization-flyoos",
        "file": "local_usr/sys/var/lib/data/flyoos_anchor_state.dataset.json",
    },
}


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def sha256(data: Any) -> str:
    return hashlib.sha256(stable_json(data).encode("utf-8")).hexdigest()


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        return {"_read_error": f"invalid json: {exc}"}


def read_jsonl_count(path: pathlib.Path) -> dict[str, Any]:
    result = {"exists": path.exists(), "valid_lines": 0, "invalid_lines": 0, "bytes": 0}
    if not path.exists():
        return result
    result["bytes"] = path.stat().st_size
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                json.loads(line)
                result["valid_lines"] += 1
            except json.JSONDecodeError:
                result["invalid_lines"] += 1
    return result


def write_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data) if isinstance(data, dict) else {"value": data}
    payload.setdefault("written_at_utc", utc_now())
    payload["content_sha256"] = sha256({k: v for k, v in payload.items() if k != "content_sha256"})
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_event(path: pathlib.Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    event = dict(event)
    event.setdefault("captured_at_utc", utc_now())
    event["event_sha256"] = sha256(event)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")


def command_probe(command: str) -> dict[str, Any]:
    found = shutil.which(command)
    result: dict[str, Any] = {"command": command, "available": found is not None, "path": found}
    if not found:
        return result
    try:
        completed = subprocess.run(
            [command, "--version"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
        result.update(
            {
                "version_probe_exit_code": completed.returncode,
                "version_stdout": completed.stdout.strip()[:500],
                "version_stderr": completed.stderr.strip()[:500],
            }
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics must not crash initialization.
        result["version_probe_error"] = str(exc)
    return result


def maybe_run_streampipe_capture() -> dict[str, Any]:
    if not STREAMPipe.exists():
        return {"executed": False, "reason": "streampipe.cli missing", "path": str(STREAMPipe)}
    try:
        completed = subprocess.run(
            [sys.executable, str(STREAMPipe), "capture"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        return {
            "executed": True,
            "exit_code": completed.returncode,
            "stdout_preview": completed.stdout.strip()[:1000],
            "stderr_preview": completed.stderr.strip()[:1000],
        }
    except Exception as exc:  # noqa: BLE001
        return {"executed": False, "reason": str(exc), "path": str(STREAMPipe)}


def ensure_dirs() -> dict[str, Any]:
    created: list[str] = []
    existing: list[str] = []
    for rel in REQUIRED_DIRS:
        path = SYS_ROOT / rel
        if path.exists():
            existing.append(str(path.relative_to(ROOT)))
        else:
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path.relative_to(ROOT)))
    return {"created": created, "existing": existing}


def path_inventory() -> dict[str, Any]:
    records = []
    for rel in REQUIRED_DIRS:
        path = SYS_ROOT / rel
        records.append(
            {
                "relative_path": str(path.relative_to(ROOT)),
                "exists": path.exists(),
                "is_dir": path.is_dir(),
                "is_file": path.is_file(),
            }
        )
    return {"schema_version": DATASET_SCHEMA, "dataset_id": "path_inventory", "records": records}


def command_inventory() -> dict[str, Any]:
    commands = ["python3", "python", "git", "lg2", "zip", "unzip"]
    return {
        "schema_version": DATASET_SCHEMA,
        "dataset_id": "command_inventory",
        "records": [command_probe(command) for command in commands],
    }


def streampipe_state() -> dict[str, Any]:
    base = ROOT / "logs" / "git" / "local"
    return {
        "schema_version": DATASET_SCHEMA,
        "dataset_id": "streampipe_state",
        "records": {
            "cli_exists": STREAMPipe.exists(),
            "manifest": read_json(base / "manifest.json"),
            "validation": read_json(base / "validation.json"),
            "events": read_jsonl_count(base / "events.jsonl"),
            "latest_event": read_json(base / "latest_event.json"),
        },
    }


def app_chat_state() -> dict[str, Any]:
    db_path = SYS_ROOT / "var" / "lib" / "system_app_chat" / "chat.sqlite3"
    records: dict[str, Any] = {
        "db_exists": db_path.exists(),
        "config": read_json(SYS_ROOT / "etc" / "system_app_chat.config.json"),
        "validation": read_json(SYS_ROOT / "var" / "run" / "system_app_chat.validation.json"),
    }
    if db_path.exists():
        try:
            import sqlite3

            with sqlite3.connect(db_path) as conn:
                records["registered_apps"] = conn.execute("SELECT COUNT(*) FROM apps").fetchone()[0]
                records["messages"] = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        except Exception as exc:  # noqa: BLE001 - path init must remain diagnostic-safe.
            records["sqlite_error"] = str(exc)
    return {
        "schema_version": DATASET_SCHEMA,
        "dataset_id": "app_chat_state",
        "records": records,
    }


def flyoos_anchor_state() -> dict[str, Any]:
    anchor_id = "claude/env-points-anchors-localization-flyoos"
    safe_env_names = [
        key
        for key in sorted(os.environ)
        if key.startswith(("CLAUDE_", "CODEX_", "FLYOOS_", "LOCAL_USR_SYS_", "OPENAI_"))
        or key.endswith(("_API_KEY", "_TOKEN", "_URL", "_PATH"))
    ]
    local_points = {
        "workspace_root": str(ROOT),
        "sys_root": str(SYS_ROOT),
        "bin": str(SYS_ROOT / "bin"),
        "channels": str(SYS_ROOT / "etc" / "channels"),
        "datasets": str(SYS_ROOT / "etc" / "datasets"),
        "anchors": str(SYS_ROOT / "etc" / "anchors"),
        "live_sets": str(SYS_ROOT / "var" / "lib" / "live_sets"),
        "anchor_state": str(SYS_ROOT / "var" / "lib" / "anchors"),
    }
    component_paths = {
        "path_init": "local_usr/sys/bin/path_init.py",
        "system_app_chat": "local_usr/sys/bin/system_app_chat.py",
        "sys_os_mirror": "local_usr/sys/bin/sys_os_mirror.py",
        "remote_access_gateway": "local_usr/sys/bin/remote_access_gateway.py",
        "streampipe_cli": "logs/git/local/streampipe.cli",
    }
    component_status = {
        name: {
            "relative_path": relative_path,
            "exists": (ROOT / relative_path).exists(),
        }
        for name, relative_path in component_paths.items()
    }
    return {
        "schema_version": DATASET_SCHEMA,
        "dataset_id": "flyoos_anchor_state",
        "records": {
            "anchor_id": anchor_id,
            "normalized_anchor_id": "flyoos_env_points_anchors_localization",
            "localization_scope": "workspace-local-standalone",
            "external_data_fabricated": False,
            "secret_values_read": False,
            "env_names_present": safe_env_names,
            "local_points": local_points,
            "component_status": component_status,
            "required_channels": sorted(CHANNELS),
            "required_datasets": sorted(DATASETS),
        },
    }


def build_live_sets() -> dict[str, dict[str, Any]]:
    env_bridge_keys = [
        key
        for key in sorted(os.environ)
        if key.endswith("_API_KEY") or key in {"OPENAI_API_KEY", "CODEX_BRIDGE_URL", "CODEX_LOCAL_BRIDGE"}
    ]
    return {
        "runtime": {
            "schema_version": LIVE_SET_SCHEMA,
            "live_set_id": "runtime",
            "source": "local runtime observation",
            "facts": {
                "python_executable": sys.executable,
                "python_version": sys.version.split()[0],
                "platform": sys.platform,
                "platform_detail": platform.platform(),
                "cwd": str(ROOT),
                "sys_root": str(SYS_ROOT),
                "commands": command_inventory()["records"],
            },
        },
        "git_local": {
            "schema_version": LIVE_SET_SCHEMA,
            "live_set_id": "git_local",
            "source": "logs/git/local generated state",
            "facts": streampipe_state()["records"],
        },
        "control_plane": {
            "schema_version": LIVE_SET_SCHEMA,
            "live_set_id": "control_plane",
            "source": "local_usr/sys path readiness",
            "facts": {
                "required_path_count": len(REQUIRED_DIRS),
                "paths": path_inventory()["records"],
                "channels_declared": sorted(CHANNELS),
                "datasets_declared": sorted(DATASETS),
            },
        },
        "bridge": {
            "schema_version": LIVE_SET_SCHEMA,
            "live_set_id": "bridge",
            "source": "environment variable name presence only",
            "facts": {
                "credential_values_read": False,
                "credential_like_env_names_present": env_bridge_keys,
                "bridge_configured_by_env_name": bool(env_bridge_keys),
                "network_probe_performed": False,
            },
        },
        "system_app_chat": {
            "schema_version": LIVE_SET_SCHEMA,
            "live_set_id": "system_app_chat",
            "source": "local system_app_chat state",
            "facts": app_chat_state()["records"],
        },
        "flyoos_env_points_anchors_localization": {
            "schema_version": LIVE_SET_SCHEMA,
            "live_set_id": "flyoos_env_points_anchors_localization",
            "source": "claude/env-points-anchors-localization-flyoos local anchor state",
            "facts": flyoos_anchor_state()["records"],
        },
    }


def ensure_channels() -> dict[str, Any]:
    created: list[str] = []
    existing: list[str] = []
    for channel_id, spec in CHANNELS.items():
        descriptor = SYS_ROOT / "etc" / "channels" / f"{channel_id}.channel.json"
        event_stream = SYS_ROOT / "var" / "lib" / "channels" / f"{channel_id}.events.jsonl"
        if descriptor.exists():
            existing.append(str(descriptor.relative_to(ROOT)))
        else:
            write_json(
                descriptor,
                {
                    "schema_version": CHANNEL_SCHEMA,
                    "channel_id": channel_id,
                    "purpose": spec["purpose"],
                    "source": spec["source"],
                    "sink": spec["sink"],
                    "validation": spec["validation"],
                    "status": "initialized",
                },
            )
            created.append(str(descriptor.relative_to(ROOT)))
        if not event_stream.exists():
            append_event(
                event_stream,
                {
                    "schema_version": CHANNEL_SCHEMA,
                    "channel_id": channel_id,
                    "event_type": "channel_initialized",
                    "source_exists": (ROOT / spec["source"]).exists() if not spec["source"].startswith("local ") else True,
                },
            )
            created.append(str(event_stream.relative_to(ROOT)))
    return {"created": created, "existing": existing}


def ensure_datasets() -> dict[str, Any]:
    builders = {
        "path_inventory": path_inventory,
        "command_inventory": command_inventory,
        "streampipe_state": streampipe_state,
        "app_chat_state": app_chat_state,
        "flyoos_anchor_state": flyoos_anchor_state,
    }
    generated: list[str] = []
    for dataset_id, spec in DATASETS.items():
        target = ROOT / spec["file"]
        payload = builders[dataset_id]()
        payload["purpose"] = spec["purpose"]
        write_json(target, payload)
        descriptor = SYS_ROOT / "etc" / "datasets" / f"{dataset_id}.dataset.json"
        write_json(
            descriptor,
            {
                "schema_version": DATASET_SCHEMA,
                "dataset_id": dataset_id,
                "purpose": spec["purpose"],
                "file": spec["file"],
                "generated_from": "local observations",
            },
        )
        generated.extend([str(target.relative_to(ROOT)), str(descriptor.relative_to(ROOT))])
    return {"generated": generated}


def ensure_anchors() -> dict[str, Any]:
    payload = flyoos_anchor_state()
    anchor = {
        "schema_version": "local_usr.sys.anchor.v1",
        "anchor_id": payload["records"]["anchor_id"],
        "normalized_anchor_id": payload["records"]["normalized_anchor_id"],
        "purpose": "Local runnable anchor state requested as @codex claude/env-points-anchors-localization-flyoos",
        "dataset_id": "flyoos_anchor_state",
        "dataset_file": DATASETS["flyoos_anchor_state"]["file"],
        "channel_id": "flyoos_env_points_anchors_localization",
        "live_set_file": "local_usr/sys/var/lib/live_sets/flyoos_env_points_anchors_localization.live.json",
        "facts": payload["records"],
    }
    generated: list[str] = []
    state_target = SYS_ROOT / "var" / "lib" / "anchors" / "flyoos_env_points_anchors_localization.anchor.json"
    descriptor_target = SYS_ROOT / "etc" / "anchors" / "flyoos_env_points_anchors_localization.anchor.json"
    write_json(state_target, anchor)
    write_json(
        descriptor_target,
        {
            "schema_version": "local_usr.sys.anchor.v1",
            "anchor_id": anchor["anchor_id"],
            "normalized_anchor_id": anchor["normalized_anchor_id"],
            "purpose": anchor["purpose"],
            "state_file": str(state_target.relative_to(ROOT)),
            "dataset_file": anchor["dataset_file"],
            "channel_id": anchor["channel_id"],
            "live_set_file": anchor["live_set_file"],
        },
    )
    generated.extend([str(state_target.relative_to(ROOT)), str(descriptor_target.relative_to(ROOT))])
    return {"generated": generated}


def ensure_live_sets() -> dict[str, Any]:
    generated: list[str] = []
    existing_before: list[str] = []
    live_sets = build_live_sets()
    for live_set_id, payload in live_sets.items():
        target = SYS_ROOT / "var" / "lib" / "live_sets" / f"{live_set_id}.live.json"
        if target.exists():
            existing_before.append(str(target.relative_to(ROOT)))
        payload["generation_policy"] = {
            "generated_when_missing_or_false": True,
            "external_data_fabricated": False,
            "source_type": "standalone_self_made_local_observation",
        }
        write_json(target, payload)
        generated.append(str(target.relative_to(ROOT)))
    index = {
        "schema_version": LIVE_SET_SCHEMA,
        "live_sets": [
            {
                "live_set_id": live_set_id,
                "file": f"local_usr/sys/var/lib/live_sets/{live_set_id}.live.json",
            }
            for live_set_id in sorted(live_sets)
        ],
    }
    write_json(SYS_ROOT / "var" / "lib" / "live_sets" / "index.json", index)
    generated.append("local_usr/sys/var/lib/live_sets/index.json")
    return {"generated": generated, "existing_before": existing_before}


def validate() -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    required_files = [
        SYS_ROOT / "etc" / "sys_manifest.json",
        SYS_ROOT / "var" / "run" / "state.json",
        SYS_ROOT / "var" / "lib" / "live_sets" / "index.json",
    ]
    for rel in REQUIRED_DIRS:
        path = SYS_ROOT / rel
        if not path.is_dir():
            errors.append(f"missing required directory: {path}")
    for path in required_files:
        if not path.is_file():
            errors.append(f"missing required file: {path}")
    for channel_id in CHANNELS:
        descriptor = SYS_ROOT / "etc" / "channels" / f"{channel_id}.channel.json"
        stream = SYS_ROOT / "var" / "lib" / "channels" / f"{channel_id}.events.jsonl"
        if not descriptor.exists():
            errors.append(f"missing channel descriptor: {descriptor}")
        if not stream.exists():
            errors.append(f"missing channel stream: {stream}")
    for dataset_id in DATASETS:
        descriptor = SYS_ROOT / "etc" / "datasets" / f"{dataset_id}.dataset.json"
        data_file = ROOT / DATASETS[dataset_id]["file"]
        if not descriptor.exists():
            errors.append(f"missing dataset descriptor: {descriptor}")
        if not data_file.exists():
            errors.append(f"missing dataset file: {data_file}")
    for live_set_id in build_live_sets():
        target = SYS_ROOT / "var" / "lib" / "live_sets" / f"{live_set_id}.live.json"
        payload = read_json(target)
        if not payload:
            errors.append(f"missing live-set: {target}")
        if payload.get("generation_policy", {}).get("external_data_fabricated") is not False:
            errors.append(f"live-set fabrication policy invalid: {target}")
    anchor_state = SYS_ROOT / "var" / "lib" / "anchors" / "flyoos_env_points_anchors_localization.anchor.json"
    anchor_descriptor = SYS_ROOT / "etc" / "anchors" / "flyoos_env_points_anchors_localization.anchor.json"
    if not anchor_state.exists():
        errors.append(f"missing anchor state: {anchor_state}")
    if not anchor_descriptor.exists():
        errors.append(f"missing anchor descriptor: {anchor_descriptor}")
    if read_jsonl_count(ROOT / "logs" / "git" / "local" / "events.jsonl")["invalid_lines"]:
        warnings.append("streampipe events.jsonl contains invalid lines")
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": not errors,
        "validated_at_utc": utc_now(),
        "root": str(ROOT),
        "sys_root": str(SYS_ROOT),
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    dir_result = ensure_dirs()
    stream_capture = maybe_run_streampipe_capture()
    channel_result = ensure_channels()
    dataset_result = ensure_datasets()
    anchor_result = ensure_anchors()
    live_set_result = ensure_live_sets()

    state = {
        "schema_version": SCHEMA_VERSION,
        "initialized_at_utc": utc_now(),
        "root": str(ROOT),
        "sys_root": str(SYS_ROOT),
        "dir_result": dir_result,
        "streampipe_capture": stream_capture,
        "channel_result": channel_result,
        "dataset_result": dataset_result,
        "anchor_result": anchor_result,
        "live_set_result": live_set_result,
        "policy": {
            "generate_missing_data_and_channels": True,
            "if_false_generate_standalone_checked_self_made_live_sets": True,
            "external_data_fabricated": False,
            "network_required": False,
            "stdlib_only": True,
        },
    }
    write_json(SYS_ROOT / "var" / "run" / "state.json", state)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_id": "local_usr_sys_control_plane",
        "root": str(ROOT),
        "sys_root": str(SYS_ROOT),
        "channels": CHANNELS,
        "datasets": DATASETS,
        "live_sets": sorted(build_live_sets()),
        "entrypoint": str(pathlib.Path(__file__).relative_to(ROOT)),
        "entrypoints": {
            "path_init": "local_usr/sys/bin/path_init.py",
            "api_key_passes": "local_usr/sys/bin/api_key_passes.py",
            "ios_restricted_migration": "local_usr/sys/bin/ios_restricted_migration.py",
            "reasoned_installer_export": "local_usr/sys/bin/reasoned_installer_export.py",
            "start_services": "local_usr/sys/bin/start_services.py",
            "standalone_all_in_one_os": "local_usr/sys/bin/standalone_all_in_one_os.py",
            "system_app_chat": "local_usr/sys/bin/system_app_chat.py",
            "sys_os_mirror": "local_usr/sys/bin/sys_os_mirror.py",
            "remote_access_gateway": "local_usr/sys/bin/remote_access_gateway.py",
        },
    }
    write_json(SYS_ROOT / "etc" / "sys_manifest.json", manifest)

    result = validate()
    write_json(SYS_ROOT / "var" / "run" / "validation.json", result)
    append_event(
        SYS_ROOT / "var" / "log" / "path_init.events.jsonl",
        {
            "schema_version": SCHEMA_VERSION,
            "event_type": "path_init_completed",
            "ok": result["ok"],
            "errors": result["errors"],
            "warnings": result["warnings"],
        },
    )
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
