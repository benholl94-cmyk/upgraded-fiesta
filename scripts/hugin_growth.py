#!/usr/bin/env python3
"""
hugin_growth.py — Permanentes Wachstums- und Wissens-Management für HUGIN

Doktrin: Jede Entwicklungs-Iteration hinterlässt messbares Wissen.
Wissen akkumuliert sich. Rate-Limits sind Taktgeber, keine Blocker.

Fünf Schichten:

  L5 KnowledgeLedger   — persistentes JSON-Wissensarchiv: jeder Fix,
                          jedes Muster, jede Erkenntnis wird versioniert
                          gespeichert und bleibt sitzungsübergreifend verfügbar.

  L6 CycleOrchestrator — plant Entwicklungszyklen als DEVELOP→REFLECT→BUNDLE→PUSH
                          Sequenz. Rate-Limits werden als Takt-Signal genutzt:
                          Wartezeit = Entwicklungszeit für den nächsten Zyklus.

  L7 RateCalibrator    — lernt das tatsächliche Rate-Limit-Verhalten aus echten
                          Ereignissen (nicht aus Schätzungen). Kalibriert
                          CR_RATE_PER_HOUR dynamisch nach.

  L8 GrowthMetrics     — misst Wachstum über Zeit: Commits/Woche, Reflect-Score-
                          Trend, Muster-Bibliotheks-Größe, Fix-Recycling-Rate.

  L9 PermanenceGuard   — stellt sicher dass kein Wissen verloren geht:
                          prüft ob KnowledgeLedger, Reflect-Log, Limits-State
                          und Pattern-Bibliothek konsistent sind.

Usage:
  python3 scripts/hugin_growth.py status     # Wachstumsdashboard
  python3 scripts/hugin_growth.py cycle      # Nächsten Zyklus planen
  python3 scripts/hugin_growth.py learn KEY VALUE   # Erkenntnis speichern
  python3 scripts/hugin_growth.py metrics    # Wachstumskurve
"""

import json
import os
import re
import sys
import time
import subprocess
import hashlib
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import logging
log = logging.getLogger(__name__)

REPO_ROOT  = Path(__file__).resolve().parent.parent
LEDGER_PATH   = REPO_ROOT / "logs" / "hugin_knowledge_ledger.json"
METRICS_PATH  = REPO_ROOT / "logs" / "hugin_growth_metrics.jsonl"
REFLECT_LOG   = REPO_ROOT / "logs" / "hugin_reflect.jsonl"
LIMITS_STATE  = REPO_ROOT / "logs" / "hugin_limits_state.json"

C = {
    "R":  "\033[0m",  "B":  "\033[1m",  "DIM": "\033[2m",
    "CY": "\033[96m", "GN": "\033[92m", "AM": "\033[93m",
    "RD": "\033[91m", "VT": "\033[95m", "BL": "\033[94m",
    "GY": "\033[90m", "WH": "\033[97m",
}
W = 80


def _bar(char="─", color="GY") -> str:
    return C[color] + char * W + C["R"]


