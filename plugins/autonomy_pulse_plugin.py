#!/usr/bin/env python3
"""autonomy-pulse Plugin — hm-plugins-Protokoll-Brücke zu scripts/autonomy_core.py.

Liest eine JSON-Zeile aus stdin (PluginRequest), ruft autonomy_core.run_once() auf,
gibt eine JSON-Zeile auf stdout zurück (PluginResponse).
"""
from __future__ import annotations
import json
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import autonomy_core  # type: ignore

def main() -> None:
    line = sys.stdin.readline()
    try:
        _req = json.loads(line)
    except Exception:
        _req = {}

    pulse_state = autonomy_core.pulse()
    heal_actions = autonomy_core.heal()
    autonomy_core.reflect(pulse_state, heal_actions)

    result = {
        "ts": pulse_state.get("ts"),
        "alerts": pulse_state.get("alerts", []),
        "healed": len(heal_actions),
        "audit_score": pulse_state.get("audit", {}).get("score"),
    }
    ok = len(pulse_state.get("alerts", [])) == 0
    sys.stdout.write(json.dumps({"ok": ok, "result": result, "message": "autonomy-pulse complete"}) + "\n")
    sys.stdout.flush()

if __name__ == "__main__":
    main()
