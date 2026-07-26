#!/usr/bin/env python3
"""hugin_model.py -- Beschaffung, Prüfung und Identität des lokalen Modells.

## Warum die GGUF-Datei nicht im Repo liegt

6,6 GB in git lägen in **jedem** Clone, für immer, auch nach dem Löschen.
Genau dieser Fehler wurde in diesem Repo schon einmal in kleinerem Maßstab
aufgeräumt. Stattdessen: eine gepinnte Referenz in `config/model.json` mit
SHA256, und die Datei wird zur Laufzeit geholt und geprüft.

## Der Rebrand — was er ist und was nicht

Ein umbenanntes Modell ist dasselbe Modell. Metadaten zu ändern erzeugt keine
Fähigkeit. Der Unterschied entsteht **eine Schicht darüber**:

1. **Erdung.** Jede Frage wird zuerst durch `agents/kernel.py` geschickt, der
   aus der nachverifizierten Repo-Historie schliesst. Findet er einen
   Präzedenzfall, geht dieser als Beleg in den Prompt. Das Modell antwortet
   dann *aus geprüften Fakten dieses Repos*, nicht aus statistischem Vorwissen
   über Code im Allgemeinen.
2. **Invarianten als harte Schranke.** Verbietet eine Invariante den Weg, wird
   gar nicht erst gefragt.
3. **Format erzwungen.** Eine GBNF-Grammatik zwingt die Ausgabe in das
   Antwortschema aus `agents/protocol.py`. Kein Fliesstext, der nachher
   geparst werden muss.

Punkt 1 ist der eigentliche Rebrand: dasselbe Gewichtsfile, an eine Quelle
gebunden, die kein anderer hat.

## Lizenz

Mellum2 steht unter Apache-2.0 — Änderung und Weitergabe sind ausdrücklich
erlaubt, die Urheberangabe **muss** erhalten bleiben. `stamp` schreibt den
neuen Namen und trägt die Herkunft ausdrücklich mit ein, statt sie zu
ersetzen. Ein Rebrand, der die Attribution löscht, wäre lizenzwidrig.

    python3 scripts/hugin_model.py plan          # was wuerde passieren
    python3 scripts/hugin_model.py verify DATEI  # SHA256 gegen die Pinnung
    python3 scripts/hugin_model.py prompt "..."  # geerdeter Prompt (T1b)
    python3 scripts/hugin_model.py grammar       # GBNF fuer das Antwortschema
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "config" / "model.json"


def config() -> dict:
    if not CONFIG.is_file():
        raise SystemExit(f"Fehlt: {CONFIG.relative_to(REPO)}")
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def url(cfg: dict | None = None) -> str:
    u = (cfg or config())["upstream"]
    return (f"https://huggingface.co/{u['repo']}/resolve/{u['revision']}/{u['file']}")


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def verify(path: Path) -> tuple[bool, str]:
    """Hash gegen die Pinnung. Ein Modell mit anderem Inhalt ist ein anderes
    Modell -- egal wie die Datei heisst."""
    cfg = config()
    want = cfg["upstream"]["sha256"]
    if not path.is_file():
        return False, f"{path} existiert nicht"
    got = sha256_file(path)
    if got != want:
        return False, f"SHA256 weicht ab\n  erwartet {want}\n  gelesen  {got}"
    return True, f"SHA256 stimmt ({want[:16]}…)"


# ---------------------------------------------------------------------------
# Erdung -- der eigentliche Unterschied
# ---------------------------------------------------------------------------

SYSTEM = """Du bist der HUGIN-Kern, gebunden an das Repository \
benholl94-cmyk/upgraded-fiesta.

Harte Regeln:
- Antworte NUR aus den BELEGEN unten und aus dem gezeigten Code. Steht etwas
  nicht darin, sage "nicht belegt" — erfinde nichts.
- Eine INVARIANTE ist keine Empfehlung. Widerspricht die Aufgabe einer,
  verweigere und nenne sie.
- Eine SACKGASSE bedeutet: dieser Weg wurde versucht und ist gescheitert.
  Schlage ihn nicht erneut vor.
