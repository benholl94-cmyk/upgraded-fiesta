#!/usr/bin/env python3
"""hugin_inventar.py -- jeder Teil des Systems, und kein Teil im Zustand "unbekannt".

## Die Frage, die dieses Programm beantwortet

Nicht "laeuft es" (das tut `codeam_cli.py verify`) und nicht "darf es so
sein" (das tut `munin_supervisor.py`), sondern: **ist jeder Teil dieses
Repos ueberhaupt erfasst -- und wenn etwas offen ist, welcher Befehl
schliesst es.**

Ein Teil, ueber den niemand etwas sagen kann, ist gefaehrlicher als ein
kaputter: der kaputte faellt auf. Dieses Repo hat genau daran schon dreimal
verloren -- die Plugin-Dispatch, die im Container fehlte; der Chat, dessen
`agents/` das Image nicht kopierte; die Erdung, die ohne `.git` von 178 auf
59 Faelle fiel. Alle drei waren nicht kaputt, sondern **unerfasst**.

## Drei Zustaende, und der dritte ist der Punkt

| Zustand | Bedeutung | Exit |
|---|---|---|
| `geschlossen` | erfasst, erreichbar, gepruefte Aussage moeglich | 0 |
| `offen` | etwas fehlt -- **mit dem Befehl, der es schliesst** | 1 |
| `extern` | von hier aus nicht entscheidbar (Konto, Hardware, Master) | 0 |

**`unbekannt` gibt es nicht.** Kann das Programm einen Teil nicht
einordnen, wird er als `offen` gefuehrt und benannt -- niemals weggelassen.
Eine Liste, aus der Unerklaertes verschwindet, sieht immer vollstaendig aus.

`extern` von `offen` zu trennen ist keine Bequemlichkeit: eine Liste, die
nie leer wird, wird nicht mehr gelesen. Dieselbe Lehre wie bei
`hugin_clarity.py`, wo `--offen` genau deshalb einen eigenen Ausgang hat.

## Was je Teil gerechnet wird

Nichts davon ist gepflegt; alles wird aus dem Baum gelesen:

* **erreichbar** -- verweist irgendetwas ausserhalb des Teils auf ihn?
  Ein Skript, das kein Workflow, kein Test und keine Doku nennt, ist
  entweder tot oder unauffindbar. Beides ist ein Befund.
* **gepruefft** -- nennt ihn eine Datei unter `tests/`?
* **beschrieben** -- nennt ihn `CLAUDE.md` oder `docs/`?
* **im Image** -- deckt ein `COPY` des Dockerfiles seinen Pfad ab? Nur fuer
  Teile, die zur Laufzeit gebraucht werden.

    python3 scripts/hugin_inventar.py            # Bericht
    python3 scripts/hugin_inventar.py --offen    # nur das Schliessbare
    python3 scripts/hugin_inventar.py --json
    python3 scripts/hugin_inventar.py --index    # docs/INVENTAR.md schreiben
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _log import get_logger          # noqa: E402

log = get_logger(__name__)

REPO = Path(__file__).resolve().parent.parent

GESCHLOSSEN, OFFEN, EXTERN = "geschlossen", "offen", "extern"

#: Der erzeugte Index. Wird beim Messen ausgeklammert -- siehe `Baum`.
INDEX_DATEI = "docs/INVENTAR.md"

#: Teile, die zur Laufzeit im Containerimage liegen muessen. Alles andere
#: (Tests, Workflows, Skills) gehoert bewusst nicht hinein -- ein Image, das
#: die Testsuite mitschleppt, ist groesser und nicht sicherer.
LAUFZEIT = ("plugins/", "agents/", "config/", "corpus/", "scripts/")

#: Bewusst nicht erreichbar-geprueft: Einstiegspunkte werden von aussen
#: aufgerufen, nicht von innen referenziert.
EINSTIEG = {"scripts/munin_bridge.py", "scripts/codeam_cli.py",
            "scripts/hugin_inventar.py"}


@dataclass
class Teil:
    pfad: str
    art: str                       # krate | skript | plugin | workflow | skill | konfig | doku
    zustand: str = GESCHLOSSEN
    fakten: dict = field(default_factory=dict)
    grund: str = ""
    befehl: str = ""

    def to_dict(self) -> dict:
        d = {"pfad": self.pfad, "art": self.art, "zustand": self.zustand,
             "fakten": self.fakten}
        if self.grund:
            d["grund"] = self.grund
        if self.befehl:
            d["befehl"] = self.befehl
        return d


# ---------------------------------------------------------------------------
# Der Baum, einmal gelesen
# ---------------------------------------------------------------------------

def _getrackt() -> list[str]:
    """Nur, was git kennt.

    **Sonst ist das Inventar nicht reproduzierbar** -- und genau das ist in
    CI aufgefallen: lokal lagen `status/`-Protokolle, `vendor/llama.cpp` und
    ein 6,6-GB-Modell im Baum, auf dem Runner nicht. Nennt eine ungetrackte
    Logdatei ein Skript, gilt es hier als erreichbar und dort nicht -- der
    eingecheckte Index wich vom gerechneten ab, und der Test fiel zu Recht.

    Ein Inventar des Repos muss lesen, was **im Repo** ist, nicht was
    zufaellig im Arbeitsverzeichnis liegt. Dieselbe Regel wie im
    Metatest-Sandkasten, der ebenfalls ueber `git ls-files` geht.
    """
    import subprocess
    # `--cached` allein reicht nicht: eine **neue** Datei ist unsichtbar,
    # solange sie nicht gestaged ist. Der Index konnte damit nie die Datei
    # enthalten, die im selben Commit dazukommt -- gemessen an
    # `.github/workflows/zyklus.yml`, das der Index als 19. Workflow
    # verschwieg und CI zu Recht rot machte.
    #
    # `--others --exclude-standard` schliesst die Luecke, ohne die
    # Reproduzierbarkeit aufzugeben: ignorierte Laufzeitdateien
    # (`config/llm-active.json`, `config/knowledge-loop-state.json`) bleiben
    # draussen, und auf einem frischen Checkout ist diese Menge ohnehin
    # leer -- dort zaehlt weiterhin nur, was git kennt.
    try:
        r = subprocess.run(["git", "ls-files", "-z", "--cached", "--others",
                            "--exclude-standard"], cwd=REPO,
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("git ls-files nicht ausfuehrbar: %s", exc)
        return []
    if r.returncode != 0:
        log.warning("git ls-files: exit %s", r.returncode)
        return []
    return sorted({x for x in r.stdout.split("\0") if x})


class Baum:
    """Alle getrackten Textdateien einmal im Speicher.

    Je Teil erneut ueber das Repo zu greppen waere bei ~130 Teilen und ~400
    Dateien 52.000 Dateilesungen. Einmal lesen ist derselbe Gedanke wie beim
    vorgebauten Korpus: die Messung soll billig genug sein, dass sie
    tatsaechlich laeuft.
    """

    ENDUNGEN = (".py", ".rs", ".md", ".yml", ".yaml", ".json", ".toml",
                ".sh", ".html", ".ts", ".js", "Dockerfile")

    def __init__(self) -> None:
        self.dateien: dict[str, str] = {}
        for rel in _getrackt():
            p = REPO / rel
            if not p.is_file():
                continue
            if rel.startswith("corpus/"):
                continue
            # DER EIGENE BERICHT ZAEHLT NICHT ALS NENNUNG. `docs/INVENTAR.md`
            # listet jeden Teil auf -- wer ihn mitliest, findet jeden Teil
            # "erreichbar" und "beschrieben" und misst nur noch sich selbst.
            # Gemessen: Workflows sprangen dadurch von 15/18 auf 18/18, ohne
            # dass sich irgendetwas geaendert haette. Dieselbe Selbstbezugs-
            # falle wie beim Korpus, der seine eigenen Gegenbeispiele las.
            if rel == INDEX_DATEI:
                continue
            if not (p.suffix in self.ENDUNGEN or p.name == "Dockerfile"):
                continue
            try:
                self.dateien[rel] = p.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                log.warning("%s nicht lesbar: %s", rel, exc)

    def nennt(self, name: str, ausser: str = "") -> list[str]:
        """Welche Dateien nennen diesen Namen -- ohne die Datei selbst."""
        return [rel for rel, txt in self.dateien.items()
                if rel != ausser and name in txt]


def _dockerfile_deckt(baum: Baum, pfad: str) -> bool:
    """Deckt ein `COPY` des Laufzeit-Stages diesen Pfad ab?

    Nur das Runtime-Stage zaehlt. `COPY . .` steht im Builder und sagt ueber
    das ausgelieferte Image nichts aus -- genau diese Verwechslung liesse
    jede Pruefung hier gruen melden.
    """
    text = baum.dateien.get("Dockerfile", "")
    _, _, laufzeit = text.partition("FROM")           # erstes Stage weg
    _, _, laufzeit = laufzeit.partition("FROM")       # ab dem zweiten
    quelle = laufzeit if laufzeit else text
    for m in re.finditer(r"^COPY\s+(?:--from=\S+\s+)?(\S+)\s", quelle, re.M):
        ziel = m.group(1)
        if ziel in (".", "./"):
            continue
        if pfad == ziel or pfad.startswith(ziel.rstrip("/") + "/"):
            return True
    return False


# ---------------------------------------------------------------------------
# Die Teile
# ---------------------------------------------------------------------------

def _sammeln() -> list[tuple[str, str]]:
    """Die Teile -- ebenfalls nur getrackte.

    `Baum` allein umzustellen reichte nicht: die Sammlung griff weiter
    direkt aufs Dateisystem und nahm `config/knowledge-loop-state.json` und
    `config/llm-active.json` mit -- beides ungetrackter Laufzeitzustand, der
    lokal existiert und auf dem Runner nicht. Derselbe Fehler in der anderen
    Haelfte, gefunden erst durch den Vergleich gegen einen frischen Klon.
    """
    getrackt = set(_getrackt())

    def da(rel: str) -> bool:
        return rel in getrackt

    out: list[tuple[str, str]] = []
    for p in sorted((REPO / "crates").rglob("Cargo.toml")):
        rel = str(p.parent.relative_to(REPO))
        if da(str(p.relative_to(REPO))):
            out.append((rel, "krate"))
    for p in sorted((REPO / "scripts").glob("*.py")):
        if da(str(p.relative_to(REPO))):
            out.append((str(p.relative_to(REPO)), "skript"))
    for p in sorted((REPO / "plugins").glob("*.py")):
        if da(str(p.relative_to(REPO))):
            out.append((str(p.relative_to(REPO)), "plugin"))
    for p in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        if da(str(p.relative_to(REPO))):
            out.append((str(p.relative_to(REPO)), "workflow"))
    skills = REPO / ".claude" / "skills"
    if skills.is_dir():
        for p in sorted(skills.iterdir()):
            if p.is_dir():
                out.append((str(p.relative_to(REPO)), "skill"))
    for p in sorted((REPO / "config").glob("*.json")):
        if da(str(p.relative_to(REPO))):
            out.append((str(p.relative_to(REPO)), "konfig"))
    docs = REPO / "docs"
    if docs.is_dir():
        for p in sorted(docs.glob("*.md")):
            if da(str(p.relative_to(REPO))):
                out.append((str(p.relative_to(REPO)), "doku"))
    return out


_GESAMMELT: set[str] | None = None


def _gesammelt() -> set[str]:
    """Was pytest tatsaechlich sammelt -- gerechnet, nicht gegrept.

    **Vierter Messfehler dieses Programms, und derselbe Fehlertyp wie die
    drei davor: eine Naeherung wurde fuer die Sache gehalten.** Die
    Namenssuche im Dateitext findet keinen parametrisierten Test.
    `tests/test_inventar_und_skripte.py` spannt sich ueber
    `(REPO / "scripts").glob("*.py")` auf und prueft **jedes** Skript auf
    Syntax, Moduldocstring, `--help` und das Verbot von Shell-Aufrufen;
    im Quelltext steht
    dabei kein einziger Dateiname.

    Gemessen: 12 Testfaelle allein fuer die drei Skripte, die das Inventar
    als "keine Testdatei nennt diesen Teil" fuehrte, und 6 fuer die drei
    Workflows. Der Befund war jedes Mal falsch -- und ein falscher Befund
    kostet die Glaubwuerdigkeit der ganzen Liste.

    `--collect-only` fuehrt nichts aus, es sammelt nur. Einmal je Lauf.
    """
    global _GESAMMELT
    if _GESAMMELT is not None:
        return _GESAMMELT
    import subprocess
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/",
                            "--collect-only", "-q", "--no-header", "-p",
                            "no:cacheprovider"],
                           cwd=REPO, capture_output=True, text=True, timeout=600)
        _GESAMMELT = {z.strip() for z in r.stdout.splitlines() if "::" in z}
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("pytest --collect-only nicht ausfuehrbar: %s", exc)
        _GESAMMELT = set()
    return _GESAMMELT


def _in_testfaellen(pfad: str) -> bool:
    """Nennt irgendein *gesammelter* Testfall diesen Teil?"""
    name = Path(pfad).name
    ohne = name[:-3] if name.endswith(".py") else name
    return any(name in fall or ohne in fall or pfad in fall
               for fall in _gesammelt())


def _geprueft(pfad: str, art: str, nenner: list[str], baum: Baum) -> bool:
    """Wird dieser Teil von irgendeinem Test beruehrt?

    **Fuer Kraten ist `tests/` die falsche Frage** -- und die erste Fassung
    hier stellte genau sie. Rust legt Modultests in `#[cfg(test)]` neben den
    Code; `crates/hm-vector` hat neun, `crates/hm-plugins` fuenfzehn. Der
    Pruefer meldete trotzdem *"keine Testdatei nennt diesen Teil"* -- fuer
    12 von 20 Kraten, alle falsch.

    Das ist die teuerste Sorte Befund: er sieht aus wie Arbeit, ist keiner,
    und nach dem zweiten Mal wird die ganze Liste nicht mehr gelesen.
    """
    if art == "krate":
        wurzel = pfad.rstrip("/") + "/"
        for rel, txt in baum.dateien.items():
            if rel.startswith(wurzel) and rel.endswith(".rs") and (
                    "#[cfg(test)]" in txt or "#[test]" in txt
                    or "#[tokio::test]" in txt):
                return True
        return any(r.startswith("tests/") for r in nenner) or _in_testfaellen(pfad)
    return any(r.startswith("tests/") for r in nenner) or _in_testfaellen(pfad)


def _pruefe(pfad: str, art: str, baum: Baum) -> Teil:
    name = Path(pfad).name
    # Auch der Modulname ohne Endung. Ein Test schreibt `import hugin_keyring`
    # und nie `hugin_keyring.py` -- die erste Fassung suchte nur den
    # Dateinamen und meldete deshalb getestete Skripte als ungeprueft.
    kandidaten = [pfad, name]
    if art in ("skript", "plugin") and name.endswith(".py"):
        kandidaten.append(name[:-3])
    # VEREINIGUNG, nicht die erste nichtleere Liste. Die vorige Fassung brach
    # beim ersten Treffer ab: `CLAUDE.md` nennt den vollen Pfad, also wurde
    # nach dem Modulnamen gar nicht mehr gesucht -- und genau unter dem nennt
    # der Test ihn. Ergebnis: getestete Skripte als ungeprueft gemeldet.
    treffer: set[str] = set()
    for k in kandidaten:
        treffer.update(baum.nennt(k, ausser=pfad))
    nenner = sorted(treffer)

    fakten = {
        "erreichbar": bool(nenner) or pfad in EINSTIEG or _in_testfaellen(pfad),
        "geprueft": _geprueft(pfad, art, nenner, baum),
        "beschrieben": any(r == "CLAUDE.md" or r.startswith("docs/")
                           for r in nenner),
        "nennungen": len(nenner),
    }
    if any(pfad.startswith(v) for v in LAUFZEIT):
        fakten["im_image"] = _dockerfile_deckt(baum, pfad)

    t = Teil(pfad=pfad, art=art, fakten=fakten)

    if not fakten["erreichbar"]:
        t.zustand, t.grund = OFFEN, "nichts im Repo nennt diesen Teil"
        t.befehl = (f"entweder anbinden (Test, Workflow oder Doku) oder "
                    f"entfernen: git rm {pfad}")
        return t
    if fakten.get("im_image") is False:
        t.zustand = OFFEN
        t.grund = "wird zur Laufzeit gebraucht, liegt aber nicht im Image"
        t.befehl = f"COPY {Path(pfad).parts[0]}/ /app/{Path(pfad).parts[0]}/ im Dockerfile"
        return t
    if art in ("krate", "skript", "plugin") and not fakten["geprueft"]:
        t.zustand = OFFEN
        t.grund = "keine Testdatei nennt diesen Teil"
        t.befehl = f"tests/ um einen Fall fuer {name} ergaenzen"
        return t
    return t


def inventar() -> list[Teil]:
    baum = Baum()
    return [_pruefe(p, a, baum) for p, a in _sammeln()]


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def index_md(teile: list[Teil]) -> str:
    """Der automatisch aktuelle Index.

    Von Hand gepflegte Uebersichten veralten still -- die Krate-Tabelle in
    `CLAUDE.md` nannte reale Kraten monatelang "intentional placeholders".
    Diese Datei wird erzeugt; wer sie von Hand aendert, verliert die
    Aenderung beim naechsten Lauf, und das ist beabsichtigt.
    """
    z = ["# Inventar", "",
         "**Erzeugt von `scripts/hugin_inventar.py --index`. Nicht von Hand "
         "aendern.** Jede Zeile ist gerechnet: erreichbar heisst, dass eine "
         "andere Datei im Repo diesen Teil nennt; geprueft heisst, dass eine "
         "Datei unter `tests/` ihn nennt.", ""]
    offen = [t for t in teile if t.zustand == OFFEN]
    z += [f"- Teile gesamt: **{len(teile)}**",
          f"- geschlossen: **{sum(1 for t in teile if t.zustand == GESCHLOSSEN)}**",
          f"- offen: **{len(offen)}**",
          f"- extern: **{sum(1 for t in teile if t.zustand == EXTERN)}**", ""]
    if offen:
        z += ["## Offen — mit dem Befehl, der es schliesst", "",
              "| Teil | Grund | Befehl |", "|---|---|---|"]
        z += [f"| `{t.pfad}` | {t.grund} | `{t.befehl}` |" for t in offen]
        z.append("")
    for art in sorted({t.art for t in teile}):
        gruppe = [t for t in teile if t.art == art]
        z += [f"## {art} — {len(gruppe)}", "",
              "| Teil | Zustand | geprueft | beschrieben |", "|---|---|---|---|"]
        for t in gruppe:
            z.append(f"| `{t.pfad}` | {t.zustand} | "
                     f"{'ja' if t.fakten.get('geprueft') else 'nein'} | "
                     f"{'ja' if t.fakten.get('beschrieben') else 'nein'} |")
        z.append("")
    return "\n".join(z) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--offen", action="store_true", help="nur das Schliessbare")
    p.add_argument("--json", action="store_true")
    p.add_argument("--index", action="store_true", help="docs/INVENTAR.md schreiben")
    a = p.parse_args(argv)

    teile = inventar()
    offen = [t for t in teile if t.zustand == OFFEN]

    if a.index:
        ziel = REPO / INDEX_DATEI
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(index_md(teile), encoding="utf-8")
        print(f"{INDEX_DATEI}: {len(teile)} Teile, {len(offen)} offen")
        return 1 if offen else 0

    if a.json:
        print(json.dumps({"teile": [t.to_dict() for t in teile],
                          "offen": len(offen), "gesamt": len(teile)},
                         ensure_ascii=False, indent=2))
        return 1 if offen else 0

    if not a.offen:
        for art in sorted({t.art for t in teile}):
            g = [t for t in teile if t.art == art]
            zu = sum(1 for t in g if t.zustand == GESCHLOSSEN)
            print(f"{art:<10} {zu}/{len(g)} geschlossen")
        print()
    for t in offen:
        print(f"[OFFEN ] {t.pfad}")
        print(f"         {t.grund}")
        print(f"         → {t.befehl}")
    if not offen:
        print("Kein Teil offen. Kein Teil unbekannt.")
    return 1 if offen else 0


if __name__ == "__main__":
    raise SystemExit(main())
