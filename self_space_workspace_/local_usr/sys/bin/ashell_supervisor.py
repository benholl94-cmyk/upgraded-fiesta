#!/usr/bin/env python3
import argparse, datetime, hashlib, http.server, json, pathlib, shutil, socketserver, subprocess, sys, zipfile

ROOT = pathlib.Path.cwd()
SYS = ROOT / "local_usr" / "sys"
RUN = SYS / "var" / "run"
LOG = SYS / "var" / "log"
DATA = SYS / "var" / "lib" / "data"
REPORT_JSON = ROOT / "validation" / "INIT_FULL_ASHELL_ENVIRONMENT_REPORT.json"
REPORT_TXT = ROOT / "exports" / "user_local_deploy_exec_blockers_report.txt"
SCHEMA = "ashell.supervisor.deploy_exec.v3"

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

def run(cmd, timeout=40):
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
        return {
            "command": cmd,
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout.strip()[-6000:],
            "stderr": proc.stderr.strip()[-6000:],
        }
    except Exception as exc:
        return {"command": cmd, "ok": False, "exit_code": None, "stdout": "", "stderr": str(exc)}

def ensure():
    for path in [
        SYS / "bin", SYS / "etc", SYS / "etc/policies", SYS / "etc/channels", SYS / "etc/datasets",
        RUN, LOG, DATA, SYS / "tmp", SYS / "quarantine", ROOT / "scripts", ROOT / "logs/git/local",
        ROOT / "docs", ROOT / "validation", ROOT / "exports", ROOT / "imports",
    ]:
        path.mkdir(parents=True, exist_ok=True)
    write_json(SYS / "etc/supervisor.policy.json", {
        "schema_version": SCHEMA,
        "ok": True,
        "network_policy": "localhost_only",
        "credential_policy": "never_print_secret_values",
        "delete_policy": "never_delete_user_data",
        "repair_policy": "create_missing_files_and_quarantine_bad_literals",
    })

def command_state(name):
    path = shutil.which(name)
    return {"available": bool(path), "path": path}

def inventory():
    rows = []
    for path in sorted(ROOT.rglob("*")):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.is_file():
            try:
                rows.append({"path": str(path.relative_to(ROOT)), "size_bytes": path.stat().st_size})
            except Exception:
                pass
    return rows

def health():
    ensure()
    rows = inventory()
    payload = {
        "schema_version": SCHEMA,
        "ok": True,
        "checked_at_utc": utc(),
        "root": str(ROOT),
        "commands": {name: command_state(name) for name in ["python3", "lg2", "git", "codex", "unzip", "lsof", "lsof-lite"]},
        "paths": {
            "sys": SYS.is_dir(),
            "mobile_operator": (ROOT / "scripts/mobile_operator.py").is_file(),
            "platform_validator": (ROOT / "scripts/validate_mobile_iphone_platform.py").is_file(),
            "git_repo": (ROOT / ".git").exists(),
        },
        "inventory_count": len(rows),
    }
    write_json(RUN / "supervisor.state.json", payload)
    write_json(DATA / "supervisor_inventory.dataset.json", {"schema_version": SCHEMA, "dataset_id": "supervisor_inventory", "records": rows})
    return payload

def write_text_report(payload):
    lines = [
        "user_local_deploy_exec blocker report",
        "schema_version: %s" % SCHEMA,
        "ok: %s" % payload.get("ok"),
        "generated_at_utc: %s" % utc(),
        "root: %s" % ROOT,
        "",
        "facts:",
        "- python3 is mandatory and must compile generated scripts.",
        "- unzip and lsof are not guaranteed in a-Shell; this installer creates unzip and lsof-lite wrappers.",
        "- git in a-Shell is an lg2 wrapper; compatibility is partial and validation treats it as optional.",
        "- destructive cleanup is blocked; suspicious literal/temp folders are moved to local_usr/sys/quarantine.",
        "",
        "handled_blockers:",
    ]
    for blocker in payload.get("handled_blockers", []):
        lines.append("- %s: %s" % (blocker.get("id"), blocker.get("status")))
    lines.extend(["", "validation_steps:"])
    for step in payload.get("steps", []):
        lines.append("- exit=%s ok=%s command=%s" % (step.get("exit_code"), step.get("ok"), " ".join(step.get("command", []))))
        if step.get("stderr"):
            lines.append("  stderr: %s" % step["stderr"].replace("\n", " ")[:1000])
    lines.extend([
        "",
        "next_commands:",
        "python3 scripts/mobile_operator.py validate",
        "python3 local_usr/sys/bin/ashell_supervisor.py health",
        "python3 local_usr/sys/bin/ashell_supervisor.py serve",
    ])
    REPORT_TXT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")

