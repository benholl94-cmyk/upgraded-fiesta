#!/usr/bin/env python3
"""munin_session.py -- die eine Übergabe. Ersetzt zwei Vorgänger.

## Warum es zwei gab

`munin_handoff.py` maß den Ist-Zustand (Branch, HEAD, Supervisor-Befunde) und
schrieb `.claude/persona/HANDOFF.md`. `munin_continuity.py` führt ein Ledger
aus Entscheidungen, Sackgassen und offenen Punkten und schreibt `HANDOFF.md`.
Zwei Dateien, die beide beanspruchten, *die* Übergabe zu sein.

Beide hatten recht -- für ihre Hälfte. Der Fehler war, dass keine der beiden
sagte, **wo ihre Hälfte endet.** Genau deshalb kam die Frage bei jeder neuen
Sitzung wieder hoch.

## Die Grenze, und warum sie entscheidbar ist

    Ableitbar aus git, Dateisystem oder Supervisor
        -> wird bei jeder Ausgabe NEU GEMESSEN, nie gespeichert.
           Speichern wäre Redundanz, und Redundanz verrottet zu Drift.

    Nicht ableitbar (Entscheidung, Sackgasse, offener Punkt, Invariante)
        -> gehört ins Ledger und MUSS einen Anker tragen,
           damit `verify` nachrechnen kann statt zu glauben.

Das ist keine Geschmacksfrage. Für jeden Fakt lässt sich beantworten, ob ein
Skript ihn aus dem Repo rekonstruieren kann. Fällt die Antwort "ja" aus und
er steht trotzdem im Ledger, ist das ein Fehler -- und `guard()` unten findet
ihn, statt darauf zu hoffen, dass jemand die Regel im Kopf behält.

Eine Konvention, an die man sich erinnern muss, ist genau die Sorte Regel, die
diese Datei abschaffen soll.

    python3 scripts/munin_session.py brief            # nach stdout
    python3 scripts/munin_session.py brief --write    # nach HANDOFF.md
    python3 scripts/munin_session.py guard            # Grenzverletzungen finden

Ledgerpflege (Erfassen, Auflösen, Verdichten, Versiegeln) bleibt bei
`munin_continuity.py` -- diese Datei baut darauf auf und ersetzt sie nicht.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "HANDOFF.md"
CONTINUITY = REPO / "scripts" / "munin_continuity.py"

# Vorgänger, die diese Datei ablöst. `guard` meldet sie, solange sie noch da
# sind -- eine dritte Fassung neben zwei alten wäre die Verschlimmerung des
# Problems, nicht die Lösung.
SUPERSEDED = (
    REPO / "scripts" / "munin_handoff.py",
    REPO / ".claude" / "persona" / "HANDOFF.md",
)


def _load_continuity():
    if not CONTINUITY.is_file():
        return None
    spec = importlib.util.spec_from_file_location("munin_continuity", CONTINUITY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("munin_continuity", mod)
    spec.loader.exec_module(mod)
    return mod


def run(*args: str) -> str:
    r = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


# ---------------------------------------------------------------------------
# Die gemessene Hälfte -- nichts hiervon wird je gespeichert
# ---------------------------------------------------------------------------

def measured() -> dict:
    findings = []
    r = subprocess.run(["python3", "scripts/munin_supervisor.py", "--quick", "--json"],
                       cwd=REPO, capture_output=True, text=True)
    try:
        findings = json.loads(r.stdout).get("findings", [])
    except (json.JSONDecodeError, AttributeError):
        pass
    return {
        "branch": run("git", "branch", "--show-current") or "(detached)",
        "head": run("git", "log", "-1", "--format=%h %s"),
        "unpushed": run("git", "rev-list", "origin/HEAD..HEAD", "--count") or "0",
        "dirty": bool(run("git", "status", "--porcelain")),
        "tracked": len(run("git", "ls-files").splitlines()),
        "findings": findings,
        "recent": run("git", "log", "-8", "--format=%h %s").splitlines(),
    }


# ---------------------------------------------------------------------------
# Die Grenzwache
# ---------------------------------------------------------------------------

# Muster, die belegen, dass ein Ledgereintrag etwas Ableitbares behauptet.
# Bewusst eng: ein zu breiter Wächter meldet echte Entscheidungen als Verstoss
# und wird dann abgeschaltet, womit er nichts mehr bewacht.
_DERIVABLE = (
    (re.compile(r"\b[0-9a-f]{7,40}\b"),
     "nackter Commit-Hash im Text -- gehoert als anchor 'sha:...', nicht in die Prosa"),
    (re.compile(r"\b\d+\s+(passed|Tests? gr[üu]n|tests? pass)", re.IGNORECASE),
     "Testzahl -- wird gemessen, nicht erinnert"),
    (re.compile(r"\b(HEAD steht auf|Branch ist|aktueller Branch)\b", re.IGNORECASE),
     "Repo-Zustand -- wird gemessen, nicht erinnert"),
    (re.compile(r"\b\d+\s+(getrackte|Dateien im Index)\b", re.IGNORECASE),
     "Dateizahl -- wird gemessen, nicht erinnert"),
)


@dataclass(frozen=True)
class Violation:
    where: str
    detail: str

    def __str__(self) -> str:
        return f"{self.where}: {self.detail}"


def guard() -> list[Violation]:
    """Findet Grenzverletzungen: Ableitbares im Ledger, oder Vorgänger, die
    noch existieren."""
    out: list[Violation] = []

    for p in SUPERSEDED:
        if p.exists():
            out.append(Violation(
                str(p.relative_to(REPO)),
                "Vorgaenger existiert noch -- zwei Uebergaben nebeneinander sind "
                "schlimmer als eine falsche"))

    cont = _load_continuity()
    if cont is None:
        return out
    try:
        led = cont.Ledger.load()
    except Exception as exc:                     # kaputtes Ledger kippt nicht den Lauf
        out.append(Violation("ledger", f"nicht lesbar: {exc}"))
        return out

    for e in led.entries:
        text = getattr(e, "text", "") or ""
        for pattern, why in _DERIVABLE:
            if pattern.search(text):
                out.append(Violation(f"ledger/{getattr(e, 'id', '?')}", why))
                break
    return out


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def brief() -> str:
    m = measured()
    cont = _load_continuity()
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    L = [
        "# Übergabe",
        "",
        f"Erzeugt {ts} von `scripts/munin_session.py`. **Nicht von Hand pflegen** —",
        "neu erzeugen mit `python3 scripts/munin_session.py brief --write`.",
        "",
        "Zwei Hälften, klar getrennt: was aus dem Repo ableitbar ist, steht unter",
        "*Gemessen* und wird bei jeder Ausgabe neu berechnet. Was nicht ableitbar",
        "ist, steht unter *Getragen* und lebt im Ledger. Ein Fakt gehört nie in",
        "beide — `munin_session.py guard` findet Verstöße.",
        "",
        "## Gemessen",
        "",
        "| | |", "|---|---|",
        f"| Branch | `{m['branch']}` |",
        f"| HEAD | `{m['head']}` |",
        f"| Ungepusht | {m['unpushed']} |",
        f"| Arbeitsbaum schmutzig | {'ja' if m['dirty'] else 'nein'} |",
        f"| Getrackte Dateien | {m['tracked']} |",
        "",
    ]

    if m["findings"]:
        L += ["### Offene Befunde", "", "| Schwere | Regel | Befund |", "|---|---|---|"]
        for f in m["findings"]:
            # Pipe maskieren, sonst zerreisst ein Befund die Markdown-Tabelle.
            detail = str(f.get("detail", ""))[:100].replace("|", "\\|")
            L.append(f"| {f.get('severity')} | `{f.get('rule')}` | {detail} |")
        L += ["", "Begründungen: `python3 scripts/munin_supervisor.py --quick`", ""]
    else:
        L += ["### Offene Befunde", "", "Keine.", ""]

    L += ["## Getragen", ""]
    if cont is None:
        L += ["_Kein Ledger vorhanden (`scripts/munin_continuity.py` fehlt)._", ""]
    else:
        try:
            led = cont.Ledger.load()
            rotten = cont.verify(led)
            by_kind: dict[str, list] = {}
            for e in led.entries:
                by_kind.setdefault(getattr(e, "kind", "notiz"), []).append(e)
            for kind in ("offen", "invariante", "entscheidung", "sackgasse", "notiz"):
                items = by_kind.get(kind, [])
                if not items:
                    continue
                L += [f"### {kind}", ""]
                for e in items:
                    anchors = " ".join(f"`{a}`" for a in getattr(e, "anchors", ()))
                    L.append(f"- {getattr(e, 'text', '')}" + (f"  {anchors}" if anchors else ""))
                L.append("")
            if rotten:
                L += ["### Verrottete Anker", "",
                      "Diese Einträge zeigen auf etwas, das es nicht mehr gibt:", ""]
                L += [f"- `{a}` ({status}) — {detail}" for _e, a, status, detail in rotten]
                L.append("")
        except Exception as exc:
            L += [f"_Ledger nicht lesbar: {exc}_", ""]

    problems = guard()
    L += ["## Grenzwache", ""]
    L += (["Sauber — keine ableitbaren Fakten im Ledger, keine Vorgängerdateien.", ""]
          if not problems else
          [f"- {v}" for v in problems] + [""])

    L += ["## Einstieg", "", "```sh",
          "python3 scripts/munin_session.py brief      # dieser Text, neu gemessen",
          "python3 scripts/munin_continuity.py capture # Entscheidung/Sackgasse erfassen",
          "python3 scripts/munin_continuity.py seal --push  # Sitzung abschliessen",
          "python3 scripts/munin_supervisor.py --quick # Verfassungs-Audit",
          "```", "", "### Letzte Commits", "", "```"] + m["recent"] + ["```", ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brief", help="Übergabe erzeugen")
    b.add_argument("--write", action="store_true", help=f"nach {OUT.name} schreiben")
    g = sub.add_parser("guard", help="Grenzverletzungen finden")
    g.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    if a.cmd == "guard":
        v = guard()
        if a.json:
            print(json.dumps([{"where": x.where, "detail": x.detail} for x in v],
                             ensure_ascii=False, indent=2))
        else:
            print("Grenzwache: sauber." if not v else
                  f"Grenzwache: {len(v)} Verstoss/Verstoesse\n" +
                  "\n".join(f"  {x}" for x in v))
        return 1 if v else 0

    text = brief()
    if a.write:
        OUT.write_text(text + "\n", encoding="utf-8")
        print(f"geschrieben: {OUT.name} ({len(text)} Zeichen)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
