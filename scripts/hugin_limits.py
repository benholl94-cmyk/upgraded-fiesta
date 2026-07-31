#!/usr/bin/env python3
"""
hugin_limits.py — Permanentes Limit-Management für HUGIN-Entwicklung

Vier eigenentwickelte Module ohne externe Abhängigkeiten:

  L1 CommitBundler   — akkumuliert Änderungen, fasst sie zu einem Commit zusammen.
                       Verhindert, dass jeder Micro-Push einen separaten CI/Review-Zyklus auslöst.

  L2 RateGuard       — schätzt den verfügbaren Review-Kontingent (CodeRabbit, CI-Minuten)
                       aus dem Commit-Rhythmus ab und empfiehlt Pause-Fenster.

  L3 ReviewRecycler  — liest bestehende Review-Threads aus dem Git-Log und identifiziert
                       Muster, die in zukünftigen Commits wiederverwendet werden können
                       (z.B. wiederkehrende Fixes → Vorlage erzeugen).

  L4 FlowKeeper      — koppelt L1+L2+L3: entscheidet autonom ob sofort pushen,
                       bündeln oder warten. Gibt Empfehlung als maschinenlesbare
                       Entscheidung aus (JSON), die hugin_push.py konsumieren kann.

Usage:
  python3 scripts/hugin_limits.py status          # Aktueller Zustand aller Module
  python3 scripts/hugin_limits.py bundle [--push] # Staged Commits bündeln (optional pushen)
  python3 scripts/hugin_limits.py advice          # FlowKeeper-Empfehlung abrufen
  python3 scripts/hugin_limits.py recycle         # ReviewRecycler — Muster-Analyse
"""

import subprocess
import json
import os
import re
import time
import sys
import argparse
import hashlib
from dataclasses import dataclass, asdict
from typing import Optional
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent
LIMITS_STATE = REPO_ROOT / "logs" / "hugin_limits_state.json"

# ANSI
C = {
    "R":  "\033[0m",  "B":  "\033[1m",  "DIM": "\033[2m",
    "CY": "\033[96m", "GN": "\033[92m", "AM": "\033[93m",
    "RD": "\033[91m", "VT": "\033[95m", "GY": "\033[90m",
    "WH": "\033[97m",
}
W = 80


def _bar(color="GY") -> str:
    return C[color] + "─" * W + C["R"]


def _head(text: str, color="VT") -> str:
    pad = (W - len(text) - 4) // 2
    return (C[color] + C["B"] + "╔" + "═" * pad
            + f"  {text}  " + "═" * (W - pad - len(text) - 4) + "╗" + C["R"])


def _foot(color="VT") -> str:
    return C[color] + "╚" + "═" * (W - 2) + "╝" + C["R"]


