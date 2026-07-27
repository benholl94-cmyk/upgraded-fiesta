#!/usr/bin/env python3
"""hugin_selfheal.py -- das Repo haelt sich selbst instand.

## Was hier vorher fehlte

Es gab vier Zeitplaene (`munin-link-hourly`, `platform-monitoring`,
`visible-monitoring`, `visible-status`). Alle vier **beobachten**: sie messen,
schreiben einen Bericht ins Repo und enden. Keiner repariert etwas, keiner
ruft Supervisor oder Clarity auf, und keiner haelt eine Faehigkeit am Leben.
Beobachtung ohne Erhaltung ist kein Selbsterhalt — sie erzeugt nur Dateien,
die niemand liest.

Ebenso wenig selbsterhaltend ist ein Werkzeug, dessen Loesung darin besteht,
dass der Master einen Befehl in seine Shell tippt. Diese Shell endet, der
Container endet, und beim naechsten Start ist alles wieder offen. Genau diesen
Fehler haben die letzten Sitzungen wiederholt.

## Was Selbsterhalt verlangt

    1. Der Zustand ueberlebt.        Alles Noetige ist aus dem Repo allein
                                     wiederherstellbar — oder wird zur
                                     Laufzeit neu erzeugt, weil beide Enden
                                     dem Projekt gehoeren.
    2. Es laeuft ohne Anstoss.       Zeitplan auf eigener Infrastruktur.
    3. Es repariert, was mechanisch  Kein Mensch fuer eine Dateikopie.
       reparierbar ist.
    4. Es kostet nichts.             Oeffentliches Repo: Actions frei.
                                     Kostensperre bleibt zu.
    5. Es eskaliert nur den Rest —   Und nimmt die Eskalation zurueck,
       genau einmal.                 sobald die Ursache weg ist.

Punkt 5 ist der, an dem solche Systeme sonst sterben: eine Meldung, die
bleibt, nachdem das Problem weg ist, bringt allen bei, Meldungen zu
ignorieren. Deshalb ist `zurueckgenommen` hier ein eigener Ausgang und kein
Sonderfall.

## Wo die Grenze verlaeuft

Repariert wird nur, was **deterministisch** ist: eine Kopie, ein fehlender
Schluessel, den das Projekt selbst ausstellt. Alles, was eine Entscheidung
verlangt — welcher Code richtig ist, ob ein Provider genutzt werden soll, ob
Geld ausgegeben wird — wird eskaliert, nie geraten. Ein Automat, der raet,
ist gefaehrlicher als einer, der stehen bleibt.

    python3 scripts/hugin_selfheal.py --dry-run   # was waere zu tun
    python3 scripts/hugin_selfheal.py --apply     # tun
    python3 scripts/hugin_selfheal.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ESKALATION = REPO / "status" / "selbsterhalt.json"

GETAN, NICHTS, ESKALIERT, GESCHEITERT = "getan", "nichts", "eskaliert", "gescheitert"


@dataclass
class Schritt:
    id: str
    was: str
    stand: str
    detail: str = ""
    braucht_master: str = ""     # nur bei ESKALIERT: was genau der Master tun muss

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v}


def _run(*argv, cwd=REPO, env=None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env=e)


# ---------------------------------------------------------------------------
# Reparaturen — deterministisch, nachgeprueft
# ---------------------------------------------------------------------------

def r_index_sync(apply: bool) -> Schritt:
    """`index.html` muss bytegleich zu `hugin.html` sein.

    Bisher liess CI den Lauf hier *scheitern*. Das ist richtig fuer einen
    Menschen, der gerade editiert, und falsch fuer ein System, das sich selbst
    erhaelt: die Regel ist deterministisch, es gibt genau eine richtige
    Aufloesung, und niemand muss dafuer gefragt werden.
    """
    quelle, ziel = REPO / "hugin/hugin.html", REPO / "hugin/index.html"
    if not quelle.is_file():
        return Schritt("index-sync", "index.html synchron halten", GESCHEITERT,
                       "hugin/hugin.html fehlt")
    if ziel.is_file() and ziel.read_bytes() == quelle.read_bytes():
        return Schritt("index-sync", "index.html synchron halten", NICHTS, "bereits gleich")
    if not apply:
        return Schritt("index-sync", "index.html synchron halten", GETAN,
                       "wuerde kopieren (dry-run)")
    shutil.copyfile(quelle, ziel)
    # Nachgeprueft, nicht angenommen -- eine Reparatur, die sich selbst
    # bestaetigt, ohne zu messen, ist keine.
    if ziel.read_bytes() != quelle.read_bytes():
        return Schritt("index-sync", "index.html synchron halten", GESCHEITERT,
                       "Kopie stimmt danach immer noch nicht")
    return Schritt("index-sync", "index.html synchron halten", GETAN, "kopiert und geprueft")


def r_schluessel(apply: bool) -> Schritt:
    """Der Lauf stellt sich seine eigenen Schluessel aus.

    Die 6 selbst ausstellbaren Schluessel gelten nur zwischen Teilen dieses
    Projekts. In einem frischen Container ist ein frisch erzeugter Wert
    deshalb **gueltig** — es gibt niemanden, der den alten kennen muesste.
    Genau das macht diesen Teil selbsterhaltend: kein Backup noetig, keine
    Uebergabe, kein Master.

    Anders bei den 11 anbietergebundenen Schluesseln: die kann nur ausstellen,
    wer das Konto hat. Sie werden nie geraten und nie erzeugt.
    """
    seed = Path.home() / ".hugin" / "master.seed"
    if seed.is_file():
        return Schritt("schluessel", "eigene Schluessel bereitstellen", NICHTS,
                       "Seed vorhanden")
    if not apply:
        return Schritt("schluessel", "eigene Schluessel bereitstellen", GETAN,
                       "wuerde Seed erzeugen (dry-run)")
    r = _run(sys.executable, "scripts/hugin_keyring.py", "init")
    if r.returncode != 0:
        return Schritt("schluessel", "eigene Schluessel bereitstellen", GESCHEITERT,
                       (r.stderr or r.stdout).strip()[:200])
    if not seed.is_file():
        return Schritt("schluessel", "eigene Schluessel bereitstellen", GESCHEITERT,
                       "init meldete Erfolg, aber es liegt kein Seed da")
    return Schritt("schluessel", "eigene Schluessel bereitstellen", GETAN,
                   "Seed erzeugt — die 6 projekteigenen Schluessel sind ableitbar")


REPARATUREN = (r_index_sync, r_schluessel)


# ---------------------------------------------------------------------------
# Pruefungen — was danach noch nicht stimmt
# ---------------------------------------------------------------------------

def p_supervisor() -> Schritt:
    r = _run(sys.executable, "scripts/munin_supervisor.py", "--quick")
    if r.returncode == 0:
        return Schritt("supervisor", "Verfassungs-Audit", NICHTS, "sauber")
    zeilen = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("[")]
    return Schritt("supervisor", "Verfassungs-Audit", ESKALIERT,
                   " | ".join(zeilen)[:600],
                   braucht_master="Diese Befunde verlangen eine Entscheidung — "
                                  "der Supervisor loest nie selbst auf.")


def p_tests() -> Schritt:
    r = _run(sys.executable, "-m", "pytest", "tests/", "-q")
    letzte = (r.stdout or r.stderr).strip().splitlines()
    kurz = letzte[-1][:200] if letzte else ""
    if r.returncode == 0:
        return Schritt("tests", "Testsuite", NICHTS, kurz)
    return Schritt("tests", "Testsuite", ESKALIERT, kurz,
                   braucht_master="Ein roter Test ist keine mechanische "
                                  "Reparatur — welcher Code richtig ist, "
                                  "entscheidet kein Automat.")


def p_clarity() -> Schritt:
    r = _run(sys.executable, "scripts/hugin_clarity.py", "--json")
    try:
        daten = json.loads(r.stdout)
    except Exception:
        return Schritt("clarity", "Einsatzbereitschaft", GESCHEITERT,
                       "Clarity-Ausgabe nicht lesbar")
    offen = [p for g in daten for p in g["punkte"] if p.get("stand") == "OFFEN"]
    if not offen:
        return Schritt("clarity", "Einsatzbereitschaft", NICHTS, "nichts offen")
    return Schritt(
        "clarity", "Einsatzbereitschaft", ESKALIERT,
        " | ".join(f"{p['id']}: {p['gemessen']}" for p in offen)[:600],
        braucht_master="\n".join(f"  {p['id']}: {p.get('befehl', '—')}" for p in offen))


def p_anker() -> Schritt:
    r = _run(sys.executable, "scripts/munin_continuity.py", "verify")
    if r.returncode == 0:
        return Schritt("anker", "Ledger-Anker", NICHTS, "gueltig")
    return Schritt("anker", "Ledger-Anker", ESKALIERT,
                   (r.stdout or r.stderr).strip().splitlines()[-1][:200]
                   if (r.stdout or r.stderr).strip() else "",
                   braucht_master="Ein verrotteter Anker zeigt auf etwas, das "
                                  "es nicht mehr gibt — was an seine Stelle "
                                  "gehoert, weiss nur ein Mensch.")


PRUEFUNGEN = (p_supervisor, p_tests, p_clarity, p_anker)


# ---------------------------------------------------------------------------
# Eskalation — genau eine, und sie wird zurueckgenommen
# ---------------------------------------------------------------------------

def eskalation_schreiben(schritte: list[Schritt]) -> dict:
    """Ein Zustand, den der Workflow in genau eine Meldung uebersetzt.

    Frueherer Zustand ist Teil der Ausgabe: `zurueckgenommen` bedeutet, dass
    beim letzten Lauf etwas offen war und jetzt nicht mehr. Ohne dieses Feld
    kann der Workflow eine erledigte Meldung nicht schliessen, und eine
    Meldung, die nach der Loesung stehen bleibt, bringt allen bei, Meldungen
    zu ignorieren.
    """
    offen = [s for s in schritte if s.stand in (ESKALIERT, GESCHEITERT)]
    vorher = {}
    if ESKALATION.is_file():
        try:
            vorher = json.loads(ESKALATION.read_text(encoding="utf-8"))
        except Exception:
            vorher = {}
    war_offen = bool(vorher.get("offen"))

    zustand = {
        "schema": "hugin.selbsterhalt.v1",
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "offen": [s.to_dict() for s in offen],
        "getan": [s.to_dict() for s in schritte if s.stand == GETAN],
        "zurueckgenommen": bool(war_offen and not offen),
    }
    ESKALATION.parent.mkdir(parents=True, exist_ok=True)
    ESKALATION.write_text(json.dumps(zustand, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return zustand


def bericht(zustand: dict) -> str:
    """Der Text, der als Meldung erscheint. Erst was zu tun ist, dann warum."""
    if not zustand["offen"]:
        return ("Selbsterhalt: nichts offen. Alles, was mechanisch reparierbar "
                "war, ist repariert.")
    zeilen = ["Der Selbsterhalt-Lauf hat repariert, was ohne Entscheidung "
              "reparierbar war. Das hier verlangt dich:", ""]
    for s in zustand["offen"]:
        zeilen.append(f"**{s['id']}** — {s['was']}")
        zeilen.append(f"gemessen: {s.get('detail', '')}")
        if s.get("braucht_master"):
            zeilen.append(f"{s['braucht_master']}")
        zeilen.append("")
    if zustand["getan"]:
        zeilen.append("Selbst erledigt in diesem Lauf:")
        zeilen += [f"- {s['id']}: {s.get('detail', '')}" for s in zustand["getan"]]
    return "\n".join(zeilen)


def lauf(apply: bool) -> tuple[list[Schritt], dict]:
    schritte = [fn(apply) for fn in REPARATUREN]
    schritte += [fn() for fn in PRUEFUNGEN]
    return schritte, eskalation_schreiben(schritte)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="Reparaturen wirklich ausfuehren")
    g.add_argument("--dry-run", action="store_true", help="nur zeigen (Standard)")
    p.add_argument("--json", action="store_true")
    # Fuer den Workflow: eine Zeile Zustand und ein fertiger Meldungstext.
    # Damit bleibt das YAML frei von Logik -- Mehrzeiliges Python in einem
    # `run:`-Block hat in diesem Repo schon zweimal die Datei zerlegt.
    p.add_argument("--status", action="store_true",
                   help="ein Wort: offen | leer | zurueckgenommen")
    p.add_argument("--bericht", action="store_true", help="Meldungstext")
    a = p.parse_args(argv)

    if a.status or a.bericht:
        # Liest den zuletzt geschriebenen Zustand, misst NICHT neu: sonst
        # koennte zwischen Lauf und Meldung etwas anderes herauskommen als
        # das, was der Lauf tatsaechlich getan hat.
        z = json.loads(ESKALATION.read_text(encoding="utf-8")) if ESKALATION.is_file() else {}
        if a.status:
            print("offen" if z.get("offen") else
                  ("zurueckgenommen" if z.get("zurueckgenommen") else "leer"))
        else:
            print(bericht(z or {"offen": [], "getan": []}))
        return 0

    schritte, zustand = lauf(a.apply)

    if a.json:
        print(json.dumps({"schritte": [s.to_dict() for s in schritte],
                          "zustand": zustand}, ensure_ascii=False, indent=2))
    else:
        marke = {GETAN: "[REPARIERT]", NICHTS: "[ok       ]",
                 ESKALIERT: "[MASTER   ]", GESCHEITERT: "[FEHLER   ]"}
        for s in schritte:
            print(f"{marke[s.stand]} {s.id:<12} {s.detail}")
        print()
        print(bericht(zustand))

    # Ausgang 0 auch bei Eskalation: der Lauf hat getan, was er konnte. Ein
    # roter Lauf fuer etwas, das nur der Master entscheiden kann, faerbt die
    # Historie dauerhaft rot und macht echte Fehlschlaege unsichtbar.
    return 1 if any(s.stand == GESCHEITERT for s in schritte) else 0


if __name__ == "__main__":
    raise SystemExit(main())