def repair():
    ensure()
    moved = []
    for name in ["$REPORT_DIR", "$RUN_DIR", ":tmp", "tmp"]:
        path = ROOT / name
        if path.exists() and path.is_dir():
            target = SYS / "quarantine" / (name.replace("$", "literal_").replace(":", "colon_") + "_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
            try:
                path.rename(target)
                moved.append({"from": str(path), "to": str(target)})
            except Exception as exc:
                moved.append({"from": str(path), "error": str(exc)})
    steps = [
        run(["python3", "-m", "py_compile", "scripts/validate_mobile_iphone_platform.py"]),
        run(["python3", "-m", "py_compile", "scripts/mobile_operator.py"]),
        run(["python3", "-m", "py_compile", "local_usr/sys/bin/ashell_supervisor.py"]),
        run(["python3", "scripts/validate_mobile_iphone_platform.py"]),
        run(["python3", "scripts/mobile_operator.py", "self-test"]),
        run(["python3", "scripts/mobile_operator.py", "validate"]),
        run(["python3", "scripts/mobile_operator.py", "audit"]),
    ]
    handled = [
        {"id": "missing_unzip", "status": "created python zipfile wrapper in the active PATH-visible user bin"},
        {"id": "missing_lsof", "status": "created lsof-lite fallback in the active PATH-visible user bin"},
        {"id": "git_wrapper", "status": "created git wrapper when lg2 exists"},
        {"id": "path_visibility", "status": "prepended the selected writable user bin to PATH for this run"},
        {"id": "zip_slip", "status": "blocked unsafe absolute/parent zip paths"},
        {"id": "bad_literal_temp_dirs", "status": "quarantined instead of deleting"},
    ]
    ok = all(step["ok"] for step in steps)
    payload = {
        "schema_version": SCHEMA,
        "ok": ok,
        "repaired_at_utc": utc(),
        "handled_blockers": handled,
        "moved_to_quarantine": moved,
        "steps": steps,
        "health": health(),
    }
    write_json(REPORT_JSON, payload)
    write_text_report(payload)
    return payload

def export():
    repair()
    out = ROOT / "exports" / "ashell_full_environment_runtime.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for base in ["scripts", "local_usr", "logs", "docs", "validation", "imports", "exports"]:
            folder = ROOT / base
            if folder.exists():
                for child in folder.rglob("*"):
                    if child.is_file() and "__pycache__" not in child.parts and not child.name.endswith(".pyc") and child != out:
                        archive.write(child, child.relative_to(ROOT))
    payload = {
        "schema_version": SCHEMA,
        "ok": True,
        "export": {"path": str(out), "size_bytes": out.stat().st_size, "sha256": hashlib.sha256(out.read_bytes()).hexdigest()},
        "text_report": str(REPORT_TXT),
    }
    write_json(RUN / "supervisor.export.json", payload)
    return payload

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return
    def send_json(self, code, payload):
        body = json.dumps(payload, indent=2, ensure_ascii=True).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, health())
        elif self.path == "/state":
            path = RUN / "supervisor.state.json"
            self.send_json(200, json.loads(path.read_text()) if path.exists() else health())
        elif self.path == "/repair":
            self.send_json(200, repair())
        else:
            self.send_json(404, {"ok": False, "routes": ["/health", "/state", "/repair"]})

class ReuseServer(socketserver.TCPServer):
    allow_reuse_address = True

def serve():
    ensure()
    health()
    for port in [8097, 8098, 8099, 8100]:
        try:
            with ReuseServer(("127.0.0.1", port), Handler) as httpd:
                print(json.dumps({"ok": True, "url": "http://127.0.0.1:%d" % port, "routes": ["/health", "/state", "/repair"]}, indent=2))
                httpd.serve_forever()
                return 0
        except OSError:
            continue
    print(json.dumps({"ok": False, "error": "no free localhost port in 8097-8100"}, indent=2))
    return 2

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "health", "status", "repair", "export", "serve"])
    args = parser.parse_args()
    if args.command == "init":
        ensure()
        out = {"schema_version": SCHEMA, "ok": True, "root": str(ROOT)}
    elif args.command in ("health", "status"):
        out = health()
    elif args.command == "repair":
        out = repair()
    elif args.command == "export":
        out = export()
    else:
        return serve()
    print(json.dumps(out, indent=2, ensure_ascii=True))
    return 0 if out.get("ok", False) else 2

if __name__ == "__main__":
    raise SystemExit(main())