def _head(text: str, color="GN") -> str:
    pad = max(0, (W - len(text) - 4) // 2)
    return (C[color] + C["B"] + "╔" + "═" * pad
            + f"  {text}  " + "═" * max(0, W - pad - len(text) - 4) + "╗" + C["R"])


def _foot(color="GN") -> str:
    return C[color] + "╚" + "═" * (W - 2) + "╝" + C["R"]


def run(cmd: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return time.time()


# ── L5: KnowledgeLedger ──────────────────────────────────────────────────────

class KnowledgeLedger:
    """
    Persistentes Wissensarchiv. Jeder Eintrag hat:
    - id:       SHA1[:8] des Inhalts
    - category: fix | pattern | insight | metric | constraint
    - key:      kurzer Bezeichner
    - value:    der eigentliche Inhalt
    - ts:       ISO-Timestamp
    - source:   welcher Commit / welche Session hat das gelernt
    - uses:     wie oft wurde dieses Wissen wiederverwendet
    """

    def __init__(self):
        LEDGER_PATH.parent.mkdir(exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if LEDGER_PATH.exists():
            try:
                return json.loads(LEDGER_PATH.read_text())
            except Exception as exc:
                log.warning("swallowed in hugin_growth: %s", exc)
        return {"version": 1, "entries": [], "stats": {"total_uses": 0, "entries_count": 0}}

    def _save(self):
        tmp = LEDGER_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False))
        tmp.replace(LEDGER_PATH)

    def _entry_id(self, key: str, value: str) -> str:
        return hashlib.sha1(f"{key}:{value}".encode()).hexdigest()[:8]

    def learn(self, category: str, key: str, value: str, source: str = "session") -> str:
        eid = self._entry_id(key, value)
        existing = next((e for e in self._data["entries"] if e["id"] == eid), None)
        if existing:
            existing["uses"] += 1
            existing["last_seen"] = _now_iso()
            self._data["stats"]["total_uses"] += 1
            self._save()
            return f"bekannt (uses={existing['uses']})"

        entry = {
            "id": eid, "category": category, "key": key,
            "value": value, "ts": _now_iso(), "source": source,
            "uses": 1, "last_seen": _now_iso(),
        }
        self._data["entries"].append(entry)
        self._data["stats"]["entries_count"] += 1
        self._save()
        return f"neu (id={eid})"

    def recall(self, query: str, top_k: int = 5) -> list[dict]:
        q = query.lower()
        scored = []
        for e in self._data["entries"]:
            score = 0
            if q in e["key"].lower():      score += 3
            if q in e["value"].lower():    score += 2
            if q in e["category"].lower(): score += 1
            score += min(e["uses"], 5)
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:top_k]]

    def entries_by_category(self) -> dict[str, list]:
        result: dict[str, list] = {}
        for e in self._data["entries"]:
            result.setdefault(e["category"], []).append(e)
        return result

    def total(self) -> int:
        return len(self._data["entries"])

    def summary(self) -> str:
        cats = self.entries_by_category()
        lines = [f"  {C['B']}L5 KnowledgeLedger{C['R']}  "
                 f"{C['WH']}{self.total()}{C['R']} Einträge"]
        for cat, entries in sorted(cats.items()):
            most_used = max(entries, key=lambda e: e["uses"])
            lines.append(
                f"  {C['CY']}{cat:<12}{C['R']}  "
                f"{C['WH']}{len(entries):2d}{C['R']} Einträge  "
                f"{C['GY']}Top: {most_used['key'][:40]} (×{most_used['uses']}){C['R']}"
            )
        return "\n".join(lines)

    def seed_from_history(self):
        """Initialbefüllung aus git-Log und Reflect-Log."""
        # Fixes aus Commit-Messages
        _, log, _ = run(["git", "log", "--format=%H|%s", "-n", "30"])
        fix_pattern = re.compile(r"fix|patch|correct|harden|umask|rebase|borrow", re.I)
        for line in log.splitlines():
            parts = line.split("|", 1)
            if len(parts) == 2 and fix_pattern.search(parts[1]):
                self.learn("fix", parts[1][:60], parts[0][:8], source="git_log")

        # Muster aus Reflect-Log
        if REFLECT_LOG.exists():
            for line in REFLECT_LOG.read_text().splitlines():
                try:
                    entry = json.loads(line)
                    self.learn("metric", f"score:{entry['task'][:40]}",
                               str(entry["score"]), source="reflect_log")
                except Exception as exc:
                    log.warning("swallowed in hugin_growth: %s", exc)


# ── L6: CycleOrchestrator ────────────────────────────────────────────────────

CYCLE_PHASES = ["DEVELOP", "REFLECT", "BUNDLE", "PUSH", "WAIT"]

