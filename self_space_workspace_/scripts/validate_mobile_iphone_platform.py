#!/usr/bin/env python3
import datetime, json, os, pathlib, platform, shutil, sys

root = pathlib.Path.cwd()
home = pathlib.Path(os.environ.get("HOME", str(root)))
docbin = pathlib.Path(os.environ.get("ASHELL_DOCBIN", str(home / "Documents" / "bin")))
payload = {
    "schema_version": "ashell.platform.validation.v2",
    "ok": True,
    "validated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    "root": str(root),
    "python": sys.version.split()[0],
    "platform": platform.platform(),
    "commands": {
        "python3": shutil.which("python3"),
        "lg2": shutil.which("lg2"),
        "git": shutil.which("git"),
        "codex": shutil.which("codex"),
        "unzip": shutil.which("unzip"),
        "lsof": shutil.which("lsof"),
        "lsof_lite": shutil.which("lsof-lite"),
    },
    "paths": {
        "scripts": (root / "scripts").is_dir(),
        "local_usr_sys": (root / "local_usr" / "sys").is_dir(),
        "documents_bin": (home / "Documents" / "bin").is_dir(),
        "active_user_bin": docbin.is_dir(),
        "active_user_bin_path": str(docbin),
        "git_repo": (root / ".git").exists(),
    },
}
print(json.dumps(payload, indent=2, ensure_ascii=True))
