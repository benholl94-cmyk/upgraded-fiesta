#!/usr/bin/env python3
"""
direct_write.py — MUNIN Direct-Write Module
============================================
Schreibt Code direkt in das Repo, committed und pusht in einem Schritt.
Kein extra PR, kein manuelles Review erforderlich.

Verwendung:
  python3 .claude/skills/direct-write/scripts/direct_write.py commit "type(scope): message"
  python3 .claude/skills/direct-write/scripts/direct_write.py push
  python3 .claude/skills/direct-write/scripts/direct_write.py sync
  python3 .claude/skills/direct-write/scripts/direct_write.py full "type(scope): message"
  python3 .claude/skills/direct-write/scripts/direct_write.py status
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent
BRANCH    = "claude/claud-ai-code-teleport-nx73zr"

C = {"B": "\033[1m", "GR": "\033[92m", "YL": "\033[93m",
     "RD": "\033[91m", "DM": "\033[2m", "R": "\033[0m"}


def run(cmd: list[str], check=True, capture=True) -> subprocess.CompletedProcess:
    kwargs = {"cwd": REPO_ROOT, "check": check, "text": True}
    if capture:
        kwargs["capture_output"] = True
    return subprocess.run(cmd, **kwargs)


def current_branch() -> str:
    return run(["git", "branch", "--show-current"]).stdout.strip()


def has_changes() -> bool:
    r = run(["git", "status", "--porcelain"])
    return bool(r.stdout.strip())


def staged_files() -> list[str]:
    r = run(["git", "diff", "--cached", "--name-only"])
    return [l for l in r.stdout.strip().split("\n") if l]


def cmd_commit(args: list[str]) -> None:
    if not args:
        print(f"{C['RD']}Fehler:{C['R']} Commit-Nachricht angeben.", file=sys.stderr)
        sys.exit(1)
    msg = args[0]
    coauthor = "benholl94-cmyk <benjaminhollbach25@gmail.com>"

    # Alle geänderten Dateien stagen (außer logs/ und secrets)
    run(["git", "add", "--all", "--", ":!logs/", ":!.env*", ":!*.key", ":!*.pem"])

    staged = staged_files()
    if not staged:
        print(f"{C['YL']}⚠{C['R']} Keine Änderungen zu committen.")
        return

    full_msg = f"{msg}\n\nCo-Authored-By: {coauthor}"
    run(["git", "commit", "-m", full_msg], capture=False)
    print(f"{C['GR']}✓{C['R']} Committed: {len(staged)} Datei(en)")


def cmd_push(_args: list[str]) -> None:
    branch = current_branch()
    # Erst remote Änderungen holen und mergen
    run(["git", "fetch", "origin", branch], check=False)
    merge = run(
        ["git", "merge", "-X", "ours", f"origin/{branch}", "--no-edit"],
        check=False,
    )
    if merge.returncode != 0:
        # Konflikt in logs/ — einfach cleanen
        run(["git", "checkout", "--", "logs/"], check=False)
        run(["git", "merge", "--continue"], check=False, capture=False)

    result = run(["git", "push", "-u", "origin", branch], check=False)
    if result.returncode != 0:
        print(f"{C['RD']}Push-Fehler:{C['R']} {result.stderr[:200]}", file=sys.stderr)
        sys.exit(1)
    print(f"{C['GR']}✓{C['R']} Gepusht auf origin/{branch}")


def cmd_sync(_args: list[str]) -> None:
    """Remote-Stand holen und lokalen Stand synchronisieren."""
    branch = current_branch()
    run(["git", "fetch", "origin", branch])
    run(["git", "merge", "-X", "ours", f"origin/{branch}", "--no-edit"], capture=False)
    print(f"{C['GR']}✓{C['R']} Synchronisiert mit origin/{branch}")


def cmd_full(args: list[str]) -> None:
    """Kompletter Zyklus: commit + sync + push."""
    cmd_commit(args)
    cmd_push([])


def cmd_status(_args: list[str]) -> None:
    branch = current_branch()
    result = run(["git", "status", "--short"])
    unpushed = run(
        ["git", "rev-list", f"origin/{branch}..HEAD", "--count"],
        check=False,
    ).stdout.strip() or "?"

    print(f"\n{C['B']}── Direct-Write Status{C['R']}")
    print(f"  Branch   : {branch}")
    print(f"  Unpushed : {unpushed} Commit(s)")
    if result.stdout.strip():
        print(f"  Änderungen:")
        for line in result.stdout.strip().split("\n"):
            print(f"    {line}")
    else:
        print(f"  {C['GR']}Sauber{C['R']} — keine lokalen Änderungen")
    print()


COMMANDS = {
    "commit": cmd_commit,
    "push":   cmd_push,
    "sync":   cmd_sync,
    "full":   cmd_full,
    "status": cmd_status,
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] not in COMMANDS:
        print(__doc__)
        sys.exit(0)
    COMMANDS[args[0]](args[1:])


if __name__ == "__main__":
    main()