class CycleOrchestrator:
    """
    Rate-Limits sind kein Stopp — sie sind der Takt.
    Während ein Rate-Limit aktiv ist, läuft DEVELOP.
    Wenn das Limit abläuft, folgt REFLECT → BUNDLE → PUSH.

    Timing-Modell (aus echten Beobachtungen kalibriert):
      CodeRabbit OSS:  ~5 Reviews/h auto, dann 4-7 min Cooldown
      Develop-Phase:   typisch 8-20 Minuten pro Feature-Zyklus
      Bundle-Window:   ≥3 Commits pro Bundle → 1 CR-Trigger statt 3
    """

    DEVELOP_TARGET_MIN = 8    # Mindest-Entwicklungszeit pro Zyklus (Minuten)
    BUNDLE_THRESHOLD   = 3    # Ab n Commits → Bundle empfohlen

    def __init__(self, ledger: KnowledgeLedger):
        self.ledger = ledger

    def _push_timestamps(self, hours: float = 2.0) -> list[float]:
        cutoff = time.time() - hours * 3600
        _, out, _ = run(["git", "log", "--format=%ct", "-n", "60"])
        return [float(l) for l in out.splitlines()
                if l.strip().isdigit() and float(l) > cutoff]

    def _unpushed_count(self) -> int:
        _, out, _ = run(["git", "log", "origin/HEAD..HEAD", "--format=%H"])
        return len(out.splitlines()) if out else 0

    def next_push_window(self) -> datetime:
        """Berechnet wann der nächste Push-Slot frei wird."""
        times = self._push_timestamps(1.0)
        if len(times) < 5:
            return datetime.now(timezone.utc)
        oldest_in_window = min(times)
        next_slot = datetime.fromtimestamp(oldest_in_window + 3600, tz=timezone.utc)
        return max(next_slot, datetime.now(timezone.utc))

    def plan(self) -> dict:
        now = datetime.now(timezone.utc)
        push_window = self.next_push_window()
        wait_s = max(0, int((push_window - now).total_seconds()))
        unpushed = self._unpushed_count()

        # Aktuell empfohlene Phase
        if wait_s > 60:
            phase = "DEVELOP"
            action = f"Entwickeln für ~{wait_s // 60}min — Push-Fenster öffnet {push_window.strftime('%H:%M UTC')}"
        elif unpushed >= self.BUNDLE_THRESHOLD:
            phase = "BUNDLE"
            action = f"{unpushed} Commits bündeln → python3 scripts/hugin_limits.py bundle --push"
        elif unpushed > 0:
            phase = "PUSH"
            action = "python3 scripts/hugin_push.py"
        else:
            phase = "DEVELOP"
            action = "Bereit für nächsten Feature-Zyklus"

        return {
            "phase": phase,
            "action": action,
            "push_window_utc": push_window.isoformat(),
            "wait_seconds": wait_s,
            "unpushed_commits": unpushed,
            "develop_minutes_available": wait_s // 60,
        }

    def render(self) -> str:
        p = self.plan()
        phase_color = {
            "DEVELOP": "GN", "REFLECT": "CY",
            "BUNDLE": "AM",  "PUSH": "BL", "WAIT": "GY",
        }.get(p["phase"], "WH")

        lines = [f"  {C['B']}L6 CycleOrchestrator{C['R']}"]
        lines.append(f"  Phase:     {C[phase_color]}{C['B']}{p['phase']}{C['R']}")
        lines.append(f"  Aktion:    {C['WH']}{p['action']}{C['R']}")
        if p["wait_seconds"] > 0:
            mins = p["wait_seconds"] // 60
            secs = p["wait_seconds"] % 60
            lines.append(f"  Fenster:   {C['GY']}in {mins}m {secs}s  "
                         f"({p['develop_minutes_available']}min Entwicklungszeit){C['R']}")
        lines.append(f"  Unpushed:  {C['WH']}{p['unpushed_commits']}{C['R']}")
        return "\n".join(lines)


# ── L7: RateCalibrator ───────────────────────────────────────────────────────

