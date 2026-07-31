#!/usr/bin/env python3
"""hugin_relay.py -- arbeitsfähig bleiben, wenn das Anthropic-Limit greift.

Das Limit ist keine Störung, sondern ein planbarer Betriebszustand. Diese
Datei behandelt ihn als solchen: sie erkennt ihn, hält die offene Arbeit fest
und führt aus, was ohne Claude ausführbar ist.

Nichts hier umgeht ein Limit, verschleiert Herkunft oder streckt Kontingente
über Konten. Der Ansatz ist das Gegenteil: das Limit wird **sauber gelesen**
und die Arbeit auf Stufen verlagert, die es gar nicht berührt.

## Die drei Stufen

    T0  Kein Modell noetig.       Immer verfuegbar, 0 EUR.
        Supervisor, Tests, Ledger-Pflege, Uebergabe, Strukturpruefung,
        Grenzwache, Keyring-Audit. Das ist mehr, als es zunaechst wirkt:
        der groesste Teil der Qualitaetssicherung braucht kein Sprachmodell.

    T1  Keylose Provider.         0 EUR, ueber agents/ + Oracle-Gate.
        Die 10 als FREE eingestuften Provider aus agents/budget.py.
        Fuer Textarbeit, Erklaerungen, Konsensmessung.

    T2  Claude.                   Kontingentiert.
        Alles, was Orchestrierung, Architektur oder Urteil verlangt.

Beim Limit faellt nur T2 aus. T0 und T1 laufen weiter — und das Repo hat in
T0 genug Substanz, dass eine Sitzung dort nicht leerlaeuft.

## Der Subroom

Was T2 gebraucht haette, verschwindet nicht, sondern geht in
`.claude/relay/queue.jsonl`. Jeder Eintrag traegt, was ihn ausloeste und
welche Stufe er braucht. Kehrt T2 zurueck, wird die Queue der Einstieg —
nicht das Gedaechtnis einer Person.

    python3 scripts/hugin_relay.py status        # welche Stufe traegt gerade
    python3 scripts/hugin_relay.py park "..."    # Arbeit in den Subroom
    python3 scripts/hugin_relay.py drain         # T0 ausfuehren, Rest bleibt
    python3 scripts/hugin_relay.py queue         # was wartet
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOM = REPO / ".claude" / "relay"
QUEUE = ROOM / "queue.jsonl"

T0, T1, T2 = "T0", "T1", "T2"
TIERS = (T0, T1, T2)

# Muster, an denen eine Limit-Meldung erkannt wird. Bewusst als Liste von
# Mustern statt eines Schalters: die Formulierungen aendern sich, und ein
# Parser der nur eine kennt, meldet spaeter faelschlich "alles in Ordnung".
LIMIT_PATTERNS = (
    re.compile(r"usage limit", re.IGNORECASE),
    re.compile(r"rate.?limit", re.IGNORECASE),
    re.compile(r"quota (exceeded|reached)", re.IGNORECASE),
    re.compile(r"limit (reached|erreicht)", re.IGNORECASE),
    re.compile(r"\b429\b"),
    re.compile(r"overloaded", re.IGNORECASE),
)


def parse_limit(text: str) -> tuple[bool, str]:
    """(ist_limit, erkanntes_muster).

    Delegiert an agents/limits.py -- dort steht die Bewertung (Art, Wartezeit,
    empfohlene Reaktion). Diese Huelle bleibt, weil der Relay nur die
    Ja/Nein-Antwort braucht; wer die Bewertung will, ruft limits.parse direkt.
    Zwei eigene Musterlisten waeren die sichere Drift.
    """
    sig = limit_signal(text)
    return (True, sig.matched) if sig else (False, "")


def limit_signal(text: str):
    """Vollstaendiges Signal mit Art und Wartezeit, oder None."""
    sys.path.insert(0, str(REPO))
    try:
        from agents import limits
        return limits.parse(text or "")
    except Exception as exc:
        log.warning("swallowed in hugin_relay: %s", exc)
        # Faellt agents/ aus, bleibt die alte Musterliste als Notnagel --
        # lieber grob erkennen als gar nicht.
        for p in LIMIT_PATTERNS:
            m = p.search(text or "")
            if m:
                return type("Sig", (), {"matched": m.group(0), "kind": "unknown",
                                        "wait_s": 30, "action": "vorsichtig behandeln",
                                        "__str__": lambda s: f"[UNKNOWN] {m.group(0)}"})()
        return None


# ---------------------------------------------------------------------------
# T0 -- was ohne jedes Modell laeuft
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Task:
    name: str
    cmd: tuple[str, ...]
    zweck: str


T0_TASKS: tuple[Task, ...] = (
    Task("supervisor", ("python3", "scripts/munin_supervisor.py", "--quick"),
         "Verfassungs-Audit"),
    Task("tests", ("python3", "-m", "pytest", "tests/", "-q"), "Testsuite"),
    Task("struktur", ("python3", "scripts/validate_repo.py"), "Strukturpruefung"),
    Task("uebergabe", ("python3", "scripts/munin_session.py", "brief", "--write"),
         "Uebergabe neu messen"),
    Task("grenzwache", ("python3", "scripts/munin_session.py", "guard"),
         "Ableitbares im Ledger finden"),
    Task("anker", ("python3", "scripts/munin_continuity.py", "verify"),
         "Ledger-Anker nachrechnen"),
    Task("keyring", ("python3", "scripts/hugin_keyring.py", "audit"),
         "Schluessel-Leckpruefung"),
)


def available_t0() -> tuple[Task, ...]:
    """Nur Aufgaben, deren Skript wirklich existiert -- nicht geraten."""
    return tuple(t for t in T0_TASKS
                 if not t.cmd[1].startswith("scripts/") or (REPO / t.cmd[1]).is_file())


def free_providers() -> tuple[str, ...]:
    """T1-Kapazitaet aus agents/budget.py, nicht aus einer zweiten Liste hier.
    Zwei Listen derselben Sache driften auseinander."""
    sys.path.insert(0, str(REPO))
    try:
        from agents import budget
        return budget.free_providers()
    except Exception as exc:
        log.warning("swallowed in hugin_relay: %s", exc)
        return ()


# ---------------------------------------------------------------------------
# Subroom
# ---------------------------------------------------------------------------

@dataclass
class Parked:
    text: str
    tier: str
    reason: str = ""
    ts: str = field(default_factory=lambda:
                    datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def to_json(self) -> str:
        return json.dumps({"ts": self.ts, "tier": self.tier,
                           "reason": self.reason, "text": self.text},
                          ensure_ascii=False, sort_keys=True)


def park(text: str, tier: str = T2, reason: str = "") -> Parked:
    if tier not in TIERS:
        raise ValueError(f"Stufe {tier!r} unbekannt; erlaubt: {TIERS}")
    if not text.strip():
        raise ValueError("Leerer Eintrag -- ein Subroom voller Leerzeilen ist Rauschen")
    p = Parked(text=text.strip(), tier=tier, reason=reason.strip())
    ROOM.mkdir(parents=True, exist_ok=True)
    with QUEUE.open("a", encoding="utf-8") as fh:
        fh.write(p.to_json() + "\n")
    return p


def queue() -> list[dict]:
    if not QUEUE.is_file():
        return []
    out = []
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # eine kaputte Zeile kippt den Subroom nicht
    return out


# ---------------------------------------------------------------------------
# Ausfuehrung
# ---------------------------------------------------------------------------

def drain(dry_run: bool = False) -> list[tuple[str, int, str]]:
    """T0 abarbeiten. Gibt (name, exit, kurzfassung) je Aufgabe."""
    results = []
    for t in available_t0():
        if dry_run:
            results.append((t.name, 0, "dry-run"))
            continue
        r = subprocess.run(t.cmd, cwd=REPO, capture_output=True, text=True)
        tail = (r.stdout or r.stderr).strip().splitlines()
        results.append((t.name, r.returncode, tail[-1][:90] if tail else ""))
    return results


def status_lines() -> list[str]:
    t0 = available_t0()
    t1 = free_providers()
    q = queue()
    waiting = {}
    for e in q:
        waiting[e.get("tier", "?")] = waiting.get(e.get("tier", "?"), 0) + 1
    out = [
        "Relay-Stufen",
        f"  T0  {len(t0)} Aufgaben ohne Modell        — immer verfuegbar, 0 EUR",
        f"  T1  {len(t1)} keylose Provider            — 0 EUR",
        "  T2  Claude                          — kontingentiert",
        "",
        f"Subroom: {len(q)} Eintrag/Eintraege" + (
            "  (" + ", ".join(f"{k}={v}" for k, v in sorted(waiting.items())) + ")"
            if waiting else ""),
    ]
    if not t1:
        out.append("  Hinweis: T1-Liste leer — agents/budget.py nicht ladbar.")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="welche Stufe traegt gerade").set_defaults(cmd="status")

    pk = sub.add_parser("park", help="Arbeit in den Subroom legen")
    pk.add_argument("text")
    pk.add_argument("--tier", default=T2, choices=TIERS)
    pk.add_argument("--reason", default="")

    dr = sub.add_parser("drain", help="T0 ausfuehren")
    dr.add_argument("--dry-run", action="store_true")

    sub.add_parser("queue", help="was wartet")

    ck = sub.add_parser("check", help="Text auf eine Limit-Meldung pruefen")
    ck.add_argument("text")

    a = p.parse_args(argv)

    if a.cmd == "status":
        print("\n".join(status_lines()))
        return 0
    if a.cmd == "park":
        e = park(a.text, a.tier, a.reason)
        print(f"geparkt [{e.tier}] {e.text[:70]}")
        return 0
    if a.cmd == "queue":
        q = queue()
        if not q:
            print("Subroom leer.")
            return 0
        for e in q:
            print(f"{e.get('ts','')}  [{e.get('tier','?')}]  {e.get('text','')[:90]}")
        return 0
    if a.cmd == "check":
        hit, pat = parse_limit(a.text)
        print(f"Limit erkannt: {pat!r}" if hit else "Keine Limit-Meldung erkannt.")
        return 0 if hit else 1

    worst = 0
    for name, code, tail in drain(a.dry_run):
        mark = "OK  " if code == 0 else f"EXIT{code}"
        print(f"[{mark}] {name:<12} {tail}")
        worst = max(worst, min(code, 1))
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
