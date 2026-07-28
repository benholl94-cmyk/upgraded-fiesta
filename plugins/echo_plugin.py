
# Strukturiertes Logging (Plan B.3). Idempotent -- mehrfach
# aufgerufen waere ein No-Op, weil `_configure_once()` einen
# Flag abfragt, bevor sie Handler anhaengt.
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PARENT = _os.path.dirname(_HERE)
_SCRIPTS = _os.path.join(_PARENT, 'scripts')
if _SCRIPTS not in _sys.path:
    _sys.path.insert(0, _SCRIPTS)
from _log import get_logger
log = get_logger(__name__)
#!/usr/bin/env python3
"""Example hm-plugins plugin.

Protocol: read one PluginRequest JSON line from stdin, write one
PluginResponse JSON line to stdout. See crates/hm-sdk for the Rust types
this mirrors.
"""

import json
import sys


def main() -> int:
    line = sys.stdin.readline()
    request = json.loads(line)
    response = {
        "ok": True,
        "result": {
            "echoed_task_type": request.get("task_type"),
            "echoed_objective": request.get("objective"),
            "echoed_payload": request.get("payload"),
        },
        "message": "echo plugin executed",
    }
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
