#!/usr/bin/env python3
"""auto_rollback_ctx.py — Entscheidungshelfer fuer Auto-Rollback.

## Warum ein Allowlist und nicht eine Blockliste

GitHub Actions kann eine `workflow_run` mit den Conclusiones `success`,
`failure`, `cancelled`, `timed_out`, `action_required`, `neutral`, `skipped`,
`stale`, `startup_failure` abschliessen. Eine Blockliste auf `failure`
schluckt stillschweigend alles, was nicht exakt `failure` ist: ein
`cancelled` oder `timed_out` aus einem Abbruch des Runners landet im
Grunde als Erfolg, weil die Pruefung nicht zutrifft. Genau das ist in
HANDOFF.md s2-5 dokumentiert, und die Folge war ein gemergter Commit, der
eigentlich zurueckgenommen werden musste.

Diese Datei bildet die Entscheidung explizit ab: jede Conclusio bekommt
eine Aktion, und eine unbekannte Conclusio faellt auf `HOLD` zurueck.
Default ist `HOLD`, niemals `REVERT` — ein "weiss nicht" darf niemals
einen Force-Push ausloesen, nur ein "weiss es und es ist rot" darf es.

    REVERT  — der letzte Merge auf main wird rueckgaengig gemacht
    HOLD    — Aktion wird blockiert, bis ein Mensch entscheidet
    NOOP    — es ist nichts zu tun

Der Auto-Rollback-Workflow uebergibt die Conclusio per env, dieses Skript
entscheidet. Der Workflow laeuft zunaechst nur ueber `workflow_dispatch`
(siehe `auto-rollback.yml`); sobald die Mechanik live verifiziert ist,
kann die `workflow_run`-Trigger-Bedingung freigeschaltet werden.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Literal

Action = Literal["REVERT", "HOLD", "NOOP"]

# Allowlist, nicht Blockliste. Jede in GitHub Actions moegliche Conclusio
# ist hier abgebildet; fehlt eine, faellt `decide()` auf `HOLD` zurueck.
ALLOWLIST: dict[str, Action] = {
    "success": "NOOP",
    "skipped": "NOOP",
    "neutral": "NOOP",
    "failure": "REVERT",
    "cancelled": "HOLD",
    "timed_out": "HOLD",
    "action_required": "HOLD",
    "startup_failure": "HOLD",
    "stale": "HOLD",
}


def decide(conclusion: str) -> Action:
    """Mappt eine GitHub-Workflow-Conclusio auf eine Rollback-Aktion.

    Unbekannte oder leere Conclusio: `HOLD`. Das ist die sichere Variante;
    ein "weiss nicht" loest nie einen REVERT aus.
    """
    key = (conclusion or "").strip().lower()
    if not key:
        return "HOLD"
    return ALLOWLIST.get(key, "HOLD")


def from_env() -> tuple[str, Action]:
    """Liest `CONCLUSION` aus der Umgebung und entscheidet.

    Returns (conclusion, action). Fuer CI-Aufrufer ohne env: `from_env()`
    gibt `('', 'HOLD')` zurueck, nicht `REVERT`.
    """
    conclusion = os.environ.get("CONCLUSION", "").strip()
    return conclusion, decide(conclusion)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument(
        "--conclusion",
        help="GitHub-Workflow-Conclusio (sonst aus $CONCLUSION).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Eine JSON-Zeile {conclusion, action} ausgeben.",
    )
    p.add_argument(
        "--show-allowlist",
        action="store_true",
        help="Alle Allowlist-Eintraege ausgeben und beenden.",
    )
    args = p.parse_args()

    if args.show_allowlist:
        json.dump(ALLOWLIST, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    conclusion = (args.conclusion if args.conclusion is not None else os.environ.get("CONCLUSION", "")).strip()
    action = decide(conclusion)
    if args.json:
        json.dump({"conclusion": conclusion, "action": action}, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(f"conclusion={conclusion!r} action={action}")
    # Exit 0 bei NOOP/HOLD; Exit 2 nur bei REVERT, damit ein Cron-Lauf
    # im stillen Erfolgsfall nicht rot wird, ein REVERT aber sichtbar ist.
    return 2 if action == "REVERT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
