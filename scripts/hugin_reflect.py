#!/usr/bin/env python3
"""
hugin_reflect.py — Asynchroner Selbst-Reflexions-Logger für HUGIN

Doktrin: Vor jeder Ausgabe transkribiert das System seine eigene Arbeit in ein
strukturiertes Snapshot-Bild. Dieses Bild wird dann auf Logik, Qualität und
Konsistenz geprüft. Erkannte Mängel werden als korrigierbare Befunde markiert
BEVOR der finale Output produziert wird.

Drei Schichten:
  L1 WorkLedger      — erfasst jeden Schritt (plan / exec / verify / fix)
  L2 ReflectEngine   — analysiert das Ledger auf 6 Qualitätsdimensionen
  L3 SnapshotPrinter — rendert das Transkript als ASCII-Bild zur Sichtkontrolle

Nutzung:
  from hugin_reflect import task

  with task("Feat: NSW Graph") as t:
      t.plan("Dreifach-Hash + NSW einbauen")
      t.exec("crates/hm-vector/src/lib.rs", "Neu: VectorIndex mit NSW-Graph")
      t.verify("cargo test --workspace", passed=True, detail="7/7 OK")
      t.fix("E0502 borrow checker", "Scores in Vec<(usize,f32)> vorausberechnen")
  # → Snapshot wird vor dem return automatisch gedruckt + geprüft

Standalone:
  python3 scripts/hugin_reflect.py --demo
"""

import time
import sys
import os
import re
import json
import hashlib
import threading
import argparse
from dataclasses import dataclass, field
from typing import Optional
from contextlib import contextmanager

# ── ANSI-Palette ─────────────────────────────────────────────────────────────

C = {
    "R":  "\033[0m",
    "B":  "\033[1m",
    "DIM": "\033[2m",
    "CY": "\033[96m",
    "GN": "\033[92m",
    "AM": "\033[93m",
    "RD": "\033[91m",
    "VT": "\033[95m",
    "BL": "\033[94m",
    "GY": "\033[90m",
    "WH": "\033[97m",
}

WIDTH = 80


def _bar(char="─", width=WIDTH, color="GY") -> str:
    return C[color] + char * width + C["R"]


def _head(text: str, color="CY") -> str:
    pad = (WIDTH - len(text) - 4) // 2
    return C[color] + C["B"] + "╔" + "═" * pad + f"  {text}  " + "═" * (WIDTH - pad - len(text) - 4) + "╗" + C["R"]


def _foot(color="CY") -> str:
    return C[color] + "╚" + "═" * (WIDTH - 2) + "╝" + C["R"]


# ── Datenstrukturen ───────────────────────────────────────────────────────────

@dataclass
class LedgerEntry:
    kind: str          # plan | exec | verify | fix | note
    content: str
    detail: str = ""
    passed: Optional[bool] = None
    ts: float = field(default_factory=time.time)


@dataclass
class QualitySignal:
    dim: str           # logic | security | completeness | consistency | clarity | efficiency
    severity: str      # ok | warn | error
    message: str
    fix: str = ""


# ── L1: WorkLedger ────────────────────────────────────────────────────────────

class WorkLedger:
    def __init__(self, task_name: str):
        self.task_name = task_name
        self.entries: list[LedgerEntry] = []
        self.started = time.time()
        self._lock = threading.Lock()

    def _add(self, kind: str, content: str, detail: str = "", passed: Optional[bool] = None):
        with self._lock:
            self.entries.append(LedgerEntry(kind, content, detail, passed))

    def plan(self, description: str):
        self._add("plan", description)

    def exec(self, target: str, what: str):
        self._add("exec", target, what)

    def verify(self, command: str, passed: bool, detail: str = ""):
        self._add("verify", command, detail, passed)

    def fix(self, problem: str, solution: str):
        self._add("fix", problem, solution)

    def note(self, text: str):
        self._add("note", text)

    def elapsed(self) -> float:
        return time.time() - self.started


