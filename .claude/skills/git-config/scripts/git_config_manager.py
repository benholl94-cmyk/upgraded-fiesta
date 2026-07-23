#!/usr/bin/env python3
"""
git_config_manager.py — MUNIN Git-Identity-Manager
====================================================
Verwaltet git-Identitätsprofile und behebt Commit-Authorship-Probleme
autonom, ohne manuelle Intervention des Masters.

Profile:
  claude     noreply@anthropic.com / Claude          → Verified auf GitHub (Standard für CI)
  munin      274793931+benholl94-cmyk@users.noreply.github.com / benholl94-cmyk  → Owner-sichtbar
  bot        Lese-only — niemals für eigene Commits

Befehle:
  status                         Aktuellen Zustand anzeigen
  switch <profile>               Profil wechseln (local config)
  fix-tip                        Tip-Commit reset-author (aktuelles Profil)
  fix-tip --profile <p>          Profil wechseln + Tip fixen in einem Schritt
  rebase-fix <base>              Alle Commits seit <base> re-author
  check-verified                 Prüft welche Commits als Unverified gelten
  auto                           Analysiert Situation + wählt optimalen Fix

Entscheidungslogik (auto):
  - Wenn Hook meldet "Unverified": switch claude + fix-tip
  - Wenn commit soll unter Owner erscheinen: switch munin
  - Merge-Commits / Bot-Commits: niemals anfassen
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent

C = {"B": "\033[1m", "CY": "\033[96m", "GR": "\033[92m",
     "YL": "\033[93m", "RD": "\033[91m", "DM": "\033[2m", "R": "\033[0m"}

PROFILES = {
    "claude": {
        "name":  "Claude",
        "email": "noreply@anthropic.com",
        "desc":  "Verified auf GitHub — Standard für autonome MUNIN-Commits",
    },
    "munin": {
        "name":  "benholl94-cmyk",
        "email": "274793931+benholl94-cmyk@users.noreply.github.com",
        "desc":  "Owner-Identität — Commits erscheinen unter benholl94-cmyk",
    },
}

# Commits die NIEMALS angefasst werden dürfen
PROTECTED_EMAILS = {
    "noreply@github.com",
    "41898282+github-actions[bot]@users.noreply.github.com",
    "49699333+dependabot[bot]@users.noreply.github.com",
}


def run(cmd: list[str], check=True, capture=True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=REPO_ROOT, check=check,
        capture_output=capture, text=True,
    )


def current_config() -> tuple[str, str]:
    name  = run(["git", "config", "user.name"]).stdout.strip()
    email = run(["git", "config", "user.email"]).stdout.strip()
    return name, email


def detect_profile(name: str, email: str) -> str:
    for pname, pdata in PROFILES.items():
        if pdata["email"] == email:
            return pname
    return "unknown"


def cmd_status(_args: list[str]) -> None:
    name, email = current_config()
    profile = detect_profile(name, email)
    pdata   = PROFILES.get(profile, {})

    print(f"\n{C['B']}── Git-Config Status{C['R']}")
    print(f"  Name  : {name}")
    print(f"  Email : {email}")
    print(f"  Profil: {C['CY']}{profile}{C['R']} — {pdata.get('desc', 'unbekannt')}")

    # Tip-Commit
    tip = run(["git", "log", "-1", "--format=%H %ae %s"]).stdout.strip()
    if tip:
        parts = tip.split(" ", 2)
        h, ae, msg = parts[0][:8], parts[1], (parts[2] if len(parts) > 2 else "")
        is_protected = ae in PROTECTED_EMAILS
        status_icon  = f"{C['RD']}PROTECTED{C['R']}" if is_protected else f"{C['GR']}eigener{C['R']}"
        verified_icon = f"{C['GR']}✓{C['R']}" if ae == "noreply@anthropic.com" else f"{C['YL']}~{C['R']}"
        print(f"\n  Tip   : [{verified_icon}] {h} <{ae}> {msg[:50]}")
        print(f"          {status_icon}")
    print()


def cmd_switch(args: list[str]) -> None:
    if not args:
        print(f"{C['RD']}Fehler:{C['R']} Profil angeben: claude | munin", file=sys.stderr)
        sys.exit(1)
    profile = args[0]
    if profile not in PROFILES:
        print(f"{C['RD']}Fehler:{C['R']} Unbekanntes Profil '{profile}'. "
              f"Verfügbar: {list(PROFILES)}", file=sys.stderr)
        sys.exit(1)
    pdata = PROFILES[profile]
    run(["git", "config", "user.name",  pdata["name"]])
    run(["git", "config", "user.email", pdata["email"]])
    print(f"{C['GR']}✓{C['R']} Profil → {C['CY']}{profile}{C['R']}: "
          f"{pdata['name']} <{pdata['email']}>")


def _tip_is_protected() -> bool:
    ae = run(["git", "log", "-1", "--format=%ae"]).stdout.strip()
    return ae in PROTECTED_EMAILS


def _tip_is_merge() -> bool:
    parents = run(["git", "log", "-1", "--format=%P"]).stdout.strip()
    return len(parents.split()) > 1


def cmd_fix_tip(args: list[str]) -> None:
    # Optionales --profile <name>
    profile_override = None
    if "--profile" in args:
        idx = args.index("--profile")
        if idx + 1 < len(args):
            profile_override = args[idx + 1]
            cmd_switch([profile_override])

    if _tip_is_protected():
        print(f"{C['YL']}⚠{C['R']} Tip-Commit gehört einem Bot/GitHub — wird nicht angefasst.")
        return
    if _tip_is_merge():
        print(f"{C['YL']}⚠{C['R']} Tip-Commit ist ein Merge-Commit — wird nicht angefasst.")
        return

    run(["git", "commit", "--amend", "--no-edit", "--reset-author"])
    tip = run(["git", "log", "-1", "--format=%H %ae"]).stdout.strip()
    h, ae = tip.split(" ", 1)
    print(f"{C['GR']}✓{C['R']} Tip-Commit re-authored: {h[:8]} <{ae}>")


def cmd_rebase_fix(args: list[str]) -> None:
    if not args:
        print(f"{C['RD']}Fehler:{C['R']} Basis-Ref angeben (z.B. origin/main)", file=sys.stderr)
        sys.exit(1)
    base = args[0]

    # Commits seit base die mir gehören (nicht protected, nicht merge)
    log = run(["git", "log", f"{base}..HEAD", "--format=%H %P %ae %s"]).stdout.strip()
    if not log:
        print("Keine eigenen Commits seit", base)
        return

    fixable = []
    for line in log.split("\n"):
        parts  = line.split(" ", 3)
        h      = parts[0]
        parents = parts[1]  # mehrere = merge
        ae     = parts[2]
        is_merge     = len(parents.split()) > 1
        is_protected = ae in PROTECTED_EMAILS
        if not is_merge and not is_protected:
            fixable.append(h)

    if not fixable:
        print(f"{C['YL']}Keine fixbaren Commits gefunden (alle protected oder Merges).{C['R']}")
        return

    print(f"  {len(fixable)} Commit(s) werden re-authored...")
    exec_cmd = "git commit --amend --no-edit --reset-author"
    result = run(
        ["git", "rebase", "--exec", exec_cmd, base],
        check=False,
    )
    if result.returncode != 0:
        print(f"{C['RD']}Rebase-Fehler:{C['R']}\n{result.stderr[:400]}")
        sys.exit(1)
    print(f"{C['GR']}✓{C['R']} {len(fixable)} Commit(s) re-authored seit {base}.")


def cmd_check_verified(_args: list[str]) -> None:
    log = run(["git", "log", "origin/main..HEAD", "--format=%H %ae %s"]).stdout.strip()
    if not log:
        print("Keine Commits über origin/main.")
        return
    print(f"\n{C['B']}── Commit-Verifikation (seit origin/main){C['R']}")
    for line in log.split("\n"):
        parts = line.split(" ", 2)
        h, ae = parts[0][:8], parts[1]
        msg   = parts[2][:50] if len(parts) > 2 else ""
        if ae == "noreply@anthropic.com":
            icon = f"{C['GR']}✓ VERIFIED  {C['R']}"
        elif ae in PROTECTED_EMAILS:
            icon = f"{C['DM']}◦ PROTECTED {C['R']}"
        else:
            icon = f"{C['YL']}~ UNVERIFIED{C['R']}"
        print(f"  {icon} {h} {msg}")
    print()


def cmd_auto(_args: list[str]) -> None:
    """Analysiert + behebt autonom."""
    print(f"\n{C['B']}── Oracle-Auto-Fix{C['R']}")

    # Prüfe ob Tip fixbar ist
    if _tip_is_protected():
        print(f"  Tip ist geschützt (Bot/GitHub). Kein Fix nötig.")
        return
    if _tip_is_merge():
        print(f"  Tip ist Merge-Commit. Kein Fix nötig.")
        return

    tip_email = run(["git", "log", "-1", "--format=%ae"]).stdout.strip()
    if tip_email == "noreply@anthropic.com":
        print(f"  {C['GR']}✓{C['R']} Tip bereits verified. Nichts zu tun.")
        return

    # Zur claude-Identität wechseln + Tip amenden
    print(f"  Tip-Email: {tip_email} → wechsle zu claude-Profil + re-author")
    cmd_switch(["claude"])
    cmd_fix_tip([])
    print(f"  {C['GR']}✓{C['R']} Auto-Fix abgeschlossen.")


COMMANDS = {
    "status":         cmd_status,
    "switch":         cmd_switch,
    "fix-tip":        cmd_fix_tip,
    "rebase-fix":     cmd_rebase_fix,
    "check-verified": cmd_check_verified,
    "auto":           cmd_auto,
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] not in COMMANDS:
        print(__doc__)
        sys.exit(0)
    COMMANDS[args[0]](args[1:])


if __name__ == "__main__":
    main()
