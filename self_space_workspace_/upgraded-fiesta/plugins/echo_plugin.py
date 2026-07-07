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
