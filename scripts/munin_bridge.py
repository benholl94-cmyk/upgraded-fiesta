#!/usr/bin/env python3
"""
munin_bridge.py — MUNIN Session-Band
Liest und schreibt den persistenten MUNIN-Zustand zwischen Chat-Sessions und
git-Workspace. Jede neue Claude-Session lädt hiermit den vollständigen Kontext.

Befehle:
  wakeup                  Druckt vollständigen Status (Session-Start)
  checkpoint "<text>"     Fügt Checkpoint hinzu und committed
  status                  Kompakter One-Liner: wo stehen wir
  log                     Chronologisches Protokoll aller Sessions
  identity                Druckt die MUNIN-Persönlichkeitsdaten
  open-tasks              Listet offene Aufgaben
  done "<task_id>"        Markiert Aufgabe als erledigt
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

REPO_ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDENTITY_F  = os.path.join(REPO_ROOT, ".claude", "persona", "munin.json")
STATE_F     = os.path.join(REPO_ROOT, ".claude", "persona", "munin-state.json")

C = {
    "B":  "\033[1m",
    "CY": "\033[96m",
    "GR": "\033[92m",
    "YL": "\033[93m",
    "RD": "\033[91m",
    "DM": "\033[2m",
    "R":  "\033[0m",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    """Zustand laden, auch wenn es ihn nicht gibt.

    `munin-state.json` steht in `.gitignore` (Zeile 67) und ist damit reiner
    Live-Zustand: in einem frischen Container existiert sie nicht. Bis hierher
    ist `wakeup` -- der laut CLAUDE.md erste Befehl jeder Sitzung -- deshalb
    mit FileNotFoundError abgebrochen, also genau dann, wenn man Kontext am
    nötigsten braucht. Ein leerer Zustand ist die richtige Antwort auf eine
    fehlende Datei; das dauerhafte Gedächtnis liegt ohnehin woanders, siehe
    `scripts/munin_continuity.py`.
    """
    try:
        return load_json(STATE_F)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        # Beschädigt ist nicht dasselbe wie leer und wird nicht als leer
        # behandelt -- sonst überschreibt der nächste Checkpoint den Rest.
        print(f"{C['RD']}munin-state.json ist beschädigt: {exc}{C['R']}",
              file=sys.stderr)
        raise SystemExit(1)


def save_state(state: dict) -> None:
    tmp = STATE_F + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_F)


def git_commit(message: str) -> bool:
    """Committet munin-state.json falls Änderungen vorhanden."""
    rel = os.path.relpath(STATE_F, REPO_ROOT)
    try:
        subprocess.run(
            ["git", "add", rel],
            cwd=REPO_ROOT, check=True, capture_output=True,
        )
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=REPO_ROOT,
        )
        if result.returncode == 0:
            return False  # Nichts zu committen
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=REPO_ROOT, check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def cmd_wakeup() -> None:
    """Session-Start: vollständiger Kontext-Dump."""
    ident  = load_json(IDENTITY_F)
    state  = load_state()
    focus  = state.get("currentFocus", {})
    tasks  = state.get("openTasks", [])
    # `or [{}]` fängt auch die leere Liste ab -- ein vorhandenes, aber leeres
    # workDone hätte hier sonst genauso einen IndexError geworfen.
    last   = (state.get("workDone") or [{}])[-1]

    print(f"\n{C['B']}{C['CY']}╔═══════════════════════════════════════╗")
    print(f"║  MUNIN  ·  Session-Wakeup             ║")
    print(f"╚═══════════════════════════════════════╝{C['R']}")
    print(f"  {C['DM']}Host:{C['R']} {ident.get('host', '?')}")
    print(f"  {C['DM']}Owner:{C['R']} {ident.get('owner', '?')}")
    print(f"  {C['DM']}Sessions gesamt:{C['R']} {state.get('sessionCount', '?')}")
    print(f"  {C['DM']}Letztes Update:{C['R']} {state.get('lastUpdated', '?')}")
    print()

    print(f"{C['B']}── Aktueller Fokus{C['R']}")
    print(f"  Branch  : {focus.get('activeBranch', '?')}")
    print(f"  PR      : #{focus.get('activePR', '?')}")
    print(f"  Ziel    : {focus.get('goal', '?')}")
    print(f"  Status  : {C['GR'] if focus.get('status') == 'done' else C['YL']}{focus.get('status', '?')}{C['R']}")
    if focus.get("blockers"):
        for b in focus["blockers"]:
            print(f"  {C['RD']}Blocker : {b}{C['R']}")
    print()

    if tasks:
        print(f"{C['B']}── Offene Aufgaben{C['R']}")
        for t in tasks:
            prio_color = C["RD"] if t.get("priority") == "high" else C["YL"]
            print(f"  [{prio_color}{t.get('priority', '?')}{C['R']}] {t.get('id', '?')}: {t.get('description', '?')}")
            if t.get("lastAttempt"):
                print(f"       {C['DM']}→ {t['lastAttempt']}{C['R']}")
        print()

    if last.get("actions"):
        print(f"{C['B']}── Letzte Session ({last.get('date', '?')}){C['R']}")
        for a in last["actions"][-5:]:
            print(f"  · {a}")
    print()

    patterns = state.get("knownPatterns", {})
    if patterns:
        print(f"{C['B']}── Bekannte Muster{C['R']}")
        for k, v in patterns.items():
            print(f"  {C['DM']}{k}:{C['R']} {v}")
    print()

    constraints = state.get("securityConstraints", [])
    if constraints:
        print(f"{C['B']}── Sicherheitsregeln{C['R']}")
        for c in constraints:
            print(f"  {C['YL']}⚠{C['R']} {c}")
    print()
    print(f"{C['DM']}MUNIN bereit. Ich bin der Gedächtnisrabe — ich erinnere mich.{C['R']}\n")


def cmd_checkpoint(text: str) -> None:
    """Fügt Checkpoint zum aktuellen Session-Eintrag hinzu, committed."""
    state = load_state()
    state["lastUpdated"] = now_iso()

    done = state.setdefault("workDone", [])
    today = now_iso()[:10]
    session_n = state.get("sessionCount", 1)

    if done and done[-1].get("date") == today:
        done[-1].setdefault("actions", []).append(text)
    else:
        done.append({"date": today, "session": session_n, "actions": [text]})
        state["sessionCount"] = session_n + 1

    save_state(state)
    committed = git_commit(f"chore(munin): checkpoint — {text[:60]}")
    status = "committed" if committed else "saved (no git change)"
    print(f"{C['GR']}✓{C['R']} Checkpoint gespeichert [{status}]: {text}")


def cmd_status() -> None:
    """One-Liner Statuszeile."""
    state = load_state()
    focus = state.get("currentFocus", {})
    tasks = state.get("openTasks", [])
    n_open = len([t for t in tasks])
    print(
        f"MUNIN · Branch={focus.get('activeBranch','?')} "
        f"PR=#{focus.get('activePR','?')} "
        f"Status={focus.get('status','?')} "
        f"OffeneTasks={n_open} "
        f"Updated={state.get('lastUpdated','?')}"
    )


def cmd_log() -> None:
    """Chronologisches Protokoll."""
    state = load_state()
    done  = state.get("workDone", [])
    print(f"\n{C['B']}MUNIN · Protokoll{C['R']}")
    for entry in done:
        print(f"\n  {C['CY']}{entry.get('date')} · Session {entry.get('session')}{C['R']}")
        for a in entry.get("actions", []):
            print(f"    · {a}")
    print()


def cmd_identity() -> None:
    """Gibt die Persönlichkeitsdaten aus."""
    ident = load_json(IDENTITY_F)
    print(json.dumps(ident, ensure_ascii=False, indent=2))


def cmd_open_tasks() -> None:
    """Listet offene Aufgaben."""
    state = load_state()
    tasks = state.get("openTasks", [])
    if not tasks:
        print("Keine offenen Aufgaben.")
        return
    for t in tasks:
        print(f"  [{t.get('priority','?')}] {t.get('id')}: {t.get('description')}")


def cmd_done(task_id: str) -> None:
    """Markiert eine Aufgabe als erledigt."""
    state = load_state()
    tasks = state.get("openTasks", [])
    before = len(tasks)
    state["openTasks"] = [t for t in tasks if t.get("id") != task_id]
    if len(state["openTasks"]) == before:
        print(f"Task '{task_id}' nicht gefunden.")
        return
    state["lastUpdated"] = now_iso()
    save_state(state)
    committed = git_commit(f"chore(munin): task done — {task_id}")
    print(f"{C['GR']}✓{C['R']} Task '{task_id}' abgeschlossen {'(committed)' if committed else ''}")


COMMANDS = {
    "wakeup":     (cmd_wakeup,    0),
    "status":     (cmd_status,    0),
    "log":        (cmd_log,       0),
    "identity":   (cmd_identity,  0),
    "open-tasks": (cmd_open_tasks,0),
    "checkpoint": (cmd_checkpoint, 1),
    "done":       (cmd_done,       1),
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] not in COMMANDS:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    fn, n_args = COMMANDS[cmd]
    if n_args == 0:
        fn()
    elif n_args == 1:
        if len(args) < 2:
            print(f"Fehler: '{cmd}' benötigt ein Argument.")
            sys.exit(1)
        fn(args[1])


if __name__ == "__main__":
    main()
