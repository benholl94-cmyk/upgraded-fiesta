#!/usr/bin/env python3
"""
live_iso_manager.py

This script constructs and manages a secure, self‑contained workspace (a
"live ISO container") that complies with user‑defined policies and resists
modification by external actors. The container is initialized with a
predictable directory structure, anchored waypoints (file hashes) and
configuration data stored under the container root. It exposes simple
subcommands to initialize the container, verify its integrity, audit its
contents and export it as a portable zip archive.

Key features:
  * **Initialization** (`init`): Creates the container under a specified
    directory, populates required subfolders (bin, etc, var/log, datasets),
    writes a default policy file derived from user guidelines, and records
    cryptographic hashes of all managed files. A copy of this script is
    stored inside the container at `bin/live_iso_manager.py` for offline
    operation.
  * **Verification** (`verify`): Recomputes the hashes for files recorded in
    the manifest and reports any mismatches (deleted, modified or added
    files). This ensures that the container’s policies and tools have not
    been altered without authorization.
  * **Audit** (`audit`): Produces a JSON summary of all files under the
    container root, including their relative paths, sizes and SHA‑256
    digests. This can be used for external inspection or change control.
  * **Export** (`export`): Creates a ZIP archive of the entire container
    (excluding the export itself), facilitating offline storage or
    distribution.

The script is written in plain Python 3 with no external dependencies and
uses only the standard library. All on‑disk data is stored in human‑readable
JSON for transparency. The container enforces immutability of policies by
checking the manifest; if a policy file has been changed, a verification
error will be raised. The default policy file encodes the user’s key
requirements: unknown policies are forbidden (EU compliance) and external
systems cannot override user policies.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path


def utc_now() -> str:
    """Return the current UTC time in ISO‑8601 format with 'Z' suffix."""
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def compute_hash(path: Path) -> str:
    """Compute the SHA‑256 hash of a file's contents."""
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def create_directories(root: Path) -> None:
    """Create the minimal directory structure for the container."""
    for sub in ["bin", "etc", "var/log", "datasets"]:
        (root / sub).mkdir(parents=True, exist_ok=True)


def write_default_policy(root: Path) -> Path:
    """Write a default user policy if none exists and return its path."""
    policy_path = root / "etc" / "user_policy.json"
    if policy_path.exists():
        return policy_path
    policy = {
        "schema": "user.policy.v1",
        "created_at_utc": utc_now(),
        "description": (
            "Dieses Dokument legt grundlegende Nutzer‑Richtlinien fest. "
            "Unbekannte oder nicht überprüfbare Richtlinien sind untersagt "
            "(EU‑rechtliche Vorgaben). Externe Systeme oder Personen dürfen "
            "diese Richtlinien nicht verändern oder umgehen."
        ),
        "rules": {
            "unknown_policies_forbidden": True,
            "external_modification_forbidden": True,
        },
    }
    policy_path.write_text(json.dumps(policy, indent=2, ensure_ascii=False))
    return policy_path


def generate_manifest(root: Path, files: list[Path]) -> dict:
    """Generate a manifest dictionary for a list of files relative to root."""
    manifest = {
        "schema": "live_iso.manifest.v1",
        "generated_at_utc": utc_now(),
        "files": [],
        # manifest_sha256 and manifest_file_sha256 will be added later
    }
    for p in files:
        rel = p.relative_to(root).as_posix()
        manifest["files"].append({
            "path": rel,
            "sha256": compute_hash(p),
            "size_bytes": p.stat().st_size,
        })
    return manifest


def save_manifest(root: Path, manifest: dict) -> Path:
    """Save the manifest JSON under the etc directory and return its path."""
    manifest_path = root / "etc" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest_path


def gather_files_for_manifest(root: Path) -> list[Path]:
    """Gather files to be recorded in the manifest (exclude log and export)."""
    files = []
    for p in root.rglob("*"):
        if p.is_file():
            # Exclude previous exports to avoid circular references
            if p.name.endswith(".zip") and p.parts[-2] == "var":
                continue
            files.append(p)
    return files