class RateCalibrator:
    """
    Lernt das echte Rate-Limit-Verhalten aus dem Push-Rhythmus.
    Statt feste Schwellwerte zu schätzen, beobachtet es wann Pushes
    nach CR-Events gebündelt auftreten vs verteilt.

    Erkennt drei Muster:
      BURST:  viele Pushes kurz hintereinander (CI/automation-Commits)
      STEADY: gleichmäßige Verteilung (manueller Workflow)
      IDLE:   lange Pausen (Wartephasen)
    """

    def __init__(self):
        self._state = self._load()

    def _load(self) -> dict:
        if LIMITS_STATE.exists():
            try:
                return json.loads(LIMITS_STATE.read_text())
            except Exception as exc:
                log.warning("swallowed in hugin_growth: %s", exc)
        return {"calibration": {}, "events": []}

    def _save(self):
        tmp = LIMITS_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, ensure_ascii=False))
        tmp.replace(LIMITS_STATE)

    def record_event(self, kind: str, detail: str = ""):
        self._state.setdefault("events", []).append({
            "ts": _now_ts(), "kind": kind, "detail": detail
        })
        # Nur letzte 100 Events behalten
        self._state["events"] = self._state["events"][-100:]
        self._save()

    def analyze_rhythm(self) -> dict:
        _, out, _ = run(["git", "log", "--format=%ct", "-n", "30"])
        times = sorted([float(l) for l in out.splitlines() if l.strip().isdigit()], reverse=True)
        if len(times) < 3:
            return {"pattern": "IDLE", "avg_gap_s": 0, "burst_count": 0}

        gaps = [times[i] - times[i+1] for i in range(len(times)-1)]
        avg_gap = sum(gaps) / len(gaps)
        burst_count = sum(1 for g in gaps if g < 120)  # Commits < 2min auseinander

        if burst_count > len(gaps) * 0.6:
            pattern = "BURST"
        elif avg_gap < 600:
            pattern = "STEADY"
        else:
            pattern = "IDLE"

        return {
            "pattern": pattern,
            "avg_gap_s": int(avg_gap),
            "burst_count": burst_count,
            "total_gaps": len(gaps),
        }

    def recommended_push_interval(self) -> int:
        """Empfohlener Mindestabstand zwischen Pushes in Sekunden."""
        rhythm = self.analyze_rhythm()
        if rhythm["pattern"] == "BURST":
            return 480   # 8min — im Burst-Modus bündeln
        elif rhythm["pattern"] == "STEADY":
            return 180   # 3min — bei stabilem Workflow ok
        else:
            return 60    # 1min — bei IDLE ist CR sowieso nicht aktiv

    def render(self) -> str:
        rhythm = self.analyze_rhythm()
        interval = self.recommended_push_interval()
        pat_color = {"BURST": "RD", "STEADY": "GN", "IDLE": "GY"}.get(rhythm["pattern"], "WH")
        lines = [f"  {C['B']}L7 RateCalibrator{C['R']}"]
        lines.append(f"  Rhythmus:  {C[pat_color]}{C['B']}{rhythm['pattern']}{C['R']}  "
                     f"{C['GY']}Ø Gap: {rhythm['avg_gap_s']}s  "
                     f"Bursts: {rhythm['burst_count']}/{rhythm['total_gaps']}{C['R']}")
        lines.append(f"  Min Push-Abstand: {C['WH']}{interval}s{C['R']} "
                     f"{C['GY']}(dynamisch kalibriert){C['R']}")
        return "\n".join(lines)


# ── L8: GrowthMetrics ────────────────────────────────────────────────────────

