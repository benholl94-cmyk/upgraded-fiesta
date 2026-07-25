#!/usr/bin/env python3
"""
munin_link.py — MUNIN Autonomous Connection Bridge
====================================================
Verbindet: Repo ↔ Chat ↔ Hardware (iPhone/Mobile)

Kanäle:
  repo-status   Aktuellen Branch/CI/PR-Status als JSON schreiben
  broadcast     Status-Datei aktualisieren (lesbar von Gateway + Hardware)
  telegram      Nachricht ans iPhone senden (benötigt MUNIN_TELEGRAM_TOKEN + MUNIN_TELEGRAM_CHAT_ID)
  gateway-cmd   Befehl über Gateway-Webhook empfangen und ausführen
  health        Alle Verbindungen prüfen

Env-Vars (lokal setzen, nie committen):
  MUNIN_TELEGRAM_TOKEN    — Telegram Bot Token
  MUNIN_TELEGRAM_CHAT_ID  — Deine Telegram Chat-ID
  HM_OWNER_TOKEN          — Gateway-Auth (bereits bekannt)
  HM_GATEWAY_BIND         — Gateway-URL (default: http://localhost:8080)
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT    = Path(__file__).parent.parent.parent.parent.parent
STATUS_FILE  = REPO_ROOT / ".claude" / "persona" / "munin-link-status.json"
_DEV_TOKEN_FILE = REPO_ROOT / ".claude" / "persona" / ".dev-token"  # gitignored
GATEWAY_URL  = os.environ.get("HM_GATEWAY_URL", "http://localhost:8080")
OWNER_TOKEN  = os.environ.get("HM_OWNER_TOKEN", "")
TG_TOKEN     = os.environ.get("MUNIN_TELEGRAM_TOKEN", "")
TG_CHAT      = os.environ.get("MUNIN_TELEGRAM_CHAT_ID", "")
GH_TOKEN     = os.environ.get("GITHUB_TOKEN", os.environ.get("MUNIN_GH_TOKEN", ""))
GH_REPO      = "benholl94-cmyk/upgraded-fiesta"
GH_NOTIF_ISSUE = int(os.environ.get("MUNIN_NOTIF_ISSUE", "0"))  # GitHub Issue # als Bus


def _load_dev_token() -> str:
    """Lädt oder generiert einen lokalen Dev-Token (nie committen)."""
    global OWNER_TOKEN
    if OWNER_TOKEN:
        return OWNER_TOKEN
    if _DEV_TOKEN_FILE.exists():
        OWNER_TOKEN = _DEV_TOKEN_FILE.read_text().strip()
        return OWNER_TOKEN
    return ""


def _ensure_dev_token() -> str:
    """Generiert einmalig einen Dev-Token für lokale Gateway-Tests."""
    import secrets
    token = secrets.token_hex(32)
    _DEV_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DEV_TOKEN_FILE.write_text(token + "\n")
    _DEV_TOKEN_FILE.chmod(0o600)
    return token

C = {"B": "\033[1m", "GR": "\033[92m", "YL": "\033[93m",
     "RD": "\033[91m", "DM": "\033[2m", "CY": "\033[96m", "R": "\033[0m"}


def run(cmd: list[str], check=False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=check)


def git_status() -> dict:
    branch   = run(["git", "branch", "--show-current"]).stdout.strip()
    unpushed = run(["git", "rev-list", "origin/HEAD..HEAD", "--count"]).stdout.strip()
    dirty    = bool(run(["git", "status", "--porcelain"]).stdout.strip())
    tip      = run(["git", "log", "-1", "--format=%h %s"]).stdout.strip()
    return {
        "branch":   branch,
        "unpushed": int(unpushed or 0),
        "dirty":    dirty,
        "tip":      tip,
    }


def cmd_repo_status(_args: list[str]) -> None:
    st = git_status()
    print(f"\n{C['B']}── Repo-Status{C['R']}")
    print(f"  Branch   : {st['branch']}")
    print(f"  Tip      : {st['tip']}")
    print(f"  Unpushed : {st['unpushed']}")
    print(f"  Dirty    : {'ja' if st['dirty'] else 'nein'}")
    print()


def cmd_broadcast(args: list[str]) -> None:
    """Status-JSON in .claude/persona/munin-link-status.json schreiben.
    Gateway liefert diese Datei unter GET /memory/munin-link.
    Hardware kann per HTTP pollen.
    """
    message = args[0] if args else "OK"
    st = git_status()
    payload = {
        "ts":      datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "message": message,
        "repo":    st,
        "links": {
            "telegram": bool(TG_TOKEN and TG_CHAT),
            "gateway":  bool(OWNER_TOKEN),
        },
    }
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    # Auch in Gateway-Memory schreiben falls verfügbar
    if OWNER_TOKEN:
        _gateway_post("/memory", {"key": "munin-link-status", "value": json.dumps(payload)})

    print(f"{C['GR']}✓{C['R']} Broadcast: {message}")
    print(f"  → {STATUS_FILE.relative_to(REPO_ROOT)}")
    if OWNER_TOKEN:
        print(f"  → {GATEWAY_URL}/memory (munin-link-status)")


def cmd_telegram(args: list[str]) -> None:
    """Nachricht über Telegram ans iPhone senden."""
    if not TG_TOKEN or not TG_CHAT:
        print(f"{C['YL']}⚠{C['R']} Telegram nicht konfiguriert.")
        print("  export MUNIN_TELEGRAM_TOKEN=<bot-token>")
        print("  export MUNIN_TELEGRAM_CHAT_ID=<chat-id>")
        print()
        print("  Bot erstellen: https://t.me/BotFather → /newbot")
        print("  Chat-ID ermitteln: https://t.me/userinfobot")
        return

    message = args[0] if args else "MUNIN: Kein Text angegeben"
    url  = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    body = json.dumps({"chat_id": TG_CHAT, "text": message, "parse_mode": "Markdown"}).encode()
    req  = urllib.request.Request(url, data=body,
                                   headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        if resp.get("ok"):
            print(f"{C['GR']}✓{C['R']} Telegram → iPhone: {message[:60]}")
        else:
            print(f"{C['RD']}Fehler:{C['R']} {resp}")
    except Exception as e:
        print(f"{C['RD']}Telegram-Fehler:{C['R']} {e}", file=sys.stderr)
        sys.exit(1)


def _gateway_post(path: str, data: dict) -> dict | None:
    if not OWNER_TOKEN:
        return None
    url  = GATEWAY_URL.rstrip("/") + path
    body = json.dumps(data).encode()
    req  = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {OWNER_TOKEN}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _gh_api(method: str, path: str, data: dict | None = None) -> dict | None:
    """GitHub API — verwendet GITHUB_TOKEN oder MUNIN_GH_TOKEN."""
    if not GH_TOKEN:
        return None
    url  = f"https://api.github.com{path}"
    body = json.dumps(data).encode() if data else None
    req  = urllib.request.Request(
        url, data=body, method=method,
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return None


def cmd_gh_notify(args: list[str]) -> None:
    """GitHub-Issue als Notification-Bus — kein Telegram-Token nötig.
    MUNIN postet Statusupdates als Issue-Kommentar → iPhone bekommt GitHub-Notification.

    Setup:
      1. Erstelle ein Issue im Repo (z.B. 'MUNIN Status-Bus')
      2. export MUNIN_NOTIF_ISSUE=<issue-nummer>
      3. export MUNIN_GH_TOKEN=<github-pat-mit-issues-scope>
      4. Aktiviere GitHub-Notifications auf deinem iPhone
    """
    message = args[0] if args else "MUNIN: Status-Update"
    if not GH_TOKEN:
        print(f"{C['YL']}⚠{C['R']} MUNIN_GH_TOKEN nicht gesetzt — GitHub-Notification nicht möglich.")
        print("  export MUNIN_GH_TOKEN=<github-personal-access-token>")
        print("  Scope: issues:write")
        return
    if not GH_NOTIF_ISSUE:
        # Issue automatisch erstellen
        result = _gh_api("POST", f"/repos/{GH_REPO}/issues", {
            "title": "🤖 MUNIN Status-Bus",
            "body": "Dieses Issue dient als Notification-Kanal für MUNIN.\n"
                    "Kommentare hier = MUNIN-Status-Updates → iPhone-Notification.",
            "labels": [],
        })
        if result:
            issue_num = result["number"]
            print(f"{C['GR']}✓{C['R']} Status-Bus Issue erstellt: #{issue_num}")
            print(f"  export MUNIN_NOTIF_ISSUE={issue_num}")
        else:
            print(f"{C['RD']}Fehler:{C['R']} Issue konnte nicht erstellt werden.", file=sys.stderr)
        return

    st     = git_status()
    body   = (f"**MUNIN** `{datetime.now(timezone.utc).strftime('%H:%M UTC')}`\n\n"
              f"{message}\n\n"
              f"```\nbranch: {st['branch']}\ntip: {st['tip']}\n```")
    result = _gh_api("POST", f"/repos/{GH_REPO}/issues/{GH_NOTIF_ISSUE}/comments", {"body": body})
    if result:
        print(f"{C['GR']}✓{C['R']} GitHub-Notification → iPhone: #{GH_NOTIF_ISSUE}")
    else:
        print(f"{C['RD']}Fehler:{C['R']} Kommentar konnte nicht gepostet werden.", file=sys.stderr)


def cmd_init_token(_args: list[str]) -> None:
    """Generiert einen lokalen Dev-Token für Gateway-Tests.
    Dieser Token wird in .claude/persona/.dev-token gespeichert (gitignored).
    Beim Gateway-Start: export HM_OWNER_TOKEN=$(cat .claude/persona/.dev-token)
    """
    existing = _load_dev_token()
    if existing:
        print(f"{C['YL']}⚠{C['R']} Dev-Token existiert bereits.")
        print(f"  Laden: export HM_OWNER_TOKEN=$(cat .claude/persona/.dev-token)")
        return
    token = _ensure_dev_token()
    print(f"{C['GR']}✓{C['R']} Dev-Token generiert: {_DEV_TOKEN_FILE}")
    print(f"  Laden: export HM_OWNER_TOKEN=$(cat .claude/persona/.dev-token)")
    print(f"  Gateway: HM_OWNER_TOKEN=... HM_GATEWAY_ALLOW_NO_AUTH=false cargo run -p hm-gateway")
    print(f"  {C['YL']}Niemals committen — bereits in .gitignore{C['R']}")


def cmd_gateway_cmd(args: list[str]) -> None:
    """Befehl über Gateway-Task-Queue einreichen (Hardware → Chat-Brücke)."""
    if not args:
        print(f"{C['RD']}Fehler:{C['R']} Task-Typ angeben.", file=sys.stderr)
        sys.exit(1)
    task_type = args[0]
    payload   = args[1] if len(args) > 1 else ""
    result    = _gateway_post("/tasks", {"task_type": task_type, "payload": payload})
    if result:
        print(f"{C['GR']}✓{C['R']} Task eingestellt: {task_type} → {result}")
    else:
        print(f"{C['YL']}⚠{C['R']} Gateway nicht erreichbar ({GATEWAY_URL}) — Task lokal geloggt.")
        cmd_broadcast([f"pending-task: {task_type} {payload}"])


def cmd_health(_args: list[str]) -> None:
    print(f"\n{C['B']}── MUNIN-Link Health{C['R']}")

    # 1. Repo
    st = git_status()
    repo_ok = not st["dirty"] and st["unpushed"] == 0
    icon = f"{C['GR']}✓{C['R']}" if repo_ok else f"{C['YL']}⚠{C['R']}"
    print(f"  {icon} Repo: {st['branch']} | tip={st['tip'][:40]}")

    # 2. Status-Datei
    sf_ok = STATUS_FILE.exists()
    icon  = f"{C['GR']}✓{C['R']}" if sf_ok else f"{C['YL']}○{C['R']}"
    age   = ""
    if sf_ok:
        d = json.loads(STATUS_FILE.read_text())
        age = f" | zuletzt: {d.get('ts', '?')}"
    print(f"  {icon} Status-Broadcast{age}")

    # 3. Gateway
    gw_ok = bool(_gateway_post("/health", {})) if OWNER_TOKEN else False
    icon  = f"{C['GR']}✓{C['R']}" if gw_ok else f"{C['YL']}○{C['R']}"
    token_hint = "(kein HM_OWNER_TOKEN)" if not OWNER_TOKEN else GATEWAY_URL
    print(f"  {icon} Gateway: {token_hint}")

    # 4. Telegram
    tg_ok = bool(TG_TOKEN and TG_CHAT)
    icon  = f"{C['GR']}✓{C['R']}" if tg_ok else f"{C['YL']}○{C['R']}"
    hint  = "konfiguriert" if tg_ok else "export MUNIN_TELEGRAM_TOKEN + MUNIN_TELEGRAM_CHAT_ID"
    print(f"  {icon} Telegram: {hint}")

    # 5. CCR-Routine
    print(f"  {C['CY']}●{C['R']} CCR-Routine: via create_trigger konfiguriert (stündlich)")
    print()


COMMANDS = {
    "repo-status":  cmd_repo_status,
    "broadcast":    cmd_broadcast,
    "telegram":     cmd_telegram,
    "gh-notify":    cmd_gh_notify,
    "init-token":   cmd_init_token,
    "gateway-cmd":  cmd_gateway_cmd,
    "health":       cmd_health,
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] not in COMMANDS:
        print(__doc__)
        sys.exit(0)
    COMMANDS[args[0]](args[1:])


if __name__ == "__main__":
    main()
