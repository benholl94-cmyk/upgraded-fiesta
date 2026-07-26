#!/usr/bin/env python3
"""Hooks aus dem Repo nach ~/.claude/ spiegeln.

Hooks liegen ausserhalb des Repos (`~/.claude/`) und sind damit nicht
versioniert: eine Containerneuerstellung verwirft jede Korrektur, und eine
Aenderung an der installierten Fassung ist in keinem Diff sichtbar. Das Repo
haelt deshalb die autoritative Fassung, dieses Skript synchronisiert.

Richtung ist immer Repo -> Home, nie umgekehrt. Wer den Hook aendern will,
aendert die Repo-Fassung und installiert neu -- sonst entsteht genau die
stille Divergenz, gegen die das hier gebaut ist.

    python3 scripts/install_hooks.py --check     # nur pruefen, nichts schreiben
    python3 scripts/install_hooks.py             # installieren (fragt nach)
    python3 scripts/install_hooks.py --yes       # installieren ohne Rueckfrage

Exit: 0 synchron / 1 Drift oder fehlend / 2 abgebrochen.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC_DIR = REPO / ".claude" / "hooks"
DST_DIR = Path.home() / ".claude"

# Nur diese Dateien werden angefasst. Eine Glob-Installation ueber ~/.claude/
# waere zu breit -- dort liegen auch Dateien, die das Repo nichts angehen.
HOOKS = ("stop-hook-git-check.sh",)


def state(name: str) -> tuple[str, Path, Path]:
    src, dst = SRC_DIR / name, DST_DIR / name
    if not src.is_file():
        return "fehlt-im-repo", src, dst
    if not dst.is_file():
        return "nicht-installiert", src, dst
    if src.read_bytes() == dst.read_bytes():
        return "synchron", src, dst
    return "drift", src, dst


def cmd_check() -> int:
    worst = 0
    for name in HOOKS:
        st, src, dst = state(name)
        mark = {"synchron": "OK  ", "drift": "DRIFT", "nicht-installiert": "FEHLT",
                "fehlt-im-repo": "FEHLT"}[st]
        print(f"[{mark}] {name}: {st}")
        if st != "synchron":
            worst = 1
            if st == "drift":
                print(f"        Repo:       {src}")
                print(f"        Installiert:{dst}")
                print( "        Repo-Fassung gilt. Installieren: "
                       "python3 scripts/install_hooks.py --yes")
            elif st == "nicht-installiert":
                print( "        Installieren: python3 scripts/install_hooks.py --yes")
    return worst


def cmd_install(consent: bool) -> int:
    pending = [(n, *state(n)[1:]) for n in HOOKS if state(n)[0] in ("drift", "nicht-installiert")]
    if not pending:
        print("Alles synchron — nichts zu tun.")
        return 0

    print("Folgende Dateien werden ueberschrieben:")
    for name, src, dst in pending:
        old = f"{dst.stat().st_size} B" if dst.is_file() else "neu"
        print(f"  {dst}  ({old} -> {src.stat().st_size} B)")

    if not consent:
        # Gleiche Regel wie ueberall im Repo: nicht still handeln und nicht
        # still nichts tun, sondern laut verweigern mit maschinenlesbarem Grund.
        print("\nZustimmung fehlt. Erneut mit --yes aufrufen.", file=sys.stderr)
        return 2

    DST_DIR.mkdir(parents=True, exist_ok=True)
    for name, src, dst in pending:
        if dst.is_file():
            backup = dst.with_suffix(dst.suffix + ".bak")
            shutil.copy2(dst, backup)
            print(f"  Backup: {backup}")
        shutil.copy2(src, dst)
        dst.chmod(0o755)
        print(f"  Installiert: {dst}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="nur pruefen, nichts schreiben")
    p.add_argument("--yes", action="store_true", help="Zustimmung zum Ueberschreiben")
    a = p.parse_args(argv)
    return cmd_check() if a.check else cmd_install(a.yes)


if __name__ == "__main__":
    raise SystemExit(main())
