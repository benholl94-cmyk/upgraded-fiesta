# Sys/OS Mirror And Remote Access Runbook

This toolkit provides a complete local mirror and read-only remote-access surface for the generated `local_usr/sys` control-plane.

It uses only Python standard-library modules and local files.

## Build

```sh
python3 local_usr/sys/bin/build_sys_os_remote.py
```

## Mirror

```sh
python3 local_usr/sys/bin/sys_os_mirror.py init
python3 local_usr/sys/bin/sys_os_mirror.py mirror
python3 local_usr/sys/bin/sys_os_mirror.py validate
```

Generated outputs:

| Path | Role |
| --- | --- |
| `local_usr/sys/etc/sys_os_mirror.config.json` | Mirror config |
| `local_usr/sys/var/lib/sys_os_mirror/manifest.json` | Content inventory |
| `local_usr/sys/var/lib/sys_os_mirror/restore_plan.json` | Restore procedure |
| `local_usr/sys/var/lib/sys_os_mirror/archives/*.tar.gz` | Mirror archive |
| `local_usr/sys/var/run/sys_os_mirror.validation.json` | Validation result |

## Remote Access

Initialize and validate:

```sh
python3 local_usr/sys/bin/remote_access_gateway.py init
python3 local_usr/sys/bin/remote_access_gateway.py validate
```

Start local gateway:

```sh
python3 local_usr/sys/bin/remote_access_gateway.py serve
```

Default endpoint:

```text
http://127.0.0.1:8765
```

Read the generated bearer token on the same machine:

```sh
python3 - <<'PY'
from pathlib import Path
print(Path("local_usr/sys/etc/remote_access.token").read_text().strip())
PY
```

Health check:

```sh
curl http://127.0.0.1:8765/health
```

Authenticated examples:

```sh
TOKEN="$(python3 - <<'PY'
from pathlib import Path
print(Path("local_usr/sys/etc/remote_access.token").read_text().strip())
PY
)"
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/manifest
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/mirror/validation
curl -H "Authorization: Bearer $TOKEN" -o latest_sys_os_mirror.tar.gz http://127.0.0.1:8765/archive/latest
```

## Boundaries

- The gateway is read-only.
- Shell execution is disabled.
- Default bind is loopback: `127.0.0.1`.
- External target credentials are not generated.
- Sensitive-name files are excluded from mirror content.

## Restore

Use the generated restore plan:

```sh
python3 -m json.tool local_usr/sys/var/lib/sys_os_mirror/restore_plan.json
```

Validate archive hash before any extraction:

```sh
python3 - <<'PY'
import hashlib, json
from pathlib import Path
plan = json.loads(Path("local_usr/sys/var/lib/sys_os_mirror/restore_plan.json").read_text())
archive = Path(plan["archive_path"])
h = hashlib.sha256(archive.read_bytes()).hexdigest()
print({"ok": h == plan["archive_sha256"], "archive": str(archive), "sha256": h})
PY
```
