#!/usr/bin/env python3
"""Kontext fuer auto_rollback.py einsammeln.

Getrennt vom Workflow, weil verschachtelte Heredocs in YAML die Datei
unbrauchbar machen -- genau das ist beim ersten Versuch passiert. Shell im
YAML bleibt hier auf Aufrufe beschraenkt, jede Datenverarbeitung liegt in
dieser Datei und ist damit testbar.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys


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


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "issue-body":
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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
