"""agents CLI -- Aufgaben stellen, Ergebnisse pruefen, Patches anwenden.

    python3 -m agents status
    python3 -m agents run codex --id fix-42 --kind fix \
        --instruction "..." --file crates/hm-core/src/lib.rs
    python3 -m agents ledger [--task ID]
    python3 -m agents apply <result.json> --yes

`run` wendet nichts an. Das Anwenden ist ein eigener Schritt mit eigener
Zustimmung -- ein Agent, dessen Vorschlag automatisch ins Repo laeuft, ist
kein Vorschlag.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ledger import Ledger
from .orchestrator import Orchestrator, OrchestratorError
from .protocol import AgentPatch, AgentResult, dumps


def cmd_status(a: argparse.Namespace) -> int:
    o = Orchestrator()
    rows = o.status()
    if a.json:
        print(dumps({"agents": rows}))
        return 0
    print(f"{'AGENT':<14}{'ROLLE':<14}{'ADAPTER':<14}{'BEREIT':<8}{'VERIFIZIERT':<12}GRUND")
    for r in rows:
        print(f"{r['id']:<14}{r['role']:<14}{r['adapter']:<14}"
              f"{('ja' if r['available'] else 'nein'):<8}"
              f"{('ja' if r['verified'] else 'NEIN'):<12}{r['reason']}")
    print("\nVERIFIZIERT=NEIN heisst: Code vollstaendig, Gegenstelle nie erreicht.")
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    o = Orchestrator()
    try:
        task = o.build_task(a.id, a.kind, a.instruction,
                            files=tuple(a.file or ()),
                            constraints=tuple(a.constraint or ()))
    except OrchestratorError as exc:
        print(f"Aufgabe ungueltig: {exc}", file=sys.stderr)
        return 2

    if a.dry_run:
        print(task.render_prompt())
        return 0

    try:
        result = o.dispatch(task, a.agent)
    except OrchestratorError as exc:
        print(f"Abbruch: {exc}", file=sys.stderr)
        return 3

    print(dumps(result.to_dict()))
    if result.conflicts:
        print("\nKONFLIKTE (im Ledger festgehalten):", file=sys.stderr)
        for c in result.conflicts:
            print(f"  - {c}", file=sys.stderr)
    if a.out:
        Path(a.out).write_text(dumps(result.to_dict(include_raw=True)) + "\n",
                               encoding="utf-8")
        print(f"\nErgebnis geschrieben: {a.out}", file=sys.stderr)
    if result.patches:
        print("\n" + o.describe_apply(result), file=sys.stderr)
        print("Anwenden: python3 -m agents apply <datei> --yes", file=sys.stderr)
    return 0 if result.ok else 1


def cmd_apply(a: argparse.Namespace) -> int:
    o = Orchestrator()
    raw = json.loads(Path(a.path).read_text(encoding="utf-8"))
    patches = tuple(AgentPatch(path=p["path"], action=p.get("action", "replace"),
                               content=p["content"], rationale=p.get("rationale", ""))
                    for p in raw.get("patches", []) if "content" in p)
    if not patches:
        print("Keine anwendbaren Patches: die Datei enthaelt keine 'content'-Felder.\n"
              "Ergebnisse aus 'run' sind absichtlich ohne Inhalt (nur sha256+bytes);\n"
              "nutze --out beim run, das schreibt die Vollfassung.", file=sys.stderr)
        return 2
    result = AgentResult(task_id=raw["task_id"], agent=raw.get("agent", "unbekannt"),
                         status=raw.get("status", "ok"), patches=patches,
                         notes=raw.get("notes", ""))
    print(o.describe_apply(result))
    try:
        written = o.apply(result, consent=a.yes)
    except OrchestratorError as exc:
        print(f"\nNicht angewendet: {exc}", file=sys.stderr)
        return 4
    print(f"\n{len(written)} Datei(en) geschrieben: {', '.join(written)}")
    return 0


def cmd_ledger(a: argparse.Namespace) -> int:
    led = Ledger()
    rows = led.read(a.task)
    if not rows:
        print("Ledger leer." if not a.task else f"Keine Eintraege fuer {a.task!r}.")
        return 0
    if a.json:
        print(dumps({"events": rows}))
        return 0
    for d in rows:
        print(f"{d['ts']}  {d['kind']:<20} {d['task_id']}")
        if d["kind"] == "conflict.recorded":
            print(f"    ⚠ {d['payload'].get('conflict')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agents", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="Agenten und ihre Einsatzbereitschaft")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    r = sub.add_parser("run", help="Aufgabe an einen Agenten geben")
    r.add_argument("agent")
    r.add_argument("--id", required=True)
    r.add_argument("--kind", required=True,
                   choices=("implement", "fix", "refactor", "test", "review", "explain"))
    r.add_argument("--instruction", required=True)
    r.add_argument("--file", action="append", help="Kontextdatei, wiederholbar")
    r.add_argument("--constraint", action="append", help="harte Vorgabe, wiederholbar")
    r.add_argument("--out", help="Ergebnis inkl. Patch-Inhalten hierhin schreiben")
    r.add_argument("--dry-run", action="store_true",
                   help="nur den Prompt zeigen, nichts senden")
    r.set_defaults(func=cmd_run)

    ap = sub.add_parser("apply", help="Patches aus einer Ergebnisdatei anwenden")
    ap.add_argument("path")
    ap.add_argument("--yes", action="store_true", help="Zustimmung; ohne sie: Abbruch")
    ap.set_defaults(func=cmd_apply)

    lg = sub.add_parser("ledger", help="Vorgangsprotokoll lesen")
    lg.add_argument("--task")
    lg.add_argument("--json", action="store_true")
    lg.set_defaults(func=cmd_ledger)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
