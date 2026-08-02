#!/usr/bin/env python3
"""hugin_zyklus.py -- die Kette: messen, erden, heilen, pruefen, berichten.

## Was hier NICHT gebaut wurde, und warum das der Punkt ist

Kein neues Werkzeug. Dieses Repo hat bereits alles, was eine
selbstpruefende Architektur braucht:

| Werkzeug | Frage |
|---|---|
| `hugin_inventar.py` | ist jeder Teil **erfasst** |
| `hugin_clarity.py --start` | verhindert etwas den **Betrieb** |
| `munin_supervisor.py` | **darf** es so sein |
| `hugin_corpus.py` | ist die **Erdung** aktuell |
| `hugin_selfheal.py` | laesst sich Deterministisches **reparieren** |
| `codeam_cli.py verify` | **traegt** es gerade |

Was fehlte: sie liefen **nie zusammen**. Jedes einzeln aufzurufen ist eine
Handlung, an die sich jemand erinnern muss -- und woran sich niemand
erinnert, das laeuft nicht. Ein Werkzeugkasten ohne Kette ist kein System,
sondern eine Ansammlung.

## Die Reihenfolge ist nicht beliebig

Sie folgt der Abhaengigkeit, nicht der Bequemlichkeit:

1. **messen** -- was ist ueberhaupt da (`inventar`). Ohne Bestandsaufnahme
   heilt man Dinge, die es nicht gibt.
2. **erden** -- Korpus neu bauen. Muss *vor* dem Pruefen laufen: ein
   veralteter Korpus laesst den Kern auf einen Stand antworten, den es
   nicht mehr gibt.
3. **heilen** -- nur Deterministisches (`selfheal`). Was Urteil braucht,
   wird gemeldet, nicht geraten.
4. **pruefen** -- Tests, Supervisor, Startfreiheit. *Nach* dem Heilen,
   sonst prueft man den Zustand von vorhin.
5. **berichten** -- Ledger und Bericht. Ein Lauf ohne Protokoll ist keine
   Autonomie, sondern Unsichtbarkeit.

## Drei Ausgaenge, und der mittlere ist der interessante

| Exit | Bedeutung |
|---|---|
| 0 | nichts zu tun, oder alles Aufgetretene wurde geschlossen |
| 1 | **etwas bleibt offen** -- mit Teil, Grund und Befehl |
| 2 | die Kette selbst ist gescheitert (ein Werkzeug fehlt oder stirbt) |

`2` ist von `1` getrennt, weil sie verschiedene Dinge bedeuten: ein offener
Befund ist Arbeit, eine gescheiterte Kette ist ein kaputtes Messgeraet. Sie
zusammenzuwerfen hiesse, ein defektes Thermometer wie Fieber zu behandeln.

**Ohne `--apply` wird nichts geschrieben.** Der Vorlauf sagt, was geschehen
wuerde. Das ist keine Zurueckhaltung aus Prinzip, sondern weil ein Zyklus,
der bei jedem Aufruf ungefragt den Baum aendert, in CI nicht einsetzbar
waere -- und ein Zyklus, der nicht in CI laeuft, laeuft nirgends.

    python3 scripts/hugin_zyklus.py              # Vorlauf, schreibt nichts
    python3 scripts/hugin_zyklus.py --apply      # heilen und erden
    python3 scripts/hugin_zyklus.py --json
    python3 scripts/hugin_zyklus.py --nur messen,pruefen
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _log import get_logger          # noqa: E402

log = get_logger(__name__)

REPO = Path(__file__).resolve().parent.parent

OK, BEFUND, GESCHEITERT = "ok", "befund", "gescheitert"


@dataclass
class Schritt:
    name: str
    stufe: str
    stand: str = OK
    dauer: float = 0.0
    zeilen: list[str] = field(default_factory=list)
    befehl: str = ""
    geaendert: bool = False

    def to_dict(self) -> dict:
        d = {"name": self.name, "stufe": self.stufe, "stand": self.stand,
             "dauer_s": round(self.dauer, 2)}
        if self.zeilen:
            d["ausgabe"] = self.zeilen[-6:]
        if self.befehl:
            d["befehl"] = self.befehl
        if self.geaendert:
            d["geaendert"] = True
        return d


def _lauf(argv: list[str], timeout: int = 1800) -> tuple[int, str]:
    try:
        r = subprocess.run([sys.executable, *argv], cwd=REPO,
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError as exc:
        return 127, f"nicht vorhanden: {exc}"
    except subprocess.TimeoutExpired:
        return 124, f"Zeitueberschreitung nach {timeout}s"
    except OSError as exc:
        return 126, f"{type(exc).__name__}: {exc}"


def _schritt(name: str, stufe: str, argv: list[str], *,
             befund_bei: tuple[int, ...] = (1,),
             befehl: str = "", timeout: int = 1800) -> Schritt:
    """Ein Kettenglied.

    `befund_bei` trennt "hat etwas gefunden" von "ist kaputtgegangen". Ein
    Werkzeug, das mit 1 endet, hat gearbeitet und etwas gefunden; eines,
    das mit 127 endet, gibt es nicht. Beides als Fehlschlag zu fuehren
    waere derselbe Fehler wie `unbekannt` als `in Ordnung` zu fuehren, nur
    andersherum.
    """
    # Nur Pfade werden auf Existenz geprueft. `-m pytest` ist ein Schalter,
    # keine Datei -- die erste Fassung hielt ihn fuer eine fehlende Datei und
    # meldete den Testschritt als GESCHEITERT. Der Zyklus hat damit seinen
    # eigenen Fehler korrekt als kaputtes Messgeraet gemeldet und nicht als
    # Befund; genau dafuer sind die beiden Ausgaenge getrennt.
    if not argv[0].startswith("-") and not (REPO / argv[0]).is_file():
        return Schritt(name, stufe, GESCHEITERT, 0.0,
                       [f"{argv[0]} fehlt"],
                       befehl or f"{argv[0]} wiederherstellen")
    t0 = time.perf_counter()
    code, text = _lauf(argv, timeout)
    zeilen = [z for z in text.splitlines() if z.strip()]
    stand = OK if code == 0 else (BEFUND if code in befund_bei else GESCHEITERT)
    return Schritt(name, stufe, stand, time.perf_counter() - t0, zeilen, befehl)


# ---------------------------------------------------------------------------
# Die Stufen
# ---------------------------------------------------------------------------

def s_messen() -> list[Schritt]:
    return [_schritt("inventar", "messen",
                     ["scripts/hugin_inventar.py", "--offen"],
                     befehl="python3 scripts/hugin_inventar.py --offen")]


def s_erden(apply: bool) -> list[Schritt]:
    """Korpus neu bauen -- vor dem Pruefen.

    Ein veralteter Korpus laesst den Kern auf einen Stand antworten, den es
    nicht mehr gibt. Das ist schlimmer als gar keine Erdung: eine Antwort
    aus dem Gestern sieht aus wie eine Antwort.
    """
    if not apply:
        s = _schritt("korpus", "erden", ["scripts/hugin_corpus.py", "pruefen"],
                     befehl="python3 scripts/hugin_corpus.py bauen")
        return [s]
    vorher = _korpus_stand()
    s = _schritt("korpus", "erden", ["scripts/hugin_corpus.py", "bauen"])
    s.geaendert = _korpus_stand() != vorher
    return [s]


def _korpus_stand() -> str:
    p = REPO / "corpus" / "manifest.json"
    if not p.is_file():
        return ""
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    # Der Zeitstempel gehoert NICHT dazu: er aendert sich bei jedem Bau und
    # liesse jeden Lauf als "geaendert" gelten.
    return json.dumps(d.get("dateien", {}), sort_keys=True)


def s_heilen(apply: bool) -> list[Schritt]:
    argv = ["scripts/hugin_selfheal.py"] + (["--apply"] if apply else [])
    s = _schritt("selfheal", "heilen", argv,
                 befehl="python3 scripts/hugin_selfheal.py --apply")
    s.geaendert = apply and any("repariert" in z.lower() or "behoben" in z.lower()
                                for z in s.zeilen)
    return [s]


def s_pruefen() -> list[Schritt]:
    return [
        _schritt("startfrei", "pruefen",
                 ["scripts/hugin_clarity.py", "--start"],
                 befehl='eval "$(python3 scripts/hugin_keyring.py env)"'),
        _schritt("supervisor", "pruefen",
                 ["scripts/munin_supervisor.py", "--quick"],
                 befund_bei=(1, 2),
                 befehl="python3 scripts/munin_supervisor.py"),
        _schritt("tests", "pruefen",
                 ["-m", "pytest", "tests/", "-q"],
                 befehl="python3 -m pytest tests/ -q"),
        _schritt("index", "pruefen",
                 ["scripts/hugin_inventar.py", "--index"],
                 befehl="python3 scripts/hugin_inventar.py --index"),
    ]


STUFEN = ("messen", "erden", "heilen", "pruefen")


def zyklus(apply: bool, nur: set[str] | None = None) -> list[Schritt]:
    aus: list[Schritt] = []
    for stufe in STUFEN:
        if nur and stufe not in nur:
            continue
        if stufe == "messen":
            aus += s_messen()
        elif stufe == "erden":
            aus += s_erden(apply)
        elif stufe == "heilen":
            aus += s_heilen(apply)
        elif stufe == "pruefen":
            aus += s_pruefen()
    return aus


# ---------------------------------------------------------------------------
# Bericht
# ---------------------------------------------------------------------------

MARKE = {OK: "[ok        ]", BEFUND: "[BEFUND    ]", GESCHEITERT: "[GESCHEITERT]"}


def bericht(schritte: list[Schritt]) -> str:
    z = [f"# Zyklus {datetime.now(timezone.utc).isoformat(timespec='seconds')}", ""]
    for stufe in STUFEN:
        g = [s for s in schritte if s.stufe == stufe]
        if not g:
            continue
        z.append(f"## {stufe}")
        for s in g:
            z.append(f"- **{s.name}** — {s.stand} ({s.dauer:.1f}s)"
                     + (" · geaendert" if s.geaendert else ""))
            if s.stand != OK and s.zeilen:
                z.append(f"  - `{s.zeilen[-1][:160]}`")
            if s.stand != OK and s.befehl:
                z.append(f"  - → `{s.befehl}`")
        z.append("")
    return "\n".join(z) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true",
                   help="heilen und erden wirklich ausfuehren (schreibt)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--nur", help=f"Teilmenge von {','.join(STUFEN)}")
    p.add_argument("--bericht", help="Bericht in diese Datei schreiben")
    a = p.parse_args(argv)

    nur = {x.strip() for x in a.nur.split(",")} if a.nur else None
    if nur and not nur <= set(STUFEN):
        print(f"unbekannte Stufe: {sorted(nur - set(STUFEN))}", file=sys.stderr)
        return 2

    schritte = zyklus(a.apply, nur)
    gescheitert = [s for s in schritte if s.stand == GESCHEITERT]
    befunde = [s for s in schritte if s.stand == BEFUND]

    if a.bericht:
        (REPO / a.bericht).parent.mkdir(parents=True, exist_ok=True)
        (REPO / a.bericht).write_text(bericht(schritte), encoding="utf-8")

    if a.json:
        print(json.dumps({"schritte": [s.to_dict() for s in schritte],
                          "befunde": len(befunde),
                          "gescheitert": len(gescheitert),
                          "geaendert": any(s.geaendert for s in schritte),
                          "apply": a.apply},
                         ensure_ascii=False, indent=2))
    else:
        for s in schritte:
            zeile = f"{MARKE[s.stand]} {s.stufe:<8} {s.name:<12} {s.dauer:5.1f}s"
            print(zeile + ("  geaendert" if s.geaendert else ""))
            if s.stand != OK:
                if s.zeilen:
                    print(f"              {s.zeilen[-1][:150]}")
                if s.befehl:
                    print(f"              → {s.befehl}")
        if not a.apply and (befunde or gescheitert):
            print("\nVorlauf — es wurde nichts geschrieben. "
                  "Mit --apply heilen und erden.")

    # Gescheitert schlaegt Befund: ein kaputtes Messgeraet ist kein Fieber.
    if gescheitert:
        return 2
    return 1 if befunde else 0


if __name__ == "__main__":
    raise SystemExit(main())
