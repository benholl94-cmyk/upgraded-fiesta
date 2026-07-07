#!/usr/bin/env python3
import argparse, datetime, hashlib, json, pathlib, platform, shutil, subprocess, sys, zipfile

ROOT = pathlib.Path.cwd()
SYS = ROOT / "local_usr" / "sys"
RUN = SYS / "var" / "run"
LOG = SYS / "var" / "log"
DATA = SYS / "var" / "lib" / "data"
SCHEMA = "ashell.mobile_operator.deploy_exec.v3"

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

def digest(value):
    body = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest()

def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("written_at_utc", utc())
    payload["content_sha256"] = digest({k: v for k, v in payload.items() if k != "content_sha256"})
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")

def append_event(name, payload):
    event = {"event_type": name, "captured_at_utc": utc(), **payload}
    event["event_sha256"] = digest(event)
    LOG.mkdir(parents=True, exist_ok=True)
    with (LOG / "mobile_operator.events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, ensure_ascii=True) + "\n")

def run(cmd, timeout=30):
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
        return {
            "command": cmd,
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout.strip()[-5000:],
            "stderr": proc.stderr.strip()[-5000:],
        }
    except Exception as exc:
        return {"command": cmd, "ok": False, "exit_code": None, "stdout": "", "stderr": str(exc)}

def ensure():
    for path in [
        SYS / "bin", SYS / "etc", SYS / "etc/policies", SYS / "etc/channels", SYS / "etc/datasets",
        RUN, LOG, DATA, SYS / "var/lib/channels", SYS / "var/lib/live_sets", SYS / "tmp", SYS / "quarantine",
        ROOT / "scripts", ROOT / "logs/git/local", ROOT / "docs", ROOT / "validation", ROOT / "exports", ROOT / "imports",
    ]:
        path.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": SCHEMA,
        "ok": True,
        "root": str(ROOT),
        "sys_root": str(SYS),
        "mode": "iphone_ashell_user_local_deploy_exec",
        "network_required": False,
        "delete_policy": "quarantine_instead_of_delete",
    }
    write_json(SYS / "etc/sys_manifest.json", manifest)
    append_event("ensure", {"ok": True})
    return manifest

def command_state(name):
    path = shutil.which(name)
    return {"available": bool(path), "path": path}

def state():
    lg2 = shutil.which("lg2")
    return {
        "schema_version": SCHEMA,
        "root": str(ROOT),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "commands": {name: command_state(name) for name in ["python3", "lg2", "git", "codex", "unzip", "lsof", "lsof-lite"]},
        "repo": {
            "git_present": (ROOT / ".git").exists(),
            "lg2_status": run(["lg2", "status"]) if lg2 and (ROOT / ".git").exists() else {"ok": False, "stderr": "skipped"},
        },
    }

def audit():
    ensure()
    rows = []
    for path in sorted(ROOT.rglob("*")):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.is_file():
            try:
                rows.append({"path": str(path.relative_to(ROOT)), "size_bytes": path.stat().st_size})
            except Exception:
                pass
    out = {"schema_version": SCHEMA, "ok": True, "audited_at_utc": utc(), "file_count": len(rows), "files": rows[:2000], "state": state()}
    write_json(RUN / "mobile_operator.audit.json", out)
    write_json(DATA / "path_inventory.dataset.json", {"schema_version": SCHEMA, "dataset_id": "path_inventory", "records": rows})
    append_event("audit", {"ok": True, "file_count": len(rows)})
    return out

def validate():
    ensure()
    errors = []
    warnings = []
    if not shutil.which("python3"):
        errors.append("python3 missing")
    if not shutil.which("lg2"):
        warnings.append("lg2 missing; git operations unavailable")
    if not shutil.which("unzip"):
        warnings.append("unzip command not visible in PATH")
    if not (ROOT / ".git").exists():
        warnings.append("not a git repo; Documents runtime mode active")
    for rel in ["scripts/validate_mobile_iphone_platform.py", "scripts/mobile_operator.py", "local_usr/sys/bin/ashell_supervisor.py"]:
        if not (ROOT / rel).exists():
            errors.append(rel + " missing")
    out = {"schema_version": SCHEMA, "ok": not errors, "validated_at_utc": utc(), "errors": errors, "warnings": warnings, "state": state()}
    write_json(RUN / "mobile_operator.validation.json", out)
    append_event("validate", {"ok": out["ok"], "errors": errors, "warnings": warnings})
    return out

def export():
    audit()
    out_path = ROOT / "exports" / "ashell_mobile_operator_runtime.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for base in ["scripts", "local_usr", "logs", "docs", "validation", "imports"]:
            folder = ROOT / base
            if folder.exists():
                for child in folder.rglob("*"):
                    if child.is_file() and "__pycache__" not in child.parts and not child.name.endswith(".pyc"):
                        archive.write(child, child.relative_to(ROOT))
    out = {
        "schema_version": SCHEMA,
        "ok": True,
        "export": {"path": str(out_path), "size_bytes": out_path.stat().st_size, "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()},
    }
    write_json(RUN / "mobile_operator.export.json", out)
    append_event("export", {"ok": True, "sha256": out["export"]["sha256"]})
    return out

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "status", "validate", "audit", "export", "self-test"])
    args = parser.parse_args()
    if args.command == "init":
        out = ensure()
    elif args.command == "status":
        out = {"schema_version": SCHEMA, "ok": True, "state": state()}
    elif args.command == "audit":
        out = audit()
    elif args.command == "export":
        out = export()
    elif args.command == "self-test":
        ensure()
        out = {"schema_version": SCHEMA, "ok": True, "checked_at_utc": utc(), "state": state()}
        write_json(RUN / "mobile_operator.self_test.json", out)
        append_event("self-test", {"ok": True})
    else:
        out = validate()
    print(json.dumps(out, indent=2, ensure_ascii=True))
    return 0 if out.get("ok", False) else 2

if __name__ == "__main__":
    raise SystemExit(main())
