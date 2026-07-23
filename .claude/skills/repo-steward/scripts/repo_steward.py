#!/usr/bin/env python3
"""
repo_steward.py — MUNIN Repo-Steward
=====================================
Lokale git-Operationen für Branch-Analyse und -Bereinigung.
PR-Operationen (close/merge) laufen über MCP-Tools in Claude.

Befehle:
  branches          Alle Branches mit Alter und Status auflisten
  stale-branches    Verwaiste Branches identifizieren (merged/kein PR)
  delete <branch>   Lokalen Remote-Tracking-Branch löschen
  delete-remote <branch>  Remote-Branch löschen via git push --delete
  pr-targets        PRs analysieren und Handlungsempfehlung ausgeben
  health            Vollständiger Repo-Health-Report
"""
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent

C = {"B": "\033[1m", "CY": "\033[96m", "GR": "\033[92m",
     "YL": "\033[93m", "RD": "\033[91m", "DM": "\033[2m", "R": "\033[0m"}

# Branches die NIEMALS gelöscht werden
PROTECTED_BRANCHES = {"main", "claude/claud-ai-code-teleport-nx73zr", "__dolt_remote_info__"}

# Bot-Branch-Prefixes (nur mit explizitem Befehl löschen)
BOT_PREFIXES = ("coderabbitai/", "codespace-", "revert-")


def run(cmd: list[str], check=True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=check)


def get_branches() -> list[dict]:
    result = run(["git", "for-each-ref", "refs/remotes/origin/",
                  "--format=%(refname:short)\t%(authordate:iso8601)\t%(subject)"])
    branches = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t", 2)
        name = parts[0].replace("origin/", "")
        date_str = parts[1] if len(parts) > 1 else ""
        subject = parts[2][:60] if len(parts) > 2 else ""
        try:
            dt = datetime.fromisoformat(date_str.replace(" ", "T", 1)[:19] + "+00:00")
            age_days = (datetime.now(timezone.utc) - dt).days
        except Exception:
            age_days = -1
        is_protected = name in PROTECTED_BRANCHES
        is_bot = any(name.startswith(p) for p in BOT_PREFIXES)
        branches.append({
            "name": name, "age_days": age_days,
            "subject": subject, "protected": is_protected, "bot": is_bot,
        })
    return sorted(branches, key=lambda b: b["age_days"], reverse=True)


def cmd_branches(_args: list[str]) -> None:
    branches = get_branches()
    print(f"\n{C['B']}── Remote Branches ({len(branches)}){C['R']}")
    for b in branches:
        if b["protected"]:
            icon = f"{C['GR']}●{C['R']}"
            tag = f"{C['DM']}[protected]{C['R']}"
        elif b["bot"]:
            icon = f"{C['CY']}◆{C['R']}"
            tag = f"{C['DM']}[bot]{C['R']}"
        elif b["age_days"] > 30:
            icon = f"{C['YL']}○{C['R']}"
            tag = f"{C['YL']}[stale {b['age_days']}d]{C['R']}"
        else:
            icon = f"{C['GR']}○{C['R']}"
            tag = f"{C['DM']}[{b['age_days']}d]{C['R']}"
        print(f"  {icon} {b['name']:<55} {tag}")
    print()


def cmd_stale_branches(_args: list[str]) -> None:
    branches = get_branches()
    stale = [b for b in branches
             if not b["protected"] and b["age_days"] > 14]
    if not stale:
        print(f"{C['GR']}Keine stale Branches.{C['R']}")
        return
    print(f"\n{C['B']}── Stale Branches (>{14}d, nicht protected){C['R']}")
    for b in stale:
        color = C["RD"] if b["age_days"] > 30 else C["YL"]
        kind = "[bot]" if b["bot"] else "[codex/user]"
        print(f"  {color}{b['age_days']:>3}d{C['R']}  {kind:<14}  {b['name']}")
    print(f"\n  {len(stale)} Branch(es) identifiziert.\n")