# ── L2: ReflectEngine ────────────────────────────────────────────────────────

# Muster die auf Qualitätsmängel hinweisen
_SMELL_PATTERNS = [
    (r"\bTODO\b|\bFIXME\b|\bHACK\b|\bXXX\b",         "clarity",      "warn",  "Unfertige Markierung im Content"),
    (r"\bunwrap\(\)",                                    "logic",        "warn",  "unwrap() ohne Fehlerbehandlung"),
    (r"panic!\(",                                        "logic",        "warn",  "panic!() in Produktionspfad"),
    (r"\.clone\(\).*\.clone\(\).*\.clone\(\)",           "efficiency",   "warn",  "Dreifaches .clone() — Referenzen prüfen"),
    (r"password|secret|token|key",                       "security",     "warn",  "Sensibles Schlüsselwort im Code-Content"),
    (r"hardcod",                                         "security",     "error", "Hardcodierter Wert erkannt"),
    (r"sleep\(\d+\)",                                    "efficiency",   "warn",  "Busy-Wait sleep() — Event-driven Alternative?"),
    (r"for.*for.*for",                                   "efficiency",   "warn",  "Verschachtelte Tripel-Schleife — O(n³)?"),
    (r"\bexpect\(\"",                                    "clarity",      "warn",  "expect() ohne Kontextbotschaft"),
    (r"unsafe\s*\{",                                     "security",     "error", "unsafe Block — explizites Audit erforderlich"),
]

_LOGIC_CHECKS = [
    ("plan_before_exec",   lambda e: _has_plan_before_exec(e),     "logic",        "error", "exec-Eintrag ohne vorherigen plan"),
    ("verify_after_exec",  lambda e: _verify_follows_exec(e),      "completeness", "warn",  "exec ohne nachfolgendes verify"),
    ("fix_has_base",       lambda e: _fix_has_problem(e),          "consistency",  "warn",  "fix-Eintrag ohne Problembeschreibung"),
    ("all_verifies_pass",  lambda e: _all_verifies_pass(e),        "logic",        "error", "Mindestens ein verify fehlgeschlagen"),
]


def _has_plan_before_exec(entries: list[LedgerEntry]) -> bool:
    seen_plan = False
    for e in entries:
        if e.kind == "plan":
            seen_plan = True
        if e.kind == "exec" and not seen_plan:
            return False
    return True


def _verify_follows_exec(entries: list[LedgerEntry]) -> bool:
    for i, e in enumerate(entries):
        if e.kind == "exec":
            rest = entries[i + 1:]
            if not any(r.kind == "verify" for r in rest):
                return False
    return True


def _fix_has_problem(entries: list[LedgerEntry]) -> bool:
    for e in entries:
        if e.kind == "fix" and not e.content.strip():
            return False
    return True


def _all_verifies_pass(entries: list[LedgerEntry]) -> bool:
    return all(e.passed is not False for e in entries if e.kind == "verify")


class ReflectEngine:
    def __init__(self, ledger: WorkLedger):
        self.ledger = ledger
        self.signals: list[QualitySignal] = []

    def analyze(self) -> list[QualitySignal]:
        self.signals = []
        self._pattern_scan()
        self._logic_scan()
        self._coverage_check()
        return self.signals

    def _pattern_scan(self):
        all_text = " ".join(
            f"{e.content} {e.detail}" for e in self.ledger.entries
        )
        for pattern, dim, severity, msg in _SMELL_PATTERNS:
            if re.search(pattern, all_text, re.IGNORECASE):
                self.signals.append(QualitySignal(dim, severity, msg,
                    fix=f"Prüfe alle {dim}-relevanten Einträge auf dieses Muster"))

    def _logic_scan(self):
        entries = self.ledger.entries
        for name, check_fn, dim, severity, msg in _LOGIC_CHECKS:
            if not check_fn(entries):
                self.signals.append(QualitySignal(dim, severity, msg,
                    fix=f"Ergänze fehlende {name.replace('_', ' ')}-Einträge"))

    def _coverage_check(self):
        kinds = {e.kind for e in self.ledger.entries}
        if "plan" not in kinds:
            self.signals.append(QualitySignal("completeness", "warn",
                "Kein plan-Eintrag — Task-Ziel undokumentiert",
                fix="t.plan(...) am Anfang des Tasks aufrufen"))
        if "verify" not in kinds:
            self.signals.append(QualitySignal("completeness", "error",
                "Kein verify-Eintrag — Keine Qualitätsprüfung belegt",
                fix="t.verify(cmd, passed=True/False) nach jeder Änderung"))

    def score(self) -> int:
        deductions = {"ok": 0, "warn": 5, "error": 20}
        s = 100 - sum(deductions[sig.severity] for sig in self.signals)
        return max(0, s)

    def grade(self) -> tuple[str, str]:
        s = self.score()
        if s >= 90: return "A", "GN"
        if s >= 75: return "B", "CY"
        if s >= 60: return "C", "AM"
        return "D", "RD"


