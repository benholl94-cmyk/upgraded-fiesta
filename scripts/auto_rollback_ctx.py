#!/usr/bin/env python3
"""auto_rollback_ctx.py — Kontext einsammeln UND Conclusio-Allowlist fuer Auto-Rollback.

Zwei Rollen in einer Datei, weil sie dieselbe Tabelle teilen und nicht
auseinanderdriften duerfen:

1. **Kontext einsammeln** (`prev_conclusion`, `build`, `issue_body`).
   Getrennt vom Workflow, weil verschachtelte Heredocs in YAML die Datei
   unbrauchbar machen -- genau das ist beim ersten Versuch passiert. Shell
   im YAML bleibt hier auf Aufrufe beschraenkt, jede Datenverarbeitung liegt
   in dieser Datei und ist damit testbar.

2. **Conclusio-Allowlist** (`ALLOWLIST`, `decide`, `from_env`). GitHub
   Actions kann eine `workflow_run` mit `success`, `failure`, `cancelled`,
   `timed_out`, `action_required`, `neutral`, `skipped`, `stale`,
   `startup_failure` abschliessen. Eine Blockliste auf `failure` schluckt
   stillschweigend alles, was nicht exakt `failure` ist: ein `cancelled`
   oder `timed_out` landet im Grunde als Erfolg, weil die Pruefung nicht
   zutrifft. Genau das ist in HANDOFF.md s2-5 dokumentiert, und die Folge
   war ein gemergter Commit, der eigentlich zurueckgenommen werden musste
   -- der Workflow hat beim allerersten Lauf seinen eigenen einfuehrenden
   Merge-Commit revertiert, weil der Vorgaenger-Status 'unknown' war und
   eine Blockliste auf '== failure' das durchgewinkt hat.

   Diese Tabelle bildet die Entscheidung explizit ab: jede Conclusio
   bekommt eine Aktion, eine unbekannte faellt auf `HOLD` zurueck. Default
   ist `HOLD`, niemals `REVERT` -- ein "weiss nicht" darf nie einen
   Force-Push ausloesen, nur ein "weiss es und es ist rot" darf es.

   `scripts/auto_rollback.py` importiert diese Tabelle fuer seine Sperre 2
   (war der Vorgaenger nachweislich unbedenklich?), statt eine eigene,
   zwangslaeufig abweichende Liste zu fuehren.

       REVERT  — der letzte Merge auf main wird rueckgaengig gemacht
       HOLD    — Aktion wird blockiert, bis ein Mensch entscheidet
       NOOP    — es ist nichts zu tun
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
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


def prev_conclusion(path: str) -> str:
    """CI-Ergebnis des Vorgaengercommits aus einer Actions-API-Antwort."""
    try:
        runs = json.loads(pathlib.Path(path).read_text()).get("workflow_runs", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return "unknown"
    ci = [r for r in runs if r.get("name") == "ci" and r.get("conclusion")]
    return ci[0]["conclusion"] if ci else "unknown"


def build(reverts_path: str) -> dict:
    try:
        lines = pathlib.Path(reverts_path).read_text().splitlines()
    except OSError:
        lines = []
    return {
        "sha": os.environ.get("SHA", ""),
        "subject": os.environ.get("SUBJECT", ""),
        "branch": "main",
        "conclusion": os.environ.get("CONCLUSION", ""),
        "previous_conclusion": os.environ.get("PREV_CONCLUSION", "unknown").strip(),
        "recent_reverts": [l.strip() for l in lines if l.strip()],
    }


def issue_body() -> dict:
    """Issue-Text fuer den Befund.

    Auch hier kein mehrzeiliges Python im YAML: genau das hat die
    Workflow-Datei zweimal unbrauchbar gemacht, weil Heredocs und
    dreifache Anfuehrungszeichen die YAML-Struktur zerlegen.
    """
    sha = os.environ.get("SHA", "")
    return {
        "title": f"Auto-Rollback: {os.environ.get('ACTION', '?')} auf {sha[:7]}",
        "body": (
            "CI auf `main` ist fehlgeschlagen.\n\n"
            "**Entscheidung**\n```json\n"
            f"{os.environ.get('DECISION', '{}')}\n```\n\n"
            f"Commit: `{sha}`\n"
            f"CI-Lauf: {os.environ.get('RUN_URL', '-')}\n\n"
            "Bei `HOLD` hat eine der vier Sperren gegriffen — die Begruendung "
            "steht oben. Dann ist manuelles Eingreifen noetig."
        ),
    }


def _legacy_main(argv: list[str]) -> int:
    """Kontext-Sammler-Subkommandos, vom Workflow-YAML aufgerufen."""
    if argv[1] == "issue-body":
        print(json.dumps(issue_body(), ensure_ascii=False))
        return 0
    if len(argv) < 3:
        print("usage: auto_rollback_ctx.py {prev-conclusion|build} <datei>",
              file=sys.stderr)
        return 2
    cmd, path = argv[1], argv[2]
    if cmd == "prev-conclusion":
        print(prev_conclusion(path))
    elif cmd == "build":
        print(json.dumps(build(path), ensure_ascii=False))
    else:
        return 2
    return 0


def _allowlist_main(argv: list[str]) -> int:
    """Conclusio→Aktion-CLI: `--conclusion`, `--json`, `--show-allowlist`."""
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--conclusion",
                   help="GitHub-Workflow-Conclusio (sonst aus $CONCLUSION).")
    p.add_argument("--json", action="store_true",
                   help="Eine JSON-Zeile {conclusion, action} ausgeben.")
    p.add_argument("--show-allowlist", action="store_true",
                   help="Alle Allowlist-Eintraege ausgeben und beenden.")
    args = p.parse_args(argv)

    if args.show_allowlist:
        json.dump(ALLOWLIST, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    conclusion = (args.conclusion if args.conclusion is not None
                  else os.environ.get("CONCLUSION", "")).strip()
    action = decide(conclusion)
    if args.json:
        json.dump({"conclusion": conclusion, "action": action}, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(f"conclusion={conclusion!r} action={action}")
    # Exit 0 bei NOOP/HOLD; Exit 2 nur bei REVERT, damit ein Cron-Lauf
    # im stillen Erfolgsfall nicht rot wird, ein REVERT aber sichtbar ist.
    return 2 if action == "REVERT" else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) >= 2 and argv[1] in ("issue-body", "prev-conclusion", "build"):
        return _legacy_main(argv)
    return _allowlist_main(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