def cmd_delete_remote(args: list[str]) -> None:
    if not args:
        print(f"{C['RD']}Fehler:{C['R']} Branch-Name angeben.", file=sys.stderr)
        sys.exit(1)
    branch = args[0]
    if branch in PROTECTED_BRANCHES:
        print(f"{C['RD']}STOP:{C['R']} '{branch}' ist geschützt — kein Delete.", file=sys.stderr)
        sys.exit(2)
    result = run(["git", "push", "origin", "--delete", branch], check=False)
    if result.returncode != 0:
        # Bereits gelöscht = OK
        if "remote ref does not exist" in result.stderr:
            print(f"{C['YL']}⚠{C['R']} Branch '{branch}' existiert nicht mehr (bereits gelöscht).")
        else:
            print(f"{C['RD']}Fehler:{C['R']} {result.stderr[:200]}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"{C['GR']}✓{C['R']} Remote-Branch gelöscht: {branch}")


def cmd_health(_args: list[str]) -> None:
    branches = get_branches()
    stale   = [b for b in branches if not b["protected"] and b["age_days"] > 14]
    active  = [b for b in branches if b["protected"] or b["age_days"] <= 14]
    bots    = [b for b in stale if b["bot"]]
    user    = [b for b in stale if not b["bot"]]

    # Workflows
    wf_dir = REPO_ROOT / ".github" / "workflows"
    workflows = list(wf_dir.glob("*.yml")) if wf_dir.exists() else []
    empty_wf  = [w for w in workflows if w.stat().st_size < 10]

    print(f"\n{C['B']}╔═══════════════════════════════════════╗")
    print(f"║  MUNIN Repo-Health Report             ║")
    print(f"╚═══════════════════════════════════════╝{C['R']}")
    print(f"  Branches gesamt : {len(branches)}")
    print(f"  {C['GR']}Aktiv/Protected{C['R']}  : {len(active)}")
    print(f"  {C['YL']}Stale (User){C['R']}     : {len(user)}")
    print(f"  {C['CY']}Stale (Bot){C['R']}      : {len(bots)}")
    print(f"  Workflows        : {len(workflows)} ({C['RD']}{len(empty_wf)} leer{C['R']})" if empty_wf
          else f"  Workflows        : {C['GR']}{len(workflows)} OK{C['R']}")
    print()

    if stale:
        print(f"{C['B']}── Handlungsempfehlung{C['R']}")
        print(f"  Für MCP-PR-close + Branch-delete:")
        for b in user[:5]:
            print(f"    repo-steward delete-remote {b['name']}")
        if bots:
            print(f"  Bot-Branches (5 Stück) — separater Befehl nötig")
    print()


def cmd_pr_targets(_args: list[str]) -> None:
    """Druckt Empfehlungen für PR-Aktionen (close/keep) — MCP-Ausführung durch MUNIN."""
    # Bekannte PR-Situation aus Kontext
    stale_prs = [
        (4,  "iPhone Dev Platform", "codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-op15j7", "main", 42),
        (6,  "iPhone Dev Platform", "codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-ywuodw", "main", 42),
        (8,  "iPhone Dev Platform", "codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-rr1agn", "main", 42),
        (16, "iPhone Dev Platform", "codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-ldgbhw", "benholl94-cmyk/change-stack-8-f1e01161/626283e", 42),
        (22, "Codex iPhone setup",  "codex/richte-lokale-entwicklerumgebung-auf-iphone-ein",       "main", 41),
        (26, "iPhone control-plane validator", "codex/run-codex-cloud-setup-script", "claude/env-points-anchors-localization-flyoos", 41),
        (31, "UniqueClaw production build",    "uniqueclaw-production-grade-v2", "main", 39),
    ]
    print(f"\n{C['B']}── PR-Aktionsplan{C['R']}")
    for pr_num, title, branch, base, age in stale_prs:
        if base != "main":
            verdict = f"{C['RD']}CLOSE{C['R']} (Base nicht main)"
        elif "iPhone" in title and pr_num < 22:
            verdict = f"{C['RD']}CLOSE{C['R']} (Duplikat — #22 ist neueste Version)"
        elif pr_num == 22:
            verdict = f"{C['YL']}ENTSCHEIDUNG MASTER{C['R']} (iPhone-Arbeit — keep oder close?)"
        elif pr_num == 31:
            verdict = f"{C['YL']}ENTSCHEIDUNG MASTER{C['R']} (UniqueClaw — aktive Arbeit?)"
        else:
            verdict = f"{C['YL']}PRÜFEN{C['R']}"
        print(f"  PR #{pr_num:<3} [{age:>2}d]  {verdict}")
        print(f"         {C['DM']}{title[:45]}{C['R']}")
    print()


COMMANDS = {
    "branches":      cmd_branches,
    "stale-branches": cmd_stale_branches,
    "delete-remote": cmd_delete_remote,
    "health":        cmd_health,
    "pr-targets":    cmd_pr_targets,
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] not in COMMANDS:
        print(__doc__)
        sys.exit(0)
    COMMANDS[args[0]](args[1:])


if __name__ == "__main__":
    main()