# ── L3: SnapshotPrinter ───────────────────────────────────────────────────────

KIND_ICON = {
    "plan":   ("▸", "BL"),
    "exec":   ("◈", "CY"),
    "verify": ("✓", "GN"),
    "fix":    ("⚡", "AM"),
    "note":   ("·", "GY"),
}

SEV_COLOR = {"ok": "GN", "warn": "AM", "error": "RD"}
SEV_ICON  = {"ok": "✓", "warn": "△", "error": "✗"}


class SnapshotPrinter:
    def __init__(self, ledger: WorkLedger, signals: list[QualitySignal], score: int, grade: tuple[str, str]):
        self.ledger  = ledger
        self.signals = signals
        self.score   = score
        self.grade, self.grade_color = grade

    def render(self) -> str:
        lines = []
        lines.append("")
        lines.append(_head(f"HUGIN REFLECT  ·  {self.ledger.task_name}", "VT"))

        # ── Meta ──
        elapsed = self.ledger.elapsed()
        ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        fingerprint = hashlib.sha1(
            "".join(e.content for e in self.ledger.entries).encode()
        ).hexdigest()[:8]
        lines.append(f"  {C['GY']}Zeit: {ts}  |  Dauer: {elapsed:.1f}s  |  FP: {fingerprint}{C['R']}")
        lines.append(_bar("─"))

        # ── Ledger-Transkript ──
        lines.append(f"  {C['B']}{C['WH']}TRANSKRIPT{C['R']}  {C['GY']}({len(self.ledger.entries)} Einträge){C['R']}")
        for i, e in enumerate(self.ledger.entries):
            icon, ic = KIND_ICON.get(e.kind, ("?", "GY"))
            rel = e.ts - self.ledger.started
            prefix = f"  {C['GY']}{i+1:02d}  +{rel:5.1f}s  {C[ic]}{icon}{C['R']}  "
            content = C["WH"] + e.content + C["R"]
            if e.detail:
                content += f"  {C['GY']}→ {e.detail}{C['R']}"
            if e.passed is not None:
                mark = f"{C['GN']}[PASS]{C['R']}" if e.passed else f"{C['RD']}[FAIL]{C['R']}"
                content += f"  {mark}"
            lines.append(prefix + content)
        lines.append(_bar("─"))

        # ── Qualitätssignale ──
        lines.append(f"  {C['B']}{C['WH']}QUALITÄTS-ANALYSE{C['R']}")
        if not self.signals:
            lines.append(f"  {C['GN']}✓  Keine Mängel erkannt — alle 6 Dimensionen grün{C['R']}")
        else:
            for sig in self.signals:
                sc = SEV_COLOR[sig.severity]
                si = SEV_ICON[sig.severity]
                lines.append(f"  {C[sc]}{si}  [{sig.dim.upper():<14}] {sig.message}{C['R']}")
                if sig.fix:
                    lines.append(f"  {C['GY']}    ↳ Fix: {sig.fix}{C['R']}")
        lines.append(_bar("─"))

        # ── Score-Gauge ──
        filled = self.score // 2
        bar_gn = int(filled * 0.7)
        bar_am = int(filled * 0.2)
        bar_rd = filled - bar_gn - bar_am
        gauge = (C["GN"] + "█" * bar_gn +
                 C["AM"] + "█" * bar_am +
                 C["RD"] + "█" * bar_rd +
                 C["GY"] + "░" * (50 - filled) + C["R"])
        grade_str = f"{C[self.grade_color]}{C['B']}{self.grade}{C['R']}"
        lines.append(f"  QUALITÄTS-SCORE  {gauge}  {self.score:3d}/100  Note: {grade_str}")
        lines.append(_foot("VT"))
        lines.append("")
        return "\n".join(lines)

    def print(self):
        print(self.render())


# ── Kontext-Manager API ───────────────────────────────────────────────────────

class Task:
    """
    Haupt-API für den Reflexions-Logger.
    Alle Methoden können thread-safe aus async-Kontexten aufgerufen werden.
    """

    def __init__(self, name: str, auto_print: bool = True):
        self.ledger = WorkLedger(name)
        self.auto_print = auto_print
        self._engine: Optional[ReflectEngine] = None
        self._snapshot: Optional[SnapshotPrinter] = None

    # Delegation an Ledger
    def plan(self, description: str):   self.ledger.plan(description)
    def exec(self, target: str, what: str): self.ledger.exec(target, what)
    def verify(self, cmd: str, passed: bool, detail: str = ""):
        self.ledger.verify(cmd, passed, detail)
    def fix(self, problem: str, solution: str): self.ledger.fix(problem, solution)
    def note(self, text: str): self.ledger.note(text)

    def reflect(self) -> SnapshotPrinter:
        self._engine = ReflectEngine(self.ledger)
        sigs = self._engine.analyze()
        score = self._engine.score()
        grade = self._engine.grade()
        self._snapshot = SnapshotPrinter(self.ledger, sigs, score, grade)
        return self._snapshot

    def __enter__(self):
        return self

    def __exit__(self, *_):
        snap = self.reflect()
        if self.auto_print:
            snap.print()

    @property
    def quality_score(self) -> int:
        return self._engine.score() if self._engine else -1

    @property
    def has_errors(self) -> bool:
        if not self._engine:
            return False
        return any(s.severity == "error" for s in self._engine.signals)


@contextmanager
def task(name: str, auto_print: bool = True):
    """Shorthand Kontext-Manager."""
    t = Task(name, auto_print=auto_print)
    try:
        yield t
    finally:
        snap = t.reflect()
        if auto_print:
            snap.print()


# ── Async-Logger (Hintergrund-Thread) ─────────────────────────────────────────

class AsyncReflectLogger:
    """
    Koppelt sich an einen laufenden Task und schreibt Snapshots
    in ein Log-File, ohne den Haupt-Thread zu blockieren.
    """

    def __init__(self, log_path: str = "logs/hugin_reflect.jsonl"):
        self.log_path = log_path
        self._queue: list[dict] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._running = True
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._thread.start()

    def record(self, t: Task):
        snap = t.reflect()
        entry = {
            "ts": time.time(),
            "task": t.ledger.task_name,
            "score": t.quality_score,
            "has_errors": t.has_errors,
            "entries": len(t.ledger.entries),
            "signals": [
                {"dim": s.dim, "severity": s.severity, "message": s.message}
                for s in (t._engine.signals if t._engine else [])
            ],
        }
        with self._lock:
            self._queue.append(entry)
        snap.print()

    def _flush_loop(self):
        while self._running:
            time.sleep(0.5)
            with self._lock:
                batch = self._queue[:]
                self._queue.clear()
            if batch:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    for entry in batch:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def stop(self):
        self._running = False
        self._thread.join(timeout=2)


# Singleton-Logger (wird beim Import initialisiert, falls LOG-Verzeichnis vorhanden)
_GLOBAL_LOGGER: Optional[AsyncReflectLogger] = None


def get_logger() -> AsyncReflectLogger:
    global _GLOBAL_LOGGER
    if _GLOBAL_LOGGER is None:
        _GLOBAL_LOGGER = AsyncReflectLogger()
    return _GLOBAL_LOGGER


# ── Demo / Standalone ─────────────────────────────────────────────────────────

def _run_demo():
    print(f"\n{C['VT']}{C['B']}HUGIN REFLECT — Demo-Modus{C['R']}\n")
    print("Simuliere einen typischen Patch-Task mit absichtlichen Mängeln...\n")
    time.sleep(0.3)

    with task("Demo: NSW-Graph Patch") as t:
        t.plan("Dreifach-Hash-Ensemble in hm-vector einbauen")
        time.sleep(0.1)
        t.exec("crates/hm-vector/src/lib.rs", "Neu: VectorIndex mit NSW-Graph + 512-dim Embedding")
        time.sleep(0.05)
        t.exec("crates/hm-vector/src/lib.rs", "FNV-1a + DJB2 + SDBM dreifach Projektion — TODO: Bigram-Gewicht prüfen")
        time.sleep(0.05)
        t.fix("E0502 borrow checker — sort_by borgte self.nodes simultan",
              "Scores in Vec<(usize,f32)> vorausberechnen, dann sort+assign")
        t.verify("cargo test --workspace", passed=True, detail="7/7 Tests grün")
        t.note("unwrap() in beam_search entry-check noch vorhanden — bekannt, unkritisch")

    print(f"\n{C['GY']}Zweiter Task ohne verify (soll Warnung erzeugen)...{C['R']}\n")
    time.sleep(0.4)

    with task("Demo: Unvollständige Änderung") as t:
        t.plan("Storage-Backend konfigurieren")
        t.exec("config/plugins.json", "Neuen ops-tool Eintrag hardcoded eingetragen")
        # kein verify → soll completeness:error + security:error produzieren

    print(f"\n{C['GN']}{C['B']}Demo abgeschlossen.{C['R']}\n")


def _run_audit():
    """Liest logs/hugin_reflect.jsonl und druckt eine Zusammenfassung."""
    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "logs", "hugin_reflect.jsonl")
    if not os.path.exists(log_path):
        print(f"{C['AM']}Keine Log-Datei gefunden: {log_path}{C['R']}")
        return
    entries = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if not entries:
        print(f"{C['GY']}Log-Datei leer.{C['R']}")
        return
    print(_head("HUGIN REFLECT — Audit-Log", "BL"))
    total = len(entries)
    avg_score = sum(e["score"] for e in entries) / total
    errors = sum(1 for e in entries if e["has_errors"])
    print(f"  Tasks gesamt: {C['WH']}{total}{C['R']}  |  "
          f"Ø Score: {C['GN']}{avg_score:.0f}/100{C['R']}  |  "
          f"Mit Errors: {C['RD']}{errors}{C['R']}")
    print(_bar("─"))
    for e in entries[-10:]:
        sc = e["score"]
        sc_c = "GN" if sc >= 90 else "AM" if sc >= 60 else "RD"
        ts = time.strftime("%m-%d %H:%M", time.gmtime(e["ts"]))
        err_mark = f" {C['RD']}[ERR]{C['R']}" if e["has_errors"] else ""
        print(f"  {C['GY']}{ts}{C['R']}  {C[sc_c]}{sc:3d}{C['R']}  {e['task']}{err_mark}")
    print(_foot("BL"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HUGIN Reflect — Selbst-Reflexions-Logger")
    parser.add_argument("--demo",  action="store_true", help="Demonstration mit zwei Beispiel-Tasks")
    parser.add_argument("--audit", action="store_true", help="Audit-Log der letzten 10 Tasks ausgeben")
    args = parser.parse_args()

    if args.audit:
        _run_audit()
    elif args.demo:
        _run_demo()
    else:
        parser.print_help()