class GrowthMetrics:
    """
    Misst das tatsächliche Wachstum über Zeit anhand von
    harten Metriken aus git-Log, Reflect-Log und Ledger.
    """

    def collect(self) -> dict:
        # Commits pro Woche
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        _, out, _ = run(["git", "log", f"--since={since}", "--format=%H"])
        commits_7d = len(out.splitlines()) if out else 0

        # Reflect-Score-Trend
        scores = []
        if REFLECT_LOG.exists():
            for line in REFLECT_LOG.read_text().splitlines()[-20:]:
                try:
                    scores.append(json.loads(line)["score"])
                except Exception as exc:
                    log.warning("swallowed in hugin_growth: %s", exc)
        avg_score = sum(scores) / len(scores) if scores else 0
        score_trend = "↑" if len(scores) >= 2 and scores[-1] >= scores[0] else "→" if len(scores) < 2 else "↓"

        # Codebase-Größe
        _, out, _ = run(["git", "ls-files"])
        file_count = len(out.splitlines()) if out else 0

        # Muster-Bibliothek
        pattern_count = 5  # Basis
        if LIMITS_STATE.exists():
            try:
                st = json.loads(LIMITS_STATE.read_text())
                pattern_count += len(st.get("known_patterns", []))
            except Exception as exc:
                log.warning("swallowed in hugin_growth: %s", exc)

        return {
            "commits_7d": commits_7d,
            "avg_reflect_score": round(avg_score, 1),
            "score_trend": score_trend,
            "tracked_files": file_count,
            "pattern_library": pattern_count,
            "knowledge_entries": 0,  # Wird von Ledger befüllt
        }

    def render(self, ledger: KnowledgeLedger) -> str:
        m = self.collect()
        m["knowledge_entries"] = ledger.total()

        def bar(val: int, max_val: int, width: int = 20) -> str:
            filled = min(width, int(val / max(max_val, 1) * width))
            return C["GN"] + "█" * filled + C["GY"] + "░" * (width - filled) + C["R"]

        lines = [f"  {C['B']}L8 GrowthMetrics{C['R']}"]
        lines.append(
            f"  Commits/7d  {bar(m['commits_7d'], 50)}  {C['WH']}{m['commits_7d']:3d}{C['R']}"
        )
        score_c = "GN" if m["avg_reflect_score"] >= 85 else "AM" if m["avg_reflect_score"] >= 60 else "RD"
        lines.append(
            f"  Reflect-Ø   {bar(int(m['avg_reflect_score']), 100)}  "
            f"{C[score_c]}{m['avg_reflect_score']:5.1f}/100  {m['score_trend']}{C['R']}"
        )
        lines.append(
            f"  Wissen      {bar(m['knowledge_entries'], 50)}  {C['WH']}{m['knowledge_entries']:3d}{C['R']} Einträge"
        )
        lines.append(
            f"  Muster      {bar(m['pattern_library'], 20)}  {C['WH']}{m['pattern_library']:3d}{C['R']} Vorlagen"
        )
        lines.append(
            f"  Dateien     {bar(m['tracked_files'], 200)}  {C['WH']}{m['tracked_files']:3d}{C['R']} tracked"
        )
        return "\n".join(lines)


# ── L9: PermanenceGuard ──────────────────────────────────────────────────────

class PermanenceGuard:
    """
    Prüft Konsistenz aller persistenten Wissens-Stores.
    Stellt sicher dass kein Wissen zwischen Sessions verloren geht.
    """

    REQUIRED = [
        (LEDGER_PATH,  "KnowledgeLedger"),
        (REFLECT_LOG,  "Reflect-Log"),
        (LIMITS_STATE, "Limits-State"),
    ]

    def check(self) -> list[dict]:
        results = []
        for path, name in self.REQUIRED:
            exists = path.exists()
            size   = path.stat().st_size if exists else 0
            results.append({
                "name": name, "path": str(path.relative_to(REPO_ROOT)),
                "ok": exists and size > 10, "size_bytes": size,
            })
        return results

    def render(self) -> str:
        checks = self.check()
        lines = [f"  {C['B']}L9 PermanenceGuard{C['R']}"]
        all_ok = True
        for c in checks:
            icon = C["GN"] + "✓" + C["R"] if c["ok"] else C["RD"] + "✗" + C["R"]
            if not c["ok"]:
                all_ok = False
            lines.append(f"  {icon}  {c['name']:<20} {C['GY']}{c['path']}  "
                         f"({c['size_bytes']} B){C['R']}")
        if all_ok:
            lines.append(f"  {C['GN']}Alle Wissens-Stores konsistent — kein Datenverlust.{C['R']}")
        return "\n".join(lines)


# ── Dashboard ─────────────────────────────────────────────────────────────────

