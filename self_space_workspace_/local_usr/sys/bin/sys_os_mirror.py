#!/usr/bin/env python3
"""
Local sys/os mirror tool.

Scope is deliberately the accessible local workspace and the generated
local_usr/sys control-plane tree. It creates a content-addressed inventory,
archive, restore plan, and validation report without external dependencies.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import json
import os
import pathlib
import stat
import sys
import tarfile
from typing import Any


SCHEMA_VERSION = "local_usr.sys.os_mirror.v1"
ROOT = pathlib.Path(__file__).resolve().parents[3]
SYS_ROOT = ROOT / "local_usr" / "sys"
STATE_DIR = SYS_ROOT / "var" / "lib" / "sys_os_mirror"
ARCHIVE_DIR = STATE_DIR / "archives"
CONFIG_PATH = SYS_ROOT / "etc" / "sys_os_mirror.config.json"
MANIFEST_PATH = STATE_DIR / "manifest.json"
VALIDATION_PATH = SYS_ROOT / "var" / "run" / "sys_os_mirror.validation.json"
RESTORE_PLAN_PATH = STATE_DIR / "restore_plan.json"
EVENTS_PATH = SYS_ROOT / "var" / "log" / "sys_os_mirror.events.jsonl"


DEFAULT_INCLUDE_ROOTS = [
    "local_usr/sys",
    "logs/git/local",
    "docs",
    "validation",
]

DEFAULT_EXCLUDE_PATTERNS = [
    ".git/*",
    "*/__pycache__/*",
    "*.pyc",
    "*.pyo",
    "*.tmp",
    "tmp/*",
    "local_usr/sys/tmp/*",
    "local_usr/sys/var/lib/sys_os_mirror/archives/*",
]

SENSITIVE_NAME_PATTERNS = [
    "*secret*",
    "*token*",
    "*password*",
    "*passwd*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
]


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def write_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data) if isinstance(data, dict) else {"value": data}
    payload.setdefault("written_at_utc", utc_now())
    payload["content_sha256"] = digest_json({k: v for k, v in payload.items() if k != "content_sha256"})
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        return {"_read_error": str(exc)}


def append_event(event: dict[str, Any]) -> None:
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("captured_at_utc", utc_now())
    payload["event_sha256"] = digest_json(payload)
    with EVENTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")


def rel(path: pathlib.Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def is_within_root(path: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(ROOT)
        return True
    except ValueError:
        return False


def is_excluded(relative_path: str, exclude_patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in exclude_patterns)


def is_sensitive_name(relative_path: str) -> bool:
    lower = pathlib.PurePosixPath(relative_path).name.lower()
    full = relative_path.lower()
    return any(fnmatch.fnmatch(lower, pattern) or fnmatch.fnmatch(full, pattern) for pattern in SENSITIVE_NAME_PATTERNS)


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def init_config() -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        config = {
            "schema_version": SCHEMA_VERSION,
            "root": str(ROOT),
            "state_dir": str(STATE_DIR),
            "include_roots": DEFAULT_INCLUDE_ROOTS,
            "exclude_patterns": DEFAULT_EXCLUDE_PATTERNS,
            "sensitive_name_patterns": SENSITIVE_NAME_PATTERNS,
            "archive_format": "tar.gz",
            "network_required": False,
            "external_dependencies": [],
        }
        write_json(CONFIG_PATH, config)
    return read_json(CONFIG_PATH)


def iter_inventory(config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    entries: list[dict[str, Any]] = []
    skipped: list[str] = []
    errors: list[str] = []
    exclude_patterns = list(config.get("exclude_patterns") or DEFAULT_EXCLUDE_PATTERNS)
    include_roots = list(config.get("include_roots") or DEFAULT_INCLUDE_ROOTS)

    for include_root in include_roots:
        root_path = (ROOT / include_root).resolve()
        if not root_path.exists():
            skipped.append(f"missing include root: {include_root}")
            continue
        if not is_within_root(root_path):
            errors.append(f"include root outside workspace denied: {root_path}")
            continue
        paths = [root_path] if root_path.is_file() else sorted(root_path.rglob("*"))
        for path in paths:
            if not is_within_root(path):
                skipped.append(f"outside workspace: {path}")
                continue
            relative = rel(path)
            if is_excluded(relative, exclude_patterns):
                skipped.append(relative)
                continue
            try:
                st = path.lstat()
            except OSError as exc:
                errors.append(f"stat failed: {relative}: {exc}")
                continue
            mode = stat.S_IMODE(st.st_mode)
            entry: dict[str, Any] = {
                "path": relative,
                "type": "directory" if path.is_dir() else "file" if path.is_file() else "other",
                "mode_octal": oct(mode),
                "size_bytes": st.st_size,
                "mtime_ns": st.st_mtime_ns,
                "sensitive_name": is_sensitive_name(relative),
            }
            if path.is_file():
                if entry["sensitive_name"]:
                    entry["sha256"] = None
                    entry["content_included"] = False
                    skipped.append(f"sensitive-name-content-skipped:{relative}")
                else:
                    try:
                        entry["sha256"] = file_sha256(path)
                        entry["content_included"] = True
                    except OSError as exc:
                        entry["sha256"] = None
                        entry["content_included"] = False
                        errors.append(f"hash failed: {relative}: {exc}")
            entries.append(entry)
    return entries, skipped, errors


def build_manifest(config: dict[str, Any]) -> dict[str, Any]:
    entries, skipped, errors = iter_inventory(config)
    file_entries = [item for item in entries if item["type"] == "file" and item.get("content_included")]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": utc_now(),
        "root": str(ROOT),
        "config_path": str(CONFIG_PATH),
        "entry_count": len(entries),
        "included_file_count": len(file_entries),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "entries": entries,
        "skipped": skipped,
        "errors": errors,
    }
    manifest["manifest_sha256"] = digest_json({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    return manifest


def create_archive(manifest: dict[str, Any]) -> pathlib.Path:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_name = f"sys_os_mirror_{manifest['created_at_utc'].replace(':', '').replace('-', '').replace('.', '')}.tar.gz"
    archive_path = ARCHIVE_DIR / archive_name
    with tarfile.open(archive_path, "w:gz") as archive:
        manifest_bytes = json.dumps(manifest, ensure_ascii=True, indent=2).encode("utf-8")
        info = tarfile.TarInfo("MANIFEST.sys_os_mirror.json")
        info.size = len(manifest_bytes)
        info.mtime = int(_dt.datetime.now().timestamp())
        archive.addfile(info, fileobj=__import__("io").BytesIO(manifest_bytes))
        for entry in manifest["entries"]:
            if entry["type"] == "file" and entry.get("content_included"):
                path = ROOT / entry["path"]
                archive.add(path, arcname=entry["path"], recursive=False)
            elif entry["type"] == "directory":
                path = ROOT / entry["path"]
                archive.add(path, arcname=entry["path"], recursive=False)
    return archive_path


def write_restore_plan(manifest: dict[str, Any], archive_path: pathlib.Path) -> dict[str, Any]:
    plan = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": utc_now(),
        "archive_path": str(archive_path),
        "archive_sha256": file_sha256(archive_path),
        "restore_mode": "operator_confirmed_manual_restore",
        "restore_root": str(ROOT),
        "steps": [
            "Validate archive sha256 before extraction.",
            "Extract into a new empty workspace or staging directory.",
            "Compare MANIFEST.sys_os_mirror.json against extracted files.",
            "Move selected files into the target workspace only after operator review.",
            "Run python3 local_usr/sys/bin/path_init.py after restore.",
            "Run python3 local_usr/sys/bin/sys_os_mirror.py validate after restore.",
        ],
        "automated_overwrite_enabled": False,
        "entries_expected": manifest["entry_count"],
    }
    write_json(RESTORE_PLAN_PATH, plan)
    return plan


def validate() -> dict[str, Any]:
    manifest = read_json(MANIFEST_PATH)
    plan = read_json(RESTORE_PLAN_PATH)
    errors: list[str] = []
    warnings: list[str] = []

    if not manifest:
        errors.append(f"missing manifest: {MANIFEST_PATH}")
    if manifest.get("errors"):
        warnings.extend(manifest["errors"])
    archive_path = pathlib.Path(plan.get("archive_path", "")) if plan else pathlib.Path()
    if not plan:
        errors.append(f"missing restore plan: {RESTORE_PLAN_PATH}")
    elif not archive_path.exists():
        errors.append(f"missing archive: {archive_path}")
    elif plan.get("archive_sha256") != file_sha256(archive_path):
        errors.append("archive sha256 mismatch")
    for entry in manifest.get("entries", []):
        if entry.get("type") == "file" and entry.get("content_included"):
            path = ROOT / entry["path"]
            if not path.exists():
                errors.append(f"missing source file: {entry['path']}")
            elif entry.get("sha256") != file_sha256(path):
                warnings.append(f"source file changed since mirror: {entry['path']}")

    result = {
        "schema_version": SCHEMA_VERSION,
        "ok": not errors,
        "validated_at_utc": utc_now(),
        "manifest_path": str(MANIFEST_PATH),
        "restore_plan_path": str(RESTORE_PLAN_PATH),
        "archive_path": str(archive_path) if plan else None,
        "errors": errors,
        "warnings": warnings,
    }
    write_json(VALIDATION_PATH, result)
    append_event({"event_type": "mirror_validated", "ok": result["ok"], "errors": errors, "warnings": warnings})
    return result


def mirror() -> dict[str, Any]:
    config = init_config()
    manifest = build_manifest(config)
    write_json(MANIFEST_PATH, manifest)
    archive_path = create_archive(manifest)
    restore_plan = write_restore_plan(manifest, archive_path)
    result = validate()
    append_event(
        {
            "event_type": "mirror_created",
            "archive_path": str(archive_path),
            "archive_sha256": restore_plan["archive_sha256"],
            "ok": result["ok"],
        }
    )
    return {"manifest": manifest, "restore_plan": restore_plan, "validation": result}


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=True, indent=2))


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and validate a local sys/os mirror archive.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("mirror")
    sub.add_parser("validate")
    sub.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.command == "init":
        print_json(init_config())
        return 0
    if args.command == "mirror":
        result = mirror()
        print_json(result["validation"])
        return 0 if result["validation"]["ok"] else 2
    if args.command == "validate":
        result = validate()
        print_json(result)
        return 0 if result["ok"] else 2
    if args.command == "status":
        print_json({"config": read_json(CONFIG_PATH), "manifest": read_json(MANIFEST_PATH), "validation": read_json(VALIDATION_PATH)})
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