- Keine Vorrede, keine Zusammenfassung der Frage. Erster Satz ist die Antwort.
"""


def grounded_prompt(question: str, paths: tuple[str, ...] = ()) -> str:
    """Frage + Belege aus der eigenen Historie.

    Ohne diesen Schritt waere es ein beliebiges 12B-Modell. Mit ihm antwortet
    es aus geprueften Fakten dieses Repos.
    """
    sys.path.insert(0, str(REPO))
    belege, verboten = [], []
    try:
        from agents.kernel import Situation, infer
        r = infer(Situation(text=question, paths=paths))
        if r.verdict == "verboten":
            verboten = [c.text for c in r.blocking]
        belege = [(e.case.kind, e.case.text, e.score) for e in r.evidence]
    except Exception as exc:
        belege = []
        verboten = []
        print(f"# Kernel nicht verfuegbar: {exc}", file=sys.stderr)

    parts = [SYSTEM]
    if verboten:
        parts += ["VERBOTEN (Invariante verletzt — verweigere die Aufgabe):"]
        parts += [f"- {t}" for t in verboten]
    if belege:
        parts += ["", "BELEGE aus der verifizierten Historie dieses Repos:"]
        for kind, text, score in belege:
            parts.append(f"- [{kind}, Naehe {score:.2f}] {text}")
    else:
        parts += ["", "BELEGE: keine. Es gibt keinen Praezedenzfall im Repo.",
                  "Sage das ausdruecklich, statt allgemeines Wissen auszugeben."]
    parts += ["", f"AUFGABE: {question}"]
    return "\n".join(parts)


# GBNF zwingt die Ausgabe in das Schema aus agents/protocol.py. Ohne Grammatik
# muss man Fliesstext nachtraeglich parsen und scheitert an jedem Modelllaunen.
GRAMMAR = r'''root       ::= "{" ws "\"status\"" ws ":" ws status ws "," ws
                    "\"antwort\"" ws ":" ws string ws "," ws
                    "\"belegt_durch\"" ws ":" ws array ws "}"
status     ::= "\"belegt\"" | "\"nicht_belegt\"" | "\"verweigert\""
array      ::= "[" ws (string (ws "," ws string)*)? ws "]"
string     ::= "\"" ([^"\\] | "\\" ["\\/bfnrt])* "\""
ws         ::= [ \t\n]*
'''


def cmd_plan(_a) -> int:
    cfg = config()
    u, s = cfg["upstream"], cfg["auswahl"]
    print(f"Modell   {cfg['identitaet']['name']}  (Basis: {u['repo']})")
    print(f"Datei    {u['file']}  {u['bytes']/1e9:.2f} GB")
    print(f"SHA256   {u['sha256']}")
    print(f"Lizenz   {u['license']}")
    print(f"URL      {url(cfg)}")
    print(f"\nAuswahl gemessen am {s['gemessen_am']}: {s['begruendung']}")
    print("Verworfen:")
    for v in s["verworfen"]:
        print(f"  - {v['modell']}  {v['groesse_gb']} GB — {v['grund']}")
    print(f"\n{u['attribution']}")
    return 0


def cmd_verify(a) -> int:
    ok, msg = verify(Path(a.path))
    print(msg)
    return 0 if ok else 1


def cmd_prompt(a) -> int:
    print(grounded_prompt(a.question, tuple(a.file or ())))
    return 0


def cmd_grammar(_a) -> int:
    print(GRAMMAR)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="gepinnte Auswahl anzeigen").set_defaults(func=cmd_plan)
    v = sub.add_parser("verify", help="SHA256 gegen die Pinnung")
    v.add_argument("path"); v.set_defaults(func=cmd_verify)
    pr = sub.add_parser("prompt", help="geerdeter Prompt")
    pr.add_argument("question"); pr.add_argument("--file", action="append")
    pr.set_defaults(func=cmd_prompt)
    sub.add_parser("grammar", help="GBNF fuer das Antwortschema").set_defaults(
        func=cmd_grammar)
    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