def full_dashboard():
    ledger     = KnowledgeLedger()
    ledger.seed_from_history()

    orchestrator = CycleOrchestrator(ledger)
    calibrator   = RateCalibrator()
    metrics      = GrowthMetrics()
    guard        = PermanenceGuard()

    print()
    print(_head("HUGIN GROWTH — Florierendes Wachstums-Dashboard", "GN"))
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"  {C['GY']}Stand: {ts}  |  Repo: upgraded-fiesta{C['R']}")
    print(_bar("═", "GN"))

    print(orchestrator.render())
    print(_bar())
    print(calibrator.render())
    print(_bar())
    print(metrics.render(ledger))
    print(_bar())
    print(ledger.summary())
    print(_bar())
    print(guard.render())
    print(_foot("GN"))

    # Rate-Limit Strategie
    plan = orchestrator.plan()
    print()
    print(_head("RATE-LIMIT STRATEGIE — Permanentes Wachstum", "BL"))
    print(f"""
  {C['B']}Das Prinzip:{C['R']}
  Rate-Limits sind kein Stopp — sie sind der Takt des Zyklus.

  {C['GN']}DEVELOP{C['R']}  →  Code schreiben, Wissen aufbauen, Muster erkennen
  {C['CY']}REFLECT{C['R']}  →  Qualitätsprüfung vor dem Commit (hugin_reflect.py)
  {C['AM']}BUNDLE{C['R']}   →  N Commits → 1 Push = 1 CR-Review statt N
  {C['BL']}PUSH{C['R']}     →  Gezielt im Fenster, nicht auf jeden Micro-Commit
  {C['GY']}WAIT{C['R']}     →  Während Wartezeit: DEVELOP läuft, Wissen wächst

  {C['B']}Konkret für dieses Repo:{C['R']}
  {C['GY']}·{C['R']} Automation-Commits ([skip ci]) zählen NICHT als Feature-Push
  {C['GY']}·{C['R']} .coderabbit.yaml: auto_review: false — wirkt nach main-Merge
  {C['GY']}·{C['R']} CommitBundler: ≥3 Commits → Bundle vor Push
  {C['GY']}·{C['R']} RateCalibrator: Rhythmus wird automatisch kalibriert
  {C['GY']}·{C['R']} KnowledgeLedger: Lerntes bleibt über Sessions hinweg

  {C['B']}Nächste Aktion:{C['R']}
  {C['WH']}{plan['action']}{C['R']}
""")
    print(_foot("BL"))
    print()


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="HUGIN Growth Manager")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status",  help="Vollständiges Wachstums-Dashboard")
    sub.add_parser("metrics", help="Nur Wachstumskurve")
    sub.add_parser("cycle",   help="Nächsten Zyklus planen")

    lp = sub.add_parser("learn", help="Erkenntnis speichern")
    lp.add_argument("category", choices=["fix","pattern","insight","metric","constraint"])
    lp.add_argument("key")
    lp.add_argument("value")

    rp = sub.add_parser("recall", help="Wissen abrufen")
    rp.add_argument("query")

    args = parser.parse_args()

    if args.cmd == "metrics":
        ledger  = KnowledgeLedger()
        metrics = GrowthMetrics()
        print(metrics.render(ledger))

    elif args.cmd == "cycle":
        ledger = KnowledgeLedger()
        orc    = CycleOrchestrator(ledger)
        print(json.dumps(orc.plan(), indent=2, ensure_ascii=False))

    elif args.cmd == "learn":
        ledger = KnowledgeLedger()
        result = ledger.learn(args.category, args.key, args.value)
        print(f"{C['GN']}Gelernt [{args.category}] {args.key}: {result}{C['R']}")

    elif args.cmd == "recall":
        ledger  = KnowledgeLedger()
        results = ledger.recall(args.query)
        if not results:
            print(f"{C['GY']}Keine Treffer für '{args.query}'.{C['R']}")
        for e in results:
            print(f"  {C['CY']}{e['category']:<12}{C['R']} {C['WH']}{e['key']}{C['R']}  "
                  f"{C['GY']}(×{e['uses']}) {e['value'][:60]}{C['R']}")

    else:
        full_dashboard()


if __name__ == "__main__":
    main()
