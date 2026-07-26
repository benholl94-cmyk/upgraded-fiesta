#!/usr/bin/env python3
"""munin_handoff.py — Übergabe an die nächste Sitzung.

Das Problem: eine neue Sitzung startet ohne Gedächtnis und muss sich das Repo
neu erarbeiten. Bei 700+ Dateien und 20 Crates kostet das den halben
Kontext, bevor die erste Zeile Arbeit passiert.

`munin-state.json` sollte das lösen, ist aber gitignoriert — eine frische
Sitzung in einem neuen Container sieht sie nie. Diese Datei schreibt
stattdessen `.claude/persona/HANDOFF.md`, **getrackt**, und damit im Clone
vorhanden.

Kernregel, dieselbe wie beim Supervisor: **gemessen, nicht erinnert.** Jede
Zeile hier entsteht aus `git`, aus dem Dateisystem oder aus dem Supervisor —
nie aus einer Behauptung einer vorigen Sitzung. Eine Übergabe, die
Behauptungen weiterreicht, verstärkt Drift statt sie zu bremsen.

    python3 scripts/munin_handoff.py            # nach stdout
    python3 scripts/munin_handoff.py --write    # nach .claude/persona/HANDOFF.md
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / ".claude" / "persona" / "HANDOFF.md"
MAX_COMMITS = 12


def run(*args: str) -> str:
    r = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def supervisor_findings() -> list[dict]:
    r = subprocess.run(
        ["python3", "scripts/munin_supervisor.py", "--quick", "--json"],
        cwd=REPO, capture_output=True, text=True,
    )
    try:
        return json.loads(r.stdout).get("findings", [])
    except (json.JSONDecodeError, AttributeError):
        return []


def measured_counts() -> dict:
    py = len(run("git", "ls-files", "*.py").splitlines())
    rs = len(run("git", "ls-files", "*.rs").splitlines())
    tests = len(run("git", "ls-files", "tests/test_*.py").splitlines())
    crates = len(run("git", "ls-files", "crates/*/Cargo.toml",
                     "crates/*/*/Cargo.toml").splitlines())
    return {"python": py, "rust": rs, "test_files": tests, "crates": crates,
            "tracked": len(run("git", "ls-files").splitlines())}


def entry_points() -> list[tuple[str, str]]:
    """Die Handvoll Befehle, mit denen man das Repo bedient. Bewusst kurz:
    eine Uebergabe, die alles auflistet, wird nicht gelesen."""
    candidates = [
        ("python3 scripts/munin_supervisor.py --quick", "Verfassungs-Audit"),
        ("python3 -m pytest tests/ -q", "Python-Tests"),
        ("cargo test --workspace", "Rust-Tests"),
        ("python3 -m agents status", "Agenten + Kostenbremse"),
        ("python3 scripts/hugin_keyring.py status", "Eigene Dienstschluessel"),
        ("python3 scripts/validate_repo.py", "Strukturpruefung"),
        ("cp hugin/hugin.html hugin/index.html", "Nach jeder PWA-Aenderung"),
    ]
    return [(c, d) for c, d in candidates
            if not c.startswith("python3 scripts/")
            or (REPO / c.split()[1]).is_file()]


def build() -> str:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    branch = run("git", "branch", "--show-current") or "(detached)"
    head = run("git", "log", "-1", "--format=%h %s")
    unpushed = run("git", "rev-list", "origin/HEAD..HEAD", "--count") or "0"
    dirty = "ja" if run("git", "status", "--porcelain") else "nein"
    counts = measured_counts()
    findings = supervisor_findings()

    lines = [
        "# Übergabe an die nächste Sitzung",
        "",
        f"Erzeugt {ts} von `scripts/munin_handoff.py`. **Alles hier ist gemessen,",
        "nichts erinnert** — neu erzeugen statt von Hand pflegen:",
        "",
        "```sh",
        "python3 scripts/munin_handoff.py --write",
        "```",
        "",
        "## Zustand",
        "",
        f"| | |",
        f"|---|---|",
        f"| Branch | `{branch}` |",
        f"| HEAD | `{head}` |",
        f"| Ungepusht | {unpushed} |",
        f"| Arbeitsbaum schmutzig | {dirty} |",
        f"| Getrackte Dateien | {counts['tracked']} |",
        f"| Crates / Python / Rust / Testdateien | "
        f"{counts['crates']} / {counts['python']} / {counts['rust']} / {counts['test_files']} |",
        "",
        "## Offene Befunde",
        "",
    ]

    if findings:
        lines.append("| Schwere | Regel | Befund |")
        lines.append("|---|---|---|")
        for f in findings:
            detail = str(f.get("detail", "")).replace("|", "\\|")[:110]
            lines.append(f"| {f.get('severity')} | `{f.get('rule')}` | {detail} |")
        lines += ["", "Vollständig mit Begründung:",
                  "`python3 scripts/munin_supervisor.py --quick`"]
    else:
        lines.append("Keine — der Supervisor meldet einen sauberen Zustand.")

    lines += ["", "## Einstiegspunkte", "", "| Befehl | Wofür |", "|---|---|"]
    lines += [f"| `{c}` | {d} |" for c, d in entry_points()]

    lines += ["", "## Letzte Commits", "", "```"]
    lines += run("git", "log", f"-{MAX_COMMITS}", "--format=%h %s").splitlines()
    lines += ["```", ""]

    lines += [
        "## Was diese Datei nicht ist",
        "",
        "Kein Ersatz für `CLAUDE.md` — dort steht, *wie* das Repo funktioniert.",
        "Hier steht nur, *wo es gerade steht*. Bei Widerspruch gewinnt die",
        "Messung: `CLAUDE.md` kann veralten, diese Datei wird neu erzeugt.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--write", action="store_true",
                   help=f"nach {OUT.relative_to(REPO)} schreiben")
    a = p.parse_args(argv)
    text = build()
    if a.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text + "\n", encoding="utf-8")
        print(f"geschrieben: {OUT.relative_to(REPO)} ({len(text)} Zeichen)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
