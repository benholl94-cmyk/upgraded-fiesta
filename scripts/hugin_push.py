#!/usr/bin/env python3
"""
hugin_push.py — Autonomer, selbstheilender Git-Push-Automat für HUGIN

Drei integrierte Module:
  M1: RetryPush      — exponentieller Backoff bei transientem Fehler
  M2: DivergenceHeal — auto-rebase wenn Remote vorausgeeilt ist
  M3: StatusGuard    — vor jedem Push: nur sichere (nicht-geheime) Dateien staged

Usage: python3 scripts/hugin_push.py [--branch BRANCH] [--dry-run]
"""

import subprocess
import time
import sys
import os
import re
import argparse
from typing import Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BRANCH = "claude/claud-ai-code-teleport-nx73zr"
MAX_RETRIES = 4
BACKOFF_BASE_S = 2  # 2s, 4s, 8s, 16s

# Dateimuster die NIEMALS committet werden dürfen
SECRET_PATTERNS = [
    r"\.env(\.|$)", r"\.pem$", r"\.key$", r"id_rsa", r"id_ed25519",
    r"credentials\.json", r"secrets\.", r"token\.txt",
    r"platform-status\.json",  # Daemon-Laufzeitdatei
]


# ─── M1: RetryPush ────────────────────────────────────────────────────────────

def run(cmd: list[str], capture: bool = True) -> tuple[int, str, str]:
    """Führt einen Befehl aus und gibt (returncode, stdout, stderr) zurück."""
    result = subprocess.run(
        cmd, cwd=REPO_ROOT,
        capture_output=capture,
        text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def retry_push(branch: str, dry_run: bool = False) -> bool:
    """
    M1: Versucht git push mit exponentiellem Backoff.
    Gibt True zurück wenn erfolgreich, False nach Erschöpfung der Versuche.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        delay = BACKOFF_BASE_S ** attempt  # 2, 4, 8, 16
        if dry_run:
            print(f"[M1] DRY-RUN: git push -u origin {branch}")
            return True

        print(f"[M1] Push-Versuch {attempt}/{MAX_RETRIES} …")
        code, out, err = run(["git", "push", "-u", "origin", branch])

        if code == 0:
            print(f"[M1] Push erfolgreich.")
            return True

        # Divergenz-Fehler → M2 versuchen, dann nochmal
        if "rejected" in err and ("fetch first" in err or "non-fast-forward" in err):
            print(f"[M1] Branch divergiert — M2 (DivergenceHeal) wird aktiviert …")
            if divergence_heal(branch):
                continue  # nochmal versuchen ohne Delay
            else:
                print("[M1] DivergenceHeal fehlgeschlagen — abbruch.")
                return False

        # Transienter Fehler → warten und retry
        print(f"[M1] Fehler (code={code}): {err[:120]}")
        if attempt < MAX_RETRIES:
            print(f"[M1] Warte {delay}s …")
            time.sleep(delay)

    print(f"[M1] Push nach {MAX_RETRIES} Versuchen fehlgeschlagen.")
    return False


# ─── M2: DivergenceHeal ───────────────────────────────────────────────────────

def divergence_heal(branch: str) -> bool:
    """
    M2: Heilt Branch-Divergenz durch fetch + rebase.
    Stasht lokale Änderungen vorher, stellt sie danach wieder her.
    Gibt True zurück wenn Rebase erfolgreich, sonst False.
    """
    print(f"[M2] Fetch origin/{branch} …")
    code, _, err = run(["git", "fetch", "origin", branch])
    if code != 0:
        print(f"[M2] Fetch fehlgeschlagen: {err[:80]}")
        return False

    # Stash uncommitted changes
    code, out, _ = run(["git", "stash", "push", "-u", "-m", "hugin_push_auto_stash"])
    stashed = "No local changes" not in out and code == 0

    print(f"[M2] Rebase auf origin/{branch} …")
    code, _, err = run(["git", "rebase", f"origin/{branch}"])
    if code != 0:
        print(f"[M2] Rebase-Konflikt: {err[:120]}")
        run(["git", "rebase", "--abort"])
        if stashed:
            run(["git", "stash", "pop"])
        return False

    if stashed:
        print("[M2] Stash wiederherstellen …")
        run(["git", "stash", "pop"])

    print("[M2] Divergenz geheilt.")
    return True


# ─── M3: StatusGuard ──────────────────────────────────────────────────────────

def status_guard() -> tuple[bool, list[str]]:
    """
    M3: Prüft den Staging-Bereich auf verbotene/geheime Dateien.
    Gibt (safe, blocked_files) zurück.
    Blockiert wenn ein staged File einem SECRET_PATTERN entspricht.
    """
    code, out, _ = run(["git", "diff", "--cached", "--name-only"])
    if code != 0 or not out:
        return True, []

    staged = out.splitlines()
    blocked = []
    for f in staged:
        for pattern in SECRET_PATTERNS:
            if re.search(pattern, f, re.IGNORECASE):
                blocked.append(f)
                break

    if blocked:
        print(f"[M3] BLOCKIERT — verbotene Dateien im Staging-Bereich:")
        for f in blocked:
            print(f"  ✗ {f}")
        print("[M3] Bitte 'git reset HEAD <datei>' und erneut versuchen.")
        return False, blocked

    print(f"[M3] Staging sicher ({len(staged)} Datei(en) geprüft).")
    return True, []


# ─── Hauptroutine ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="HUGIN autonomer Push-Automat")
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  HUGIN Push-Automat | Branch: {args.branch}")
    print(f"{'='*60}\n")

    # M3: Sicherheitsprüfung vor allem anderen
    safe, blocked = status_guard()
    if not safe:
        sys.exit(1)

    # M1 + M2: Push mit Selbstheilung
    success = retry_push(args.branch, dry_run=args.dry_run)

    print()
    if success:
        print("✓ Fertig — Branch ist synchron mit Remote.")
        sys.exit(0)
    else:
        print("✗ Push fehlgeschlagen nach allen Versuchen.")
        sys.exit(1)


if __name__ == "__main__":
    main()
