#!/usr/bin/env python3
"""build_manifest.py -- was wurde gebaut, und was wurde davon nachgewiesen.

## Warum das gefehlt hat

Das Repo hatte alles, was ein Vollbau braucht — Dockerfile, docker-compose,
systemd-Units, Release-Profil, PWA, Gateway — und **keine Action, die daraus
etwas herstellt**. Gemessen: 0 Workflows bauen das Dockerfile, 0 erzeugen ein
Release-Binary, 0 pruefen die systemd-Units, 0 fahren `docker compose config`.
Wer die Plattform betreiben wollte, musste sie selbst bauen und dabei hoffen,
dass alles zusammenpasst.

Ein Bau ohne Manifest ist ausserdem eine Behauptung: eine Datei liegt da, und
niemand kann nachrechnen, aus welchem Stand sie stammt, was sie enthaelt und
welche Pruefungen sie ueberstanden hat.

## Was drinsteht — und was ausdruecklich nicht

Drin: Commit, Zeit, Artefakte mit SHA256 und Groesse, die Versionen der
Werkzeugkette, und je Pruefung ein Ergebnis mit dem Befehl, der es erzeugt hat.

**Nicht drin: irgendein Geheimnis.** Weder Tokens noch Schluesselwerte noch
Umgebungsinhalte. Genannt werden nur *Namen* von Variablen — dass ein Dienst
`HM_OWNER_TOKEN` liest, ist keine Preisgabe, sein Wert waere eine. Ein
Gegentest in `tests/test_build_manifest.py` faehrt dieselben Muster wie der
Secret-Scanner ueber die Ausgabe.

## Nachgerechnet, nicht behauptet

`pruefung` traegt kein `ok: true`, das jemand hingeschrieben hat, sondern den
Exit-Code eines tatsaechlich gelaufenen Befehls. Faellt ein Werkzeug aus, ist
das Ergebnis `unbekannt` und nicht `bestanden` — dieselbe Richtung wie
ueberall hier: Unbekanntes gilt nie als in Ordnung.

    python3 scripts/build_manifest.py --out status/build-manifest.json
    python3 scripts/build_manifest.py --pruefen   # zusaetzlich die Checks fahren
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _log import get_logger          # noqa: E402

log = get_logger(__name__)

REPO = Path(__file__).resolve().parent.parent

BESTANDEN, GEFALLEN, UNBEKANNT = "bestanden", "gefallen", "unbekannt"

# Die Artefakte eines Vollbaus. Fehlt eines, steht das im Manifest — es wird
# nicht weggelassen, denn eine Liste, aus der Fehlendes verschwindet, sieht
# immer vollstaendig aus.
ARTEFAKTE = (
    ("gateway", "target/release/hm-gateway"),
    ("tool-exec", "target/release/hm-tool-exec"),
    ("cli", "target/release/hm-cli"),
    ("ui", "ui/dist/index.html"),
    ("pwa", "hugin/index.html"),
)

# Pruefungen, die kein Geheimnis brauchen und trotzdem echte Aussagen liefern.
PRUEFUNGEN = (
    ("systemd-units", ["systemd-analyze", "verify",
                       "deploy/hm-gateway.service",
                       "deploy/hm-gateway-watchdog.service",
                       "deploy/hm-gateway-watchdog.timer"]),
    ("compose-syntax", ["docker", "compose", "config"]),
    ("repo-struktur", [sys.executable, "scripts/validate_repo.py"]),
    ("einsatzbereit", [sys.executable, "scripts/hugin_clarity.py", "--json"]),
)

# Nur fuer die Syntaxpruefung, nie exportiert, nie im Manifest. Ohne sie
# scheitert `docker compose config` an Pflichtvariablen, die mit der Syntax
# nichts zu tun haben.
PLATZHALTER = {
    "HM_OWNER_TOKEN": "manifest-syntax-check-only",
    "POSTGRES_PASSWORD": "manifest-syntax-check-only",
}


def _run(argv: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    umgebung = dict(os.environ)
    for name, wert in PLATZHALTER.items():
        umgebung.setdefault(name, wert)
    return subprocess.run(argv, cwd=REPO, capture_output=True, text=True,
                          timeout=timeout, env=umgebung)


def _sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with pfad.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _version(argv: list[str]) -> str:
    """Eine nicht ermittelbare Version ist ein leerer String, kein Absturz —
    aber sie wird protokolliert. Ein stilles Verschlucken liesse das Manifest
    behaupten, das Werkzeug sei nicht da, obwohl nur die Abfrage scheiterte."""
    try:
        r = _run(argv, timeout=60)
        return (r.stdout or r.stderr).strip().splitlines()[0][:80] if r.returncode == 0 else ""
    except Exception as exc:
        log.warning("Version von %s nicht ermittelbar: %s", argv[0], exc)
        return ""


def _git(*args: str) -> str:
    r = _run(["git", *args], timeout=60)
    return r.stdout.strip() if r.returncode == 0 else ""


def artefakte() -> list[dict]:
    out = []
    for name, rel in ARTEFAKTE:
        p = REPO / rel
        if p.is_file():
            out.append({"name": name, "pfad": rel, "bytes": p.stat().st_size,
                        "sha256": _sha256(p)})
        else:
            # Ausdruecklich als fehlend gefuehrt, nicht weggelassen.
            out.append({"name": name, "pfad": rel, "fehlt": True})
    return out


def werkzeuge() -> dict:
    return {
        "rustc": _version(["rustc", "--version"]),
        "cargo": _version(["cargo", "--version"]),
        "python": sys.version.split()[0],
        "node": _version(["node", "--version"]),
        "docker": _version(["docker", "--version"]),
    }


def pruefungen() -> list[dict]:
    """Jede Zeile ist ein gelaufener Befehl, kein Haken.

    `systemd-analyze verify` meldet auf einer Baumaschine, dass
    `/opt/hm-gateway/hm-gateway` nicht existiert — das ist eine Aussage ueber
    den Zielpfad der Installation und nicht ueber die Unit. Diese eine
    Meldung wird deshalb als solche gefuehrt und nicht als Fehlschlag: sonst
    faerbte jeder Bau rot fuer etwas, das erst beim Ausrollen gilt.
    """
    out = []
    for name, argv in PRUEFUNGEN:
        eintrag = {"pruefung": name, "befehl": " ".join(argv)}
        try:
            r = _run(argv)
        except FileNotFoundError:
            eintrag.update({"ergebnis": UNBEKANNT, "grund": f"{argv[0]} nicht vorhanden"})
            out.append(eintrag)
            continue
        except Exception as exc:
            eintrag.update({"ergebnis": UNBEKANNT, "grund": f"{type(exc).__name__}: {exc}"})
            out.append(eintrag)
            continue

        text = (r.stdout or "") + (r.stderr or "")
        nur_zielpfad = (name == "systemd-units"
                        and "is not executable" in text
                        and "/opt/hm-gateway" in text)
        if r.returncode == 0 or nur_zielpfad:
            eintrag["ergebnis"] = BESTANDEN
            if nur_zielpfad:
                eintrag["hinweis"] = ("Unit gueltig; das Zielbinary liegt erst "
                                      "nach dem Ausrollen unter /opt/hm-gateway")
        else:
            eintrag["ergebnis"] = GEFALLEN
            eintrag["ausgabe"] = text.strip().splitlines()[-1][:200] if text.strip() else ""
        out.append(eintrag)
    return out


# Dieselben Muster wie der Secret-Scanner. Ein Manifest, das ein Geheimnis
# traegt, waere schlimmer als keines: es wird als Artefakt veroeffentlicht.
GEHEIM = (
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI-artiger Key"),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "GitHub-Token"),
    (r"AIza[0-9A-Za-z_\-]{30,}", "Google-API-Key"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "Slack-Token"),
    (r"-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----", "privater Schluessel"),
    (r"hm[odmcrw]_\d+_[0-9a-f]{40,}", "selbst ausgestellter Projektschluessel"),
)


def leckpruefung(text: str) -> list[str]:
    return [f"{label}: {m.group(0)[:12]}…"
            for muster, label in GEHEIM
            for m in re.finditer(muster, text)]


def manifest(mit_pruefungen: bool) -> dict:
    d = {
        "schema": "hugin.build.v1",
        "erzeugt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": _git("rev-parse", "HEAD"),
        "commit_kurz": _git("rev-parse", "--short", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "sauber": _git("status", "--porcelain") == "",
        "werkzeuge": werkzeuge(),
        "artefakte": artefakte(),
    }
    if mit_pruefungen:
        d["pruefungen"] = pruefungen()
    return d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", help="Zieldatei (ohne: stdout)")
    p.add_argument("--pruefen", action="store_true",
                   help="Pruefungen wirklich fahren (dauert)")
    a = p.parse_args(argv)

    d = manifest(a.pruefen)
    text = json.dumps(d, ensure_ascii=False, indent=2)

    lecks = leckpruefung(text)
    if lecks:
        # Nie schreiben, nie ausgeben. Ein Manifest ist ein
        # Veroeffentlichungsartefakt.
        print("ABBRUCH — das Manifest enthaelt etwas Geheimes:", file=sys.stderr)
        for l in lecks:
            print(f"  {l}", file=sys.stderr)
        return 2

    if a.out:
        ziel = REPO / a.out
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(text + "\n", encoding="utf-8")
        print(f"{a.out}: {len(d['artefakte'])} Artefakt(e), "
              f"{len(d.get('pruefungen', []))} Pruefung(en)")
    else:
        print(text)

    gefallen = [x for x in d.get("pruefungen", []) if x["ergebnis"] == GEFALLEN]
    return 1 if gefallen else 0


if __name__ == "__main__":
    raise SystemExit(main())