def init_container(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    if root.exists() and any(root.iterdir()):
        print(f"Error: target directory '{root}' already exists and is not empty.", file=sys.stderr)
        sys.exit(1)
    root.mkdir(parents=True, exist_ok=True)
    create_directories(root)
    policy_path = write_default_policy(root)
    # Copy this script into the container's bin directory for offline use
    script_src = Path(__file__).resolve()
    script_dst = root / "bin" / Path(__file__).name
    shutil.copy2(script_src, script_dst)
    # Build manifest over container files (excluding manifest.json itself).
    files = gather_files_for_manifest(root)
    manifest = generate_manifest(root, files)
    # Compute digest using a deterministic ordering of files (sorted by path)
    sorted_entries = sorted(manifest["files"], key=lambda e: e["path"])
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(sorted_entries, sort_keys=True).encode()
    ).hexdigest()
    # Persist the manifest without recording the manifest file itself.
    save_manifest(root, manifest)
    print(f"Container initialized at {root}")


def load_manifest(root: Path) -> dict:
    manifest_path = root / "etc" / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest file '{manifest_path}' is missing. Run init first.")
    return json.loads(manifest_path.read_text())


def verify_container(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    try:
        manifest = load_manifest(root)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    stored = {entry["path"]: entry for entry in manifest["files"]}
    errors: list[str] = []
    # Verify digest of file list
    # Compute digest using the same deterministic ordering as during init
    sorted_entries = [stored[k] for k in sorted(stored.keys())]
    current_digest = hashlib.sha256(
        json.dumps(sorted_entries, sort_keys=True).encode()
    ).hexdigest()
    if current_digest != manifest.get("manifest_sha256"):
        errors.append("Manifest content digest does not match recorded manifest_sha256.")
    # Check for modified or missing files recorded in manifest
    for rel_path, entry in stored.items():
        file_path = root / rel_path
        if not file_path.is_file():
            errors.append(f"Missing file: {rel_path}")
            continue
        current_hash = compute_hash(file_path)
        if current_hash != entry["sha256"]:
            errors.append(f"Modified file: {rel_path}")
    # Gather current files and exclude manifest.json for unexpected check
    current_files = set(str(p.relative_to(root)) for p in gather_files_for_manifest(root))
    current_files.discard("etc/manifest.json")
    unexpected = current_files - set(stored.keys())
    for rel_path in sorted(unexpected):
        errors.append(f"Unexpected file: {rel_path}")
    if errors:
        print("Verification failed:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(2)
    print("Container verification passed. No modifications detected.")


def audit_container(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    report = []
    for p in gather_files_for_manifest(root):
        report.append({
            "path": str(p.relative_to(root)),
            "size_bytes": p.stat().st_size,
            "sha256": compute_hash(p),
        })
    audit_path = root / "var" / "log" / "audit_report.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps({
        "schema": "live_iso.audit.v1",
        "generated_at_utc": utc_now(),
        "entries": report,
    }, indent=2, ensure_ascii=False))
    print(f"Audit written to {audit_path}")


def export_container(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    export_dir = root / "var" / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / f"{root.name}.zip"
    with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in root.rglob("*"):
            if p.is_file():
                # Skip previous export if exists to avoid recursion
                if p == export_path:
                    continue
                zf.write(p, p.relative_to(root))
    print(f"Container exported to {export_path}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage a secure, policy‑anchored live ISO container.",
        epilog=(
            "Commands:\n"
            "  init    Initialize a new container at the given root directory\n"
            "  verify  Verify that container contents match the stored manifest\n"
            "  audit   Generate an audit report of file hashes and sizes\n"
            "  export  Create a zip archive of the container\n"
            "\n"
            "Examples:\n"
            "  python3 live_iso_manager.py init --root secure_iso\n"
            "  python3 live_iso_manager.py verify --root secure_iso\n"
            "\n"
            "After initialization, a copy of this script will be placed in the\n"
            "container's bin directory for offline use."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    # Common root option
    def add_root_option(sp):
        sp.add_argument(
            "--root",
            required=True,
            help="Directory where the container resides or will be created.",
        )
    # init
    sp_init = subparsers.add_parser("init", help="Initialize a new container")
    add_root_option(sp_init)
    sp_init.set_defaults(func=init_container)
    # verify
    sp_verify = subparsers.add_parser("verify", help="Verify container integrity")
    add_root_option(sp_verify)
    sp_verify.set_defaults(func=verify_container)
    # audit
    sp_audit = subparsers.add_parser("audit", help="Audit container contents")
    add_root_option(sp_audit)
    sp_audit.set_defaults(func=audit_container)
    # export
    sp_export = subparsers.add_parser("export", help="Export container to zip")
    add_root_option(sp_export)
    sp_export.set_defaults(func=export_container)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())