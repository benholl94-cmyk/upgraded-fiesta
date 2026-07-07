# pbpaste > ashell_supervisor_repair_onebash.sh
# sh ashell_supervisor_repair_onebash.sh

set -u

ROOT="$PWD"
SYS="local_usr/sys"
BIN="$SYS/bin"
ETC="$SYS/etc"
VAR="$SYS/var"
RUN="$VAR/run"
LOG="$VAR/log"
LIB="$VAR/lib"
DATA="$LIB/data"
CHANNELS="$LIB/channels"
LIVE="$LIB/live_sets"
SUPERVISOR="$BIN/ashell_supervisor.py"
REPORT="validation/ASHELL_SUPERVISOR_REPAIR_REPORT.json"

mkdir -p "$BIN"
mkdir -p "$ETC"
mkdir -p "$ETC/policies"
mkdir -p "$ETC/channels"
mkdir -p "$ETC/datasets"
mkdir -p "$RUN"
mkdir -p "$LOG"
mkdir -p "$DATA"
mkdir -p "$CHANNELS"
mkdir -p "$LIVE"
mkdir -p "$SYS/tmp"
mkdir -p "$SYS/quarantine"
mkdir -p scripts
mkdir -p logs/git/local
mkdir -p docs
mkdir -p validation
mkdir -p exports

if [ -d '$REPORT_DIR' ]; then
  mv '$REPORT_DIR' "$SYS/quarantine/literal_REPORT_DIR_$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
fi

if [ -d '$RUN_DIR' ]; then
  mv '$RUN_DIR' "$SYS/quarantine/literal_RUN_DIR_$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
fi

if [ -d './tmp' ]; then
  mv './tmp' "$SYS/quarantine/local_tmp_$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
fi

cat > scripts/validate_mobile_iphone_platform.py <<'PY'
#!/usr/bin/env python3
import datetime, json, pathlib, platform, shutil, sys
root = pathlib.Path.cwd()
payload = {
  "schema_version": "ashell.platform.validation.v1",
  "ok": True,
  "validated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z"),
  "root": str(root),
  "python": sys.version.split()[0] + ("+" if "+" in sys.version else ""),
  "platform": platform.platform(),
  "is_ios_ashell_hint": "/private/var/mobile/" in str(root) or "iPhone" in platform.platform(),
  "commands": {
    "python3": shutil.which("python3"),
    "lg2": shutil.which("lg2"),
    "codex": shutil.which("codex")
  },
  "paths": {
    "scripts": (root / "scripts").is_dir(),
    "local_usr_sys": (root / "local_usr" / "sys").is_dir(),
    "git": (root / ".git").exists()
  }
}
print(json.dumps(payload, indent=2))
PY
chmod +x scripts/validate_mobile_iphone_platform.py

cat > scripts/mobile_operator.py <<'PY'
#!/usr/bin/env python3
import argparse, datetime, hashlib, json, pathlib, platform, shutil, subprocess, sys, zipfile

ROOT = pathlib.Path.cwd()
SYS = ROOT / "local_usr" / "sys"
RUN = SYS / "var" / "run"
LOG = SYS / "var" / "log"
DATA = SYS / "var" / "lib" / "data"
SCHEMA = "ashell.mobile_operator.production.v1"

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z")

def h(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=True, separators=(",",":")).encode()).hexdigest()

def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("written_at_utc", utc())
    payload["content_sha256"] = h({k:v for k,v in payload.items() if k != "content_sha256"})
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")

def append_jsonl(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("captured_at_utc", utc())
    payload["event_sha256"] = h(payload)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n")

def run(cmd):
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=30)
        return {"command": cmd, "ok": p.returncode == 0, "exit_code": p.returncode, "stdout": p.stdout.strip()[-4000:], "stderr": p.stderr.strip()[-4000:]}
    except FileNotFoundError:
        return {"command": cmd, "ok": False, "exit_code": None, "stdout": "", "stderr": "command not found"}
    except subprocess.TimeoutExpired:
        return {"command": cmd, "ok": False, "exit_code": None, "stdout": "", "stderr": "timeout"}

def state():
    lg2 = shutil.which("lg2")
    codex = shutil.which("codex")
    git_present = (ROOT / ".git").exists()
    return {
      "schema_version": SCHEMA,
      "root": str(ROOT),
      "python": sys.version.split()[0] + ("+" if "+" in sys.version else ""),
      "platform": platform.platform(),
      "commands": {"python3": shutil.which("python3"), "lg2": lg2, "codex": codex},
      "repo": {
        "git_present": git_present,
        "lg2_status": run(["lg2","status"]) if lg2 and git_present else {"ok": False, "stderr": "skipped: .git missing or lg2 unavailable"}
      },
      "paths": {
        "sys": SYS.is_dir(),
        "run": RUN.is_dir(),
        "log": LOG.is_dir(),
        "data": DATA.is_dir()
      }
    }

def init():
    for p in [SYS/"bin", SYS/"etc", SYS/"etc/policies", SYS/"etc/channels", SYS/"etc/datasets", RUN, LOG, DATA, SYS/"var/lib/channels", SYS/"var/lib/live_sets", SYS/"tmp", SYS/"quarantine"]:
        p.mkdir(parents=True, exist_ok=True)
    manifest = {
      "schema_version": SCHEMA,
      "manifest_id": "iphone_ashell_supervised_workspace",
      "root": str(ROOT),
      "sys_root": str(SYS),
      "policy": {
        "network_required": False,
        "shell_exec_supervised": True,
        "delete_untrusted": False,
        "quarantine_instead_of_delete": True,
        "codex_required": False,
        "git_repo_required": False
      },
      "supervisor": "local_usr/sys/bin/ashell_supervisor.py"
    }
    write_json(SYS/"etc/sys_manifest.json", manifest)
    append_jsonl(LOG/"mobile_operator.events.jsonl", {"event_type": "init", "ok": True})
    return {"ok": True, "manifest": manifest}

def self_test():
    init()
    st = state()
    ok = bool(shutil.which("python3")) and (ROOT/"scripts/mobile_operator.py").is_file()
    out = {"schema_version": SCHEMA, "ok": ok, "checked_at_utc": utc(), "state": st, "errors": [] if ok else ["python3 or mobile_operator missing"]}
    write_json(RUN/"mobile_operator.self_test.json", out)
    append_jsonl(LOG/"mobile_operator.events.jsonl", {"event_type": "self-test", "ok": ok})
    return out

def validate():
    init()
    st = state()
    errors = []
    warnings = []
    if not shutil.which("python3"):
        errors.append("python3 missing")
    if not shutil.which("lg2"):
        warnings.append("lg2 missing; git operations disabled")
    if not (ROOT/".git").exists():
        warnings.append("current workspace is not a git repo; running in Documents-supervised mode")
    for rel in ["scripts/validate_mobile_iphone_platform.py", "scripts/mobile_operator.py", "local_usr/sys/bin/ashell_supervisor.py"]:
        if not (ROOT/rel).exists():
            errors.append(rel + " missing")
    out = {"schema_version": SCHEMA, "ok": not errors, "validated_at_utc": utc(), "errors": errors, "warnings": warnings, "state": st}
    write_json(RUN/"mobile_operator.validation.json", out)
    write_json(DATA/"runtime_state.dataset.json", {"schema_version": SCHEMA, "dataset_id": "runtime_state", "records": st})
    append_jsonl(LOG/"mobile_operator.events.jsonl", {"event_type": "validate", "ok": out["ok"], "errors": errors, "warnings": warnings})
    return out

def audit():
    init()
    records = []
    for p in sorted(ROOT.rglob("*")):
        if ".git" in p.parts or "__pycache__" in p.parts:
            continue
        if p.is_file():
            try:
                records.append({"path": str(p.relative_to(ROOT)), "size_bytes": p.stat().st_size})
            except Exception:
                pass
    out = {"schema_version": SCHEMA, "ok": True, "audited_at_utc": utc(), "file_count": len(records), "files": records[:1000], "state": state()}
    write_json(RUN/"mobile_operator.audit.json", out)
    write_json(DATA/"path_inventory.dataset.json", {"schema_version": SCHEMA, "dataset_id": "path_inventory", "records": records})
    append_jsonl(LOG/"mobile_operator.events.jsonl", {"event_type": "audit", "ok": True, "file_count": len(records)})
    return out

def export():
    audit()
    out_path = ROOT / "exports" / "ashell_supervised_workspace.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base in ["scripts", "local_usr", "logs", "docs", "validation"]:
            p = ROOT / base
            if not p.exists():
                continue
            for child in p.rglob("*"):
                if child.is_file() and "__pycache__" not in child.parts and not child.name.endswith(".pyc"):
                    z.write(child, child.relative_to(ROOT))
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    result = {"schema_version": SCHEMA, "ok": True, "export": {"path": str(out_path), "size_bytes": out_path.stat().st_size, "sha256": digest}}
    write_json(RUN/"mobile_operator.export.json", result)
    append_jsonl(LOG/"mobile_operator.events.jsonl", {"event_type": "export", "ok": True, "sha256": digest})
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["init","self-test","validate","audit","status","export"])
    a = ap.parse_args()
    if a.command == "init":
        out = init()
    elif a.command == "self-test":
        out = self_test()
    elif a.command == "validate":
        out = validate()
    elif a.command == "audit":
        out = audit()
    elif a.command == "export":
        out = export()
    else:
        out = {"schema_version": SCHEMA, "ok": True, "status": state()}
    print(json.dumps(out, indent=2, ensure_ascii=True))
    return 0 if out.get("ok", True) else 2

if __name__ == "__main__":
    raise SystemExit(main())
PY
chmod +x scripts/mobile_operator.py

cat > logs/git/local/streampipe.cli <<'PY'
#!/usr/bin/env python3
import datetime, hashlib, json, pathlib, shutil, subprocess, sys, uuid
ROOT = pathlib.Path.cwd()
STATE = ROOT / "logs" / "git" / "local"
EVENTS = STATE / "events.jsonl"
SCHEMA = "streampipe.local.git.v1"

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z")

def h(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=True, separators=(",",":")).encode()).hexdigest()

def run(cmd):
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=20)
        return {"command": cmd, "ok": p.returncode == 0, "exit_code": p.returncode, "stdout": p.stdout.strip()[-4000:], "stderr": p.stderr.strip()[-4000:]}
    except Exception as e:
        return {"command": cmd, "ok": False, "exit_code": None, "stdout": "", "stderr": str(e)}

def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")

def append(payload):
    STATE.mkdir(parents=True, exist_ok=True)
    payload["event_sha256"] = h(payload)
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n")

def capture():
    tool = "lg2" if shutil.which("lg2") else None
    cmds = {}
    if tool and (ROOT/".git").exists():
        for name, args in {"status":["status"], "branch":["branch"], "log":["log"]}.items():
            cmds[name] = run([tool] + args)
    ev = {"schema_version": SCHEMA, "event_uuid": str(uuid.uuid4()), "event_type": "git_snapshot", "captured_at_utc": utc(), "repo_root": str(ROOT), "tool": tool, "git_present": (ROOT/".git").exists(), "commands": cmds}
    append(ev)
    write(STATE/"latest_event.json", ev)
    return ev

def validate():
    valid = 0
    invalid = 0
    if EVENTS.exists():
        for line in EVENTS.read_text().splitlines():
            if not line.strip():
                continue
            try:
                json.loads(line)
                valid += 1
            except Exception:
                invalid += 1
    out = {"schema_version": SCHEMA, "ok": invalid == 0, "events": {"valid": valid, "invalid": invalid}, "git_present": (ROOT/".git").exists(), "lg2": shutil.which("lg2")}
    write(STATE/"validation.json", out)
    return out

cmd = sys.argv[1] if len(sys.argv) > 1 else "capture"
if cmd == "validate":
    print(json.dumps(validate(), indent=2))
elif cmd == "status":
    print(json.dumps({"ok": True, "state_dir": str(STATE), "events": str(EVENTS)}, indent=2))
else:
    print(json.dumps(capture(), indent=2))
PY
chmod +x logs/git/local/streampipe.cli

cat > "$SUPERVISOR" <<'PY'
#!/usr/bin/env python3
import argparse, datetime, hashlib, http.server, json, os, pathlib, shutil, socketserver, subprocess, sys, threading, time, zipfile

ROOT = pathlib.Path.cwd()
SYS = ROOT / "local_usr" / "sys"
RUN = SYS / "var" / "run"
LOG = SYS / "var" / "log"
DATA = SYS / "var" / "lib" / "data"
CHANNELS = SYS / "var" / "lib" / "channels"
LIVE = SYS / "var" / "lib" / "live_sets"
CONFIG = SYS / "etc" / "supervisor.config.json"
STATE = RUN / "supervisor.state.json"
REPORT = ROOT / "validation" / "ASHELL_SUPERVISOR_REPAIR_REPORT.json"
SCHEMA = "ashell.supervisor.production.v1"

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z")

def h(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=True, separators=(",",":")).encode()).hexdigest()

def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("written_at_utc", utc())
    payload["content_sha256"] = h({k:v for k,v in payload.items() if k != "content_sha256"})
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")

def append_jsonl(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("captured_at_utc", utc())
    payload["event_sha256"] = h(payload)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n")

def run(cmd, timeout=45):
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
        return {"command": cmd, "ok": p.returncode == 0, "exit_code": p.returncode, "stdout": p.stdout.strip()[-5000:], "stderr": p.stderr.strip()[-5000:]}
    except FileNotFoundError:
        return {"command": cmd, "ok": False, "exit_code": None, "stdout": "", "stderr": "command not found"}
    except subprocess.TimeoutExpired:
        return {"command": cmd, "ok": False, "exit_code": None, "stdout": "", "stderr": "timeout"}

def ensure():
    for p in [SYS/"bin", SYS/"etc", SYS/"etc/policies", SYS/"etc/channels", SYS/"etc/datasets", RUN, LOG, DATA, CHANNELS, LIVE, SYS/"tmp", SYS/"quarantine", ROOT/"scripts", ROOT/"logs/git/local", ROOT/"docs", ROOT/"validation", ROOT/"exports"]:
        p.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": SCHEMA,
        "bind": "127.0.0.1",
        "port": 8097,
        "read_only_http": True,
        "shell_execution_http": False,
        "restart_policy": "manual",
        "health_interval_seconds": 30,
        "required_commands": ["python3"],
        "optional_commands": ["lg2", "codex"]
    }
    write_json(CONFIG, config)
    write_json(SYS/"etc/supervisor.policy.json", {
        "schema_version": SCHEMA,
        "delete_policy": "never_delete_user_data",
        "repair_policy": "create_missing_and_quarantine_bad_literals",
        "network_policy": "localhost_only",
        "credential_policy": "do_not_read_or_print_secret_values"
    })
    return config

def command(command, args):
    found = shutil.which(command)
    out = {"command": command, "available": bool(found), "path": found}
    if found:
        out["probe"] = run([command] + args, timeout=10)
    return out

def inventory():
    records = []
    for p in sorted(ROOT.rglob("*")):
        if ".git" in p.parts or "__pycache__" in p.parts:
            continue
        if p.is_file():
            try:
                records.append({"path": str(p.relative_to(ROOT)), "size_bytes": p.stat().st_size})
            except Exception:
                pass
    return records

def health():
    ensure()
    inv = inventory()
    facts = {
        "schema_version": SCHEMA,
        "ok": True,
        "checked_at_utc": utc(),
        "root": str(ROOT),
        "sys_root": str(SYS),
        "commands": {
            "python3": command("python3", ["--version"]),
            "lg2": command("lg2", ["version"]),
            "codex": command("codex", ["--version"])
        },
        "paths": {
            "bad_literal_REPORT_DIR": (ROOT/"$REPORT_DIR").exists(),
            "bad_literal_RUN_DIR": (ROOT/"$RUN_DIR").exists(),
            "scripts_mobile_operator": (ROOT/"scripts/mobile_operator.py").exists(),
            "scripts_validate_platform": (ROOT/"scripts/validate_mobile_iphone_platform.py").exists(),
            "streampipe": (ROOT/"logs/git/local/streampipe.cli").exists(),
            "supervisor": (ROOT/"local_usr/sys/bin/ashell_supervisor.py").exists()
        },
        "repo": {
            "git_present": (ROOT/".git").exists()
        },
        "inventory_count": len(inv)
    }
    write_json(STATE, facts)
    write_json(DATA/"supervisor_inventory.dataset.json", {"schema_version": SCHEMA, "dataset_id": "supervisor_inventory", "records": inv})
    append_jsonl(LOG/"supervisor.events.jsonl", {"event_type": "health", "ok": facts["ok"]})
    return facts

def repair():
    ensure()
    moved = []
    for name in ["$REPORT_DIR", "$RUN_DIR", "tmp"]:
        p = ROOT / name
        if p.exists() and p.is_dir():
            target = SYS / "quarantine" / (name.replace("$","literal_").replace("/","_") + "_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
            try:
                p.rename(target)
                moved.append({"from": str(p), "to": str(target)})
            except Exception as exc:
                moved.append({"from": str(p), "error": str(exc)})
    steps = [
        run(["python3","scripts/validate_mobile_iphone_platform.py"]),
        run(["python3","scripts/mobile_operator.py","self-test"]),
        run(["python3","scripts/mobile_operator.py","validate"]),
        run(["python3","scripts/mobile_operator.py","audit"]),
        run(["python3","logs/git/local/streampipe.cli","capture"]),
        run(["python3","logs/git/local/streampipe.cli","validate"])
    ]
    ok = all(s["ok"] for s in steps[:4])
    out = {"schema_version": SCHEMA, "ok": ok, "repaired_at_utc": utc(), "moved_to_quarantine": moved, "steps": steps, "health": health()}
    write_json(REPORT, out)
    append_jsonl(LOG/"supervisor.events.jsonl", {"event_type": "repair", "ok": ok})
    return out

def export_runtime():
    repair()
    out = ROOT / "exports" / "ashell_supervisor_production_runtime.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for base in ["scripts", "local_usr", "logs", "docs", "validation"]:
            p = ROOT / base
            if not p.exists():
                continue
            for child in p.rglob("*"):
                if child.is_file() and "__pycache__" not in child.parts and not child.name.endswith(".pyc"):
                    z.write(child, child.relative_to(ROOT))
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    payload = {"schema_version": SCHEMA, "ok": True, "export": {"path": str(out), "size_bytes": out.stat().st_size, "sha256": digest}}
    write_json(RUN/"supervisor.export.json", payload)
    append_jsonl(LOG/"supervisor.events.jsonl", {"event_type": "export", "ok": True, "sha256": digest})
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return payload

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        append_jsonl(LOG/"supervisor_http.events.jsonl", {"event_type": "http", "client": self.client_address[0], "message": fmt % args})
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
            self.send_json(200, json.loads(STATE.read_text()) if STATE.exists() else health())
        elif self.path == "/repair":
            self.send_json(200, repair())
        else:
            self.send_json(404, {"ok": False, "routes": ["/health", "/state", "/repair"]})

class Reuse(socketserver.TCPServer):
    allow_reuse_address = True

def serve():
    config = ensure()
    health()
    bind = config["bind"]
    port = int(config["port"])
    with Reuse((bind, port), Handler) as httpd:
        append_jsonl(LOG/"supervisor.events.jsonl", {"event_type": "serve", "bind": bind, "port": port})
        print(json.dumps({"ok": True, "bind": bind, "port": port, "routes": ["/health","/state","/repair"]}, indent=2))
        httpd.serve_forever()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["init","health","repair","status","export","serve"])
    a = ap.parse_args()
    if a.command == "init":
        out = {"ok": True, "config": ensure()}
    elif a.command == "health" or a.command == "status":
        out = health()
    elif a.command == "repair":
        out = repair()
    elif a.command == "export":
        export_runtime()
        return 0
    else:
        serve()
        return 0
    print(json.dumps(out, indent=2, ensure_ascii=True))
    return 0 if out.get("ok", True) else 2

if __name__ == "__main__":
    raise SystemExit(main())
PY
chmod +x "$SUPERVISOR"

cat > docs/ASHELL_SUPERVISOR_PRODUCTION.md <<'EOF'
# a-Shell Supervisor Production Runtime

Commands:

```sh
python3 local_usr/sys/bin/ashell_supervisor.py init
python3 local_usr/sys/bin/ashell_supervisor.py health
python3 local_usr/sys/bin/ashell_supervisor.py repair
python3 local_usr/sys/bin/ashell_supervisor.py export
python3 local_usr/sys/bin/ashell_supervisor.py serve
```

Routes when serving:

```text
http://127.0.0.1:8097/health
http://127.0.0.1:8097/state
http://127.0.0.1:8097/repair
```
EOF

cat > "$ETC/channels/supervisor.channel.json" <<'EOF'
{
  "schema_version": "ashell.supervisor.production.v1",
  "channel_id": "supervisor",
  "source": "local_usr/sys/bin/ashell_supervisor.py",
  "sink": "local_usr/sys/var/log/supervisor.events.jsonl",
  "mode": "local_only"
}
EOF

cat > "$ETC/datasets/supervisor_inventory.dataset.json" <<'EOF'
{
  "schema_version": "ashell.supervisor.production.v1",
  "dataset_id": "supervisor_inventory",
  "file": "local_usr/sys/var/lib/data/supervisor_inventory.dataset.json"
}
EOF

python3 -m py_compile scripts/validate_mobile_iphone_platform.py
python3 -m py_compile scripts/mobile_operator.py
python3 -m py_compile logs/git/local/streampipe.cli
python3 -m py_compile "$SUPERVISOR"

python3 scripts/validate_mobile_iphone_platform.py
python3 scripts/mobile_operator.py init
python3 scripts/mobile_operator.py self-test
python3 scripts/mobile_operator.py validate
python3 scripts/mobile_operator.py audit
python3 logs/git/local/streampipe.cli capture
python3 logs/git/local/streampipe.cli validate
python3 "$SUPERVISOR" repair
python3 "$SUPERVISOR" export