def run(cmd: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


# ── State-Persistenz ─────────────────────────────────────────────────────────

def _load_state() -> dict:
    LIMITS_STATE.parent.mkdir(exist_ok=True)
    if LIMITS_STATE.exists():
        try:
            return json.loads(LIMITS_STATE.read_text())
        except Exception as exc:
            log.warning("swallowed in hugin_limits: %s", exc)
    return {"bundle_queue": [], "push_history": [], "known_patterns": []}


def _save_state(state: dict):
    LIMITS_STATE.parent.mkdir(exist_ok=True)
    tmp = LIMITS_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    tmp.replace(LIMITS_STATE)


# ── L1: CommitBundler ────────────────────────────────────────────────────────

@dataclass
class BundleEntry:
    message: str
    files: list[str]
    ts: float


class CommitBundler:
    """
    Akkumuliert lokale Commits und fasst sie in einem einzigen squash-Commit zusammen.
    Reduziert CI-Trigger und CodeRabbit-Reviews auf das Minimum.

    Strategie: Alle Commits seit dem letzten Push werden als ein Commit
    interaktiv rebased (squash). Commit-Messages werden in Bullet-Liste vereint.
    """

    def __init__(self, state: dict):
        self.state = state

    def unpushed_commits(self) -> list[dict]:
        """Commits die lokal vorhanden aber noch nicht gepusht sind."""
        _, out, _ = run(["git", "log", "origin/HEAD..HEAD", "--format=%H|%s|%ai"])
        if not out:
            return []
        result = []
        for line in out.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                result.append({"hash": parts[0][:8], "subject": parts[1], "date": parts[2]})
        return result

    def staged_diff_files(self) -> list[str]:
        _, out, _ = run(["git", "diff", "--cached", "--name-only"])
        return out.splitlines() if out else []

    def bundle_and_squash(self, push: bool = False) -> bool:
        """
        Squasht alle unpushed Commits in einen einzigen.
        Erzeugt eine zusammenfassende Commit-Message aus allen Einzelnachrichten.
        """
        commits = self.unpushed_commits()
        if len(commits) < 2:
            print(f"  {C['GY']}Nur {len(commits)} unpushed commit(s) — kein Bundle nötig.{C['R']}")
            return False

        subjects = [c["subject"] for c in commits]
        bundle_msg = "bundle: " + "; ".join(subjects[:3])
        if len(subjects) > 3:
            bundle_msg += f" (+{len(subjects)-3} weitere)"

        print(f"  {C['CY']}Bündele {len(commits)} Commits → 1 squash-Commit:{C['R']}")
        for c in commits:
            print(f"  {C['GY']}  {c['hash']}  {c['subject']}{C['R']}")

        # Soft-reset auf origin/HEAD → alle Änderungen wieder staged
        _, remote_head, _ = run(["git", "rev-parse", "origin/HEAD"])
        if not remote_head:
            print(f"  {C['RD']}origin/HEAD nicht auflösbar — Bundle abgebrochen.{C['R']}")
            return False

        code, _, err = run(["git", "reset", "--soft", remote_head])
        if code != 0:
            print(f"  {C['RD']}Soft-reset fehlgeschlagen: {err[:80]}{C['R']}")
            return False

        # Einziger squash-Commit
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        full_msg = (f"{bundle_msg}\n\n"
                    f"Enthält {len(commits)} Commits (gebündelt {ts}):\n" +
                    "\n".join(f"  - {s}" for s in subjects) +
                    "\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>")
        code, _, err = run(["git", "commit", "-m", full_msg])
        if code != 0:
            print(f"  {C['RD']}Commit fehlgeschlagen: {err[:80]}{C['R']}")
            return False

        print(f"  {C['GN']}✓ Bundle-Commit erstellt: {bundle_msg[:60]}{C['R']}")

        if push:
            import hugin_push
            guard = hugin_push.StatusGuard()
            if not guard.check():
                print(f"  {C['RD']}Push durch StatusGuard blockiert (staged secrets){C['R']}")
                return False
            return hugin_push.retry_push(hugin_push.DEFAULT_BRANCH)

        return True

    def status(self) -> str:
        commits = self.unpushed_commits()
        staged = self.staged_diff_files()
        lines = [f"  {C['B']}L1 CommitBundler{C['R']}"]
        lines.append(f"  Unpushed:  {C['WH']}{len(commits)}{C['R']} Commit(s)")
        lines.append(f"  Staged:    {C['WH']}{len(staged)}{C['R']} Datei(en)")
        if commits:
            for c in commits[:4]:
                lines.append(f"  {C['GY']}  {c['hash']}  {c['subject'][:55]}{C['R']}")
        return "\n".join(lines)


# ── L2: RateGuard ────────────────────────────────────────────────────────────

# CodeRabbit: ~5 reviews/Stunde im Free/Pro plan, dann ~4min cooldown
# GitHub Actions: unbegrenzt bei Public repos, 2000min/Monat bei Private
CR_RATE_PER_HOUR = 5
CR_COOLDOWN_S    = 240   # 4 Minuten Cooldown nach Limit-Erreichen
CI_HEAVY_PATHS   = ["crates/", "ui/src/", ".github/workflows/"]


class RateGuard:
    """
    Schätzt aus dem lokalen Push-Rhythmus (git log timestamps) ab,
    ob ein Push gerade sicher ist oder eine Pause ratsam wäre.
    Kein API-Zugriff — rein aus lokalen Zeitstempeln abgeleitet.
    """

    def __init__(self, state: dict):
        self.state = state

    def recent_push_times(self, hours: float = 1.0) -> list[float]:
        """Liest Commit-Timestamps der letzten `hours` Stunden aus git log."""
        cutoff = time.time() - hours * 3600
        _, out, _ = run(["git", "log", "--format=%ct", "-n", "50"])
        times = []
        for line in out.splitlines():
            try:
                t = float(line.strip())
                if t > cutoff:
                    times.append(t)
            except ValueError as exc:
                log.warning("swallowed in hugin_limits: %s", exc)
        return times

    def pushes_trigger_heavy_ci(self, files: list[str]) -> bool:
        return any(
            any(f.startswith(prefix) for prefix in CI_HEAVY_PATHS)
            for f in files
        )

    def advice(self, staged_files: list[str] | None = None) -> dict:
        """
        Gibt eine Empfehlung als dict zurück:
        {action: push|wait|bundle, reason: str, wait_seconds: int}
        """
        recent = self.recent_push_times(1.0)
        count_last_hour = len(recent)

        if count_last_hour >= CR_RATE_PER_HOUR:
            youngest = max(recent) if recent else time.time()
            wait_s = max(0, int(CR_COOLDOWN_S - (time.time() - youngest)))
            return {
                "action": "wait",
                "reason": f"{count_last_hour} Pushes in letzter Stunde ≥ CR-Limit ({CR_RATE_PER_HOUR})",
                "wait_seconds": wait_s,
            }

        if staged_files and self.pushes_trigger_heavy_ci(staged_files):
            if count_last_hour >= 3:
                return {
                    "action": "bundle",
                    "reason": "Heavy-CI-Pfade geändert + hoher Push-Rhythmus → bündeln",
                    "wait_seconds": 0,
                }

        return {
            "action": "push",
            "reason": f"Nur {count_last_hour}/{CR_RATE_PER_HOUR} Pushes in letzter Stunde — sicher",
            "wait_seconds": 0,
        }

    def status(self) -> str:
        recent = self.recent_push_times(1.0)
        adv = self.advice()
        action_color = {"push": "GN", "wait": "RD", "bundle": "AM"}.get(adv["action"], "WH")
        lines = [f"  {C['B']}L2 RateGuard{C['R']}"]
        lines.append(f"  Pushes/h:  {C['WH']}{len(recent)}/{CR_RATE_PER_HOUR}{C['R']}")
        lines.append(f"  Empfehlung: {C[action_color]}{C['B']}{adv['action'].upper()}{C['R']}  "
                     f"{C['GY']}{adv['reason']}{C['R']}")
        if adv["wait_seconds"] > 0:
            lines.append(f"  Warten:    {C['AM']}{adv['wait_seconds']}s{C['R']}")
        return "\n".join(lines)


# ── L3: ReviewRecycler ───────────────────────────────────────────────────────

# Bekannte Muster-Kategorien mit Fix-Vorlagen
_KNOWN_PATTERNS = [
    {
        "id": "umask_token",
        "name": "Token-Datei umask-Härtung",
        "trigger": r"(printf|echo).*>.*TOKEN|chmod 600",
        "template": "(umask 077; {write_cmd})\nchmod 600 {file}",
        "applies_to": ["*.sh"],
    },
    {
        "id": "host_ip_fallback",
        "name": "HOST_IP Fallback-Logik",
        "trigger": r"hostname -I.*awk.*fallback|HOST_IP.*echo 127",
        "template": 'HOST_IP="$(ipconfig getifaddr en0 2>/dev/null \\\n  || hostname -I 2>/dev/null | awk \'{{print $1}}\'\')\n[ -n "$HOST_IP" ] || HOST_IP=\'127.0.0.1\'',
        "applies_to": ["*.sh"],
    },
    {
        "id": "deep_merge_state",
        "name": "JS State Deep-Merge (nested keys)",
        "trigger": r"Object\.assign\(default\w+\(\),\s*STATE\)",
        "template": "const base = defaultState();\nSTATE = Object.assign(base, STATE, { keys: Object.assign(base.keys, STATE.keys || {}) });",
        "applies_to": ["*.html", "*.js", "*.ts"],
    },
    {
        "id": "borrow_checker_sort",
        "name": "Rust E0502 — Scores vorausberechnen statt inline sort",
        "trigger": r"sort_by.*self\.nodes|self\.nodes.*sort_by",
        "template": "let mut scored: Vec<(usize, f32)> = self.nodes[nb].neighbors.iter()\n    .map(|&i| (i, cosine_similarity(&nb_vec, &self.nodes[i].vector)))\n    .collect();\nscored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());\nself.nodes[nb].neighbors = scored.into_iter().map(|(i, _)| i).collect();",
        "applies_to": ["*.rs"],
    },
    {
        "id": "exponential_backoff",
        "name": "Exponentieller Backoff bei Retry",
        "trigger": r"retry|backoff|attempt.*sleep|sleep.*attempt",
        "template": "for attempt in range(1, MAX_RETRIES + 1):\n    delay = BASE ** attempt\n    # ... try action ...\n    time.sleep(delay)",
        "applies_to": ["*.py"],
    },
]


class ReviewRecycler:
    """
    Scannt den aktuellen Diff und den git-Log auf bekannte Muster.
    Gibt anwendbare Fix-Vorlagen zurück, die direkt in neue Änderungen übernommen werden können.
    Erweitert die Vorlagen-Bibliothek aus erkannten Fixes im Commit-Log.
    """

    def __init__(self, state: dict):
        self.state = state
        self.patterns = list(_KNOWN_PATTERNS)
        # Aus State geladene gelernte Muster einbinden
        for p in state.get("known_patterns", []):
            if p["id"] not in {x["id"] for x in self.patterns}:
                self.patterns.append(p)

    def scan_diff(self) -> list[dict]:
        """Scannt den aktuellen Diff gegen alle bekannten Muster."""
        _, diff, _ = run(["git", "diff", "HEAD", "--unified=0"])
        if not diff:
            _, diff, _ = run(["git", "diff", "--cached", "--unified=0"])

        matches = []
        for pat in self.patterns:
            if re.search(pat["trigger"], diff, re.IGNORECASE):
                matches.append(pat)
        return matches

    def scan_log(self, n: int = 20) -> list[dict]:
        """Analysiert die letzten n Commits auf Muster in Commit-Messages."""
        _, out, _ = run(["git", "log", f"-n{n}", "--format=%s"])
        found = []
        for pat in self.patterns:
            for line in out.splitlines():
                if re.search(pat["trigger"], line, re.IGNORECASE):
                    found.append({**pat, "_source": "log", "_line": line})
                    break
        return found

    def learn(self, pattern_id: str, name: str, trigger: str, template: str, applies_to: list[str]):
        """Fügt ein neues gelerntes Muster zur Bibliothek hinzu."""
        new_pat = {
            "id": pattern_id, "name": name, "trigger": trigger,
            "template": template, "applies_to": applies_to
        }
        existing = {p["id"] for p in self.state.get("known_patterns", [])}
        if pattern_id not in existing:
            self.state.setdefault("known_patterns", []).append(new_pat)
            self.patterns.append(new_pat)
            _save_state(self.state)
            return True
        return False

    def recycle_report(self) -> str:
        diff_matches = self.scan_diff()
        log_matches  = self.scan_log()
        lines = [f"  {C['B']}L3 ReviewRecycler{C['R']}",
                 f"  Bibliothek: {C['WH']}{len(self.patterns)}{C['R']} Muster"]

        if diff_matches:
            lines.append(f"\n  {C['CY']}Anwendbar auf aktuellen Diff:{C['R']}")
            for m in diff_matches:
                lines.append(f"  {C['GN']}▸{C['R']}  {C['WH']}{m['name']}{C['R']}")
                lines.append(f"  {C['GY']}    Gilt für: {', '.join(m['applies_to'])}{C['R']}")
        else:
            lines.append(f"  {C['GY']}Keine Muster-Treffer im aktuellen Diff.{C['R']}")

        if log_matches:
            lines.append(f"\n  {C['AM']}Wiederkehrende Muster im Commit-Log:{C['R']}")
            for m in log_matches[:3]:
                lines.append(f"  {C['AM']}△{C['R']}  {m['name']}")

        return "\n".join(lines)

    def status(self) -> str:
        return self.recycle_report()


# ── L4: FlowKeeper ───────────────────────────────────────────────────────────

class FlowKeeper:
    """
    Koppelt L1+L2+L3 zu einer autonomen Entscheidungseinheit.
    Analysiert den aktuellen Zustand und gibt eine Empfehlung aus,
    die von hugin_push.py als JSON konsumiert werden kann.
    """

    def __init__(self):
        self.state = _load_state()
        self.bundler  = CommitBundler(self.state)
        self.guard    = RateGuard(self.state)
        self.recycler = ReviewRecycler(self.state)

    def decide(self) -> dict:
        unpushed = self.bundler.unpushed_commits()
        staged   = self.bundler.staged_diff_files()
        adv      = self.guard.advice(staged)
        patterns = self.recycler.scan_diff()

        decision = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "unpushed_commits": len(unpushed),
            "staged_files": len(staged),
            "rate_advice": adv,
            "applicable_patterns": [p["id"] for p in patterns],
            "recommended_action": adv["action"],
            "reasoning": [],
        }

        # Logik-Kaskade
        if len(unpushed) >= 4:
            decision["recommended_action"] = "bundle"
            decision["reasoning"].append(f"{len(unpushed)} unpushed Commits → Bundle empfohlen")
        elif adv["action"] == "wait":
            decision["reasoning"].append(adv["reason"])
        elif adv["action"] == "bundle":
            decision["reasoning"].append(adv["reason"])
        else:
            decision["reasoning"].append(adv["reason"])

        if patterns:
            decision["reasoning"].append(
                f"{len(patterns)} Recycler-Muster anwendbar: "
                + ", ".join(p["name"] for p in patterns[:2])
            )

        return decision

    def full_status(self):
        print()
        print(_head("HUGIN LIMITS — Permanentes Entwicklungs-Limit-Management", "VT"))

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        print(f"  {C['GY']}Stand: {ts}{C['R']}")
        print(_bar())

        print(self.bundler.status())
        print(_bar())
        print(self.guard.status())
        print(_bar())
        print(self.recycler.status())
        print(_bar())

        dec = self.decide()
        action_color = {"push": "GN", "wait": "RD", "bundle": "AM"}.get(dec["recommended_action"], "WH")
        print(f"  {C['B']}L4 FlowKeeper — Gesamtentscheidung{C['R']}")
        print(f"  Aktion:   {C[action_color]}{C['B']}{dec['recommended_action'].upper()}{C['R']}")
        for r in dec["reasoning"]:
            print(f"  {C['GY']}· {r}{C['R']}")

        print(_foot())
        print()

        # State speichern
        _save_state(self.state)
        return dec


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="HUGIN Limit-Management")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status",  help="Status aller Module anzeigen")
    sub.add_parser("advice",  help="FlowKeeper-Empfehlung als JSON")
    sub.add_parser("recycle", help="ReviewRecycler Muster-Bericht")

    bp = sub.add_parser("bundle", help="Commits bündeln (optional pushen)")
    bp.add_argument("--push", action="store_true", help="Nach Bundle direkt pushen")

    lp = sub.add_parser("learn", help="Neues Muster lernen")
    lp.add_argument("--id",       required=True)
    lp.add_argument("--name",     required=True)
    lp.add_argument("--trigger",  required=True)
    lp.add_argument("--template", required=True)
    lp.add_argument("--ext",      nargs="+", default=["*"])

    args = parser.parse_args()
    fk = FlowKeeper()

    if args.cmd == "status" or args.cmd is None:
        fk.full_status()

    elif args.cmd == "advice":
        print(json.dumps(fk.decide(), indent=2, ensure_ascii=False))

    elif args.cmd == "bundle":
        dec = fk.decide()
        if dec["recommended_action"] == "wait":
            print(f"{C['RD']}RateGuard empfiehlt Warten: {dec['rate_advice']['reason']}{C['R']}")
            sys.exit(1)
        ok = fk.bundler.bundle_and_squash(push=args.push)
        sys.exit(0 if ok else 1)

    elif args.cmd == "recycle":
        print(fk.recycler.recycle_report())

    elif args.cmd == "learn":
        ok = fk.recycler.learn(args.id, args.name, args.trigger, args.template, args.ext)
        if ok:
            print(f"{C['GN']}Muster '{args.id}' gelernt.{C['R']}")
        else:
            print(f"{C['AM']}Muster '{args.id}' bereits bekannt.{C['R']}")


if __name__ == "__main__":
    main()
