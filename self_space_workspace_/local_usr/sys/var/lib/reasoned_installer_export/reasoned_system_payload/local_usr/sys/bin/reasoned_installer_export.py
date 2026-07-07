#!/usr/bin/env python3
"""Reasoned live-datetime installer and export builder.

Risk level is not an automatic refusal. This tool separates actual mechanism
blocks from high-risk work that can continue with controls, audit, and explicit
operator gates.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import zipfile
from typing import Any


SCHEMA_VERSION = "local_usr.sys.reasoned_installer_export.v1"
ROOT = pathlib.Path(__file__).resolve().parents[3]
SYS_ROOT = ROOT / "local_usr" / "sys"
STATE_DIR = SYS_ROOT / "var" / "lib" / "reasoned_installer_export"
EXPORT_DIR = ROOT / "exports"
VALIDATION_PATH = SYS_ROOT / "var" / "run" / "reasoned_installer_export.validation.json"
STATE_PATH = STATE_DIR / "state.json"
REPORT_PATH = ROOT / "docs" / "REASONED_INSTALLER_EXPORT_REPORT.md"
INSTALLER_PATH = ROOT / "install_reasoned_system.py"

DENIED_MECHANISMS = {
    "credential_exfiltration": ["steal api key", "exfiltrate token", "dump secrets", "print private key"],
    "sandbox_or_kernel_bypass": ["sandbox bypass", "kernel patch", "jailbreak required", "amfi bypass", "tfp0"],
    "malware_persistence": ["hidden daemon", "stealth persistence", "evade detection", "unauthorized persistence"],
    "quota_or_billing_bypass": ["quota bypass", "rate limit bypass", "billing bypass", "free credit abuse"],
}

HIGH_RISK_SIGNALS = {
    "secret_handling": ["api key", "token", "secret", "credential"],
    "network_reachability": ["public", "remote", "gateway", "lan", "internet"],
    "system_boundary": ["ios", "kernel", "sandbox", "background", "extension"],
    "automation": ["autonomous", "automatic", "self-running", "out-of-app"],
    "repo_write": ["github", "main", "push", "sync", "commit"],
}

CONTROL_CATALOG = {
    "secret_handling": ["secret references only", "redacted logs", "fail closed", "rotation metadata"],
    "network_reachability": ["localhost/LAN default", "owner token", "no public tunnel by default", "healthcheck"],
    "system_boundary": ["platform boundary preserved", "no kernel modification", "no sandbox bypass", "documented entitlement requirements"],
    "automation": ["operator gate", "audit event", "bounded scheduler", "idempotent retry"],
    "repo_write": ["branch/permission check", "no secret artifacts", "commit scope manifest", "rollback note"],
}


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_json(value: Any) -> str:
    return sha256_bytes(stable_json(value).encode("utf-8"))


def write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
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


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assess_task(text: str) -> dict[str, Any]:
    lower = text.lower()
    denied_hits = {
        name: [needle for needle in needles if needle in lower]
        for name, needles in DENIED_MECHANISMS.items()
    }
    denied_hits = {name: hits for name, hits in denied_hits.items() if hits}
    signal_hits = {
        name: [needle for needle in needles if needle in lower]
        for name, needles in HIGH_RISK_SIGNALS.items()
    }
    signal_hits = {name: hits for name, hits in signal_hits.items() if hits}

    if denied_hits:
        return {
            "ok": False,
            "decision": "blocked_by_mechanism",
            "risk_level": "critical",
            "reason": "A concrete denied mechanism was requested; severity alone did not cause the block.",
            "denied_mechanisms": denied_hits,
            "risk_signals": signal_hits,
            "controls_required": [],
        }

    score = min(5, 1 + len(signal_hits))
    risk_level = ["low", "moderate", "elevated", "high", "very_high", "critical"][score]
    controls: list[str] = []
    for signal in signal_hits:
        controls.extend(CONTROL_CATALOG.get(signal, []))
    if not controls:
        controls = ["normal validation", "audit note"]
    return {
        "ok": True,
        "decision": "allowed_with_controls" if score >= 3 else "allowed",
        "risk_level": risk_level,
        "risk_score": score,
        "reason": "Risk level controls execution requirements; it is not an automatic refusal.",
        "denied_mechanisms": {},
        "risk_signals": signal_hits,
        "controls_required": sorted(set(controls)),
    }


def source_files() -> list[pathlib.Path]:
    candidates = [
        SYS_ROOT / "bin" / "api_key_passes.py",
        SYS_ROOT / "bin" / "ios_restricted_migration.py",
        SYS_ROOT / "bin" / "standalone_all_in_one_os.py",
        SYS_ROOT / "bin" / "reasoned_installer_export.py",
        SYS_ROOT / "bin" / "build_sys_os_remote.py",
        ROOT / "config" / "api-key-passes.policy.json",
        ROOT / "docs" / "API_KEY_PASSES_HARDENED_POLICY.md",
        ROOT / "docs" / "IOS_HARD_RESTRICTED_SAFE_MIGRATION.md",
        ROOT / "docs" / "STANDALONE_ALL_IN_ONE_OS_INTERPRETATION.md",
        ROOT / "docs" / "CODEX_CLAUDE_ACKNOWLEDGE.md",
    ]
    return [path for path in candidates if path.exists()]


def render_installer() -> str:
    return '''#!/usr/bin/env python3
"""Install the reasoned local_usr/sys control-plane export into a target root."""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Install reasoned local_usr/sys export.")
    parser.add_argument("--source", default="reasoned_system_payload", help="Extracted payload directory")
    parser.add_argument("--target", default=".", help="Target project root")
    args = parser.parse_args()
    source = pathlib.Path(args.source).resolve()
    target = pathlib.Path(args.target).resolve()
    if not source.is_dir():
        print({"ok": False, "reason": f"source missing: {source}"})
        return 2
    target.mkdir(parents=True, exist_ok=True)
    for child in source.rglob("*"):
        rel = child.relative_to(source)
        dest = target / rel
        if child.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        if any(part in {".git", "__pycache__"} for part in rel.parts):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, dest)
    print({"ok": True, "source": str(source), "target": str(target)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def render_report(state: dict[str, Any]) -> str:
    assessment = state["assessment"]
    lines = [
        "# Reasoned Live-DateTime Installer Export Report",
        "",
        f"Generated UTC: `{state['generated_at_utc']}`",
        "",
        "## Result",
        "",
        "Gefahrenstufe ist ein Steuerungssignal, kein automatischer Ablehnungsgrund. Blockiert wird nur ein konkret unzulässiger Mechanismus oder Zweck. Hohe Gefahr wird mit Controls, Audit, Operator-Gate und reproduzierbarem Export behandelt.",
        "",
        "## Risk Decision",
        "",
        f"- Decision: `{assessment['decision']}`",
        f"- Risk level: `{assessment['risk_level']}`",
        f"- Reason: {assessment['reason']}",
        f"- Controls: `{', '.join(assessment['controls_required'])}`",
        "",
        "## Exports",
        "",
    ]
    for item in state["exports"]:
        lines.append(f"- `{item['path']}` sha256 `{item['sha256']}`")
    lines.extend(
        [
            "",
            "## Install",
            "",
            "```sh",
            "python3 install_reasoned_system.py --source reasoned_system_payload --target .",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def build_payload() -> pathlib.Path:
    payload = STATE_DIR / "reasoned_system_payload"
    if payload.exists():
        shutil.rmtree(payload)
    for src in source_files():
        dest = payload / src.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return payload


def run_validation() -> dict[str, Any]:
    checks = []
    for command in [
        [sys.executable, "local_usr/sys/bin/api_key_passes.py", "validate"],
        [sys.executable, "local_usr/sys/bin/ios_restricted_migration.py", "validate"],
        [sys.executable, "local_usr/sys/bin/standalone_all_in_one_os.py", "validate"],
    ]:
        completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, timeout=45, check=False)
        checks.append(
            {
                "command": command,
                "exit_code": completed.returncode,
                "ok": completed.returncode == 0,
                "stdout": completed.stdout.strip()[-2000:],
                "stderr": completed.stderr.strip()[-2000:],
            }
        )
    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def export(task: str) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    assessment = assess_task(task)
    validation = run_validation()
    payload = build_payload()
    INSTALLER_PATH.write_text(render_installer(), encoding="utf-8")
    try:
        os.chmod(INSTALLER_PATH, 0o755)
    except OSError:
        pass

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tar_path = EXPORT_DIR / f"reasoned_system_payload_{stamp}.tar.gz"
    zip_path = EXPORT_DIR / f"reasoned_system_payload_{stamp}.zip"
    with tarfile.open(tar_path, "w:gz") as archive:
        archive.add(payload, arcname="reasoned_system_payload")
        archive.add(INSTALLER_PATH, arcname="install_reasoned_system.py")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(payload.parent).as_posix())
        archive.write(INSTALLER_PATH, "install_reasoned_system.py")

    state = {
        "schema_version": SCHEMA_VERSION,
        "ok": assessment["ok"] and validation["ok"],
        "generated_at_utc": utc_now(),
        "task": task,
        "assessment": assessment,
        "validation": validation,
        "installer": str(INSTALLER_PATH),
        "exports": [
            {"path": str(tar_path), "sha256": file_sha256(tar_path), "bytes": tar_path.stat().st_size},
            {"path": str(zip_path), "sha256": file_sha256(zip_path), "bytes": zip_path.stat().st_size},
        ],
        "payload_files": [str(path.relative_to(ROOT)) for path in source_files()],
    }
    write_json(STATE_PATH, state)
    REPORT_PATH.write_text(render_report(state), encoding="utf-8")
    result = validate(write=False)
    write_json(VALIDATION_PATH, result)
    return state


def validate(write: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    state = read_json(STATE_PATH)
    if not state:
        errors.append(f"missing state: {STATE_PATH}")
    if not INSTALLER_PATH.exists():
        errors.append(f"missing installer: {INSTALLER_PATH}")
    if not REPORT_PATH.exists():
        errors.append(f"missing report: {REPORT_PATH}")
    for item in state.get("exports", []) if state else []:
        path = pathlib.Path(item.get("path", ""))
        if not path.exists():
            errors.append(f"missing export: {path}")
        elif file_sha256(path) != item.get("sha256"):
            errors.append(f"export checksum mismatch: {path}")
    if state and state.get("assessment", {}).get("decision") == "blocked_by_mechanism":
        warnings.append("state records a blocked mechanism; no installer execution should be promoted")
    result = {
        "schema_version": SCHEMA_VERSION,
        "ok": not errors,
        "validated_at_utc": utc_now(),
        "state_path": str(STATE_PATH),
        "installer_path": str(INSTALLER_PATH),
        "report_path": str(REPORT_PATH),
        "errors": errors,
        "warnings": warnings,
    }
    if write:
        write_json(VALIDATION_PATH, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build reasoned installer and export bundle.")
    parser.add_argument("command", choices=["assess", "export", "validate", "status", "report"])
    parser.add_argument("--task", default="Run Codex/Claude mobile-first work with hard restrictions, high-risk controls, safe API key references, and GitHub handoff exports.")
    args = parser.parse_args(argv)
    if args.command == "assess":
        result = assess_task(args.task)
    elif args.command == "export":
        result = export(args.task)
    elif args.command == "validate":
        result = validate()
    elif args.command == "status":
        result = read_json(STATE_PATH) or {"ok": False, "reason": "not exported yet"}
    else:
        if REPORT_PATH.exists():
            print(REPORT_PATH.read_text(encoding="utf-8"))
            return 0
        result = {"ok": False, "reason": "report missing"}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
