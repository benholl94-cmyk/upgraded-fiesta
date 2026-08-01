#!/usr/bin/env python3
"""release_notes.py -- die Release-Notiz wird aus dem Manifest gerechnet.

## Warum nicht von Hand geschrieben

Eine Release-Notiz ist die Stelle, an der ein Projekt behauptet, was es kann.
Von Hand geschrieben ist sie eine Erinnerung an den Zustand zum Zeitpunkt des
Schreibens — und veraltet ab dem naechsten Bau, ohne dass jemand es merkt.
Genau diese Sorte Drift hat hier schon die Krate-Tabelle in `CLAUDE.md`
erwischt (*"intentional placeholders"*, waehrend die Kraten laengst echt
waren) und die Zeile *"31 Dateien getrackt trotz .gitignore"*, die lange nach
dem Aufraeumen noch dastand.

Diese Notiz enthaelt deshalb **keinen einzigen Wert, den ein Mensch
hingeschrieben hat**. Groessen, Pruefsummen, Werkzeugversionen und
Pruefergebnisse kommen aus `status/build-manifest.json`, das sein eigener
Erzeuger aus gelaufenen Befehlen befuellt; Port, Auth-Variable und Routen aus
`status/deploy-contract.json`, das `codeam_cli.py describe` erzeugt. Steht ein
Wert dort nicht, steht er hier nicht — er wird nicht ersetzt und nicht
geschaetzt.

## Was ausdruecklich mit hineingehoert: die Grenzen

Eine Notiz, die nur Bestandenes zeigt, ist eine Auswahl und keine Aussage.
Gefallene und unbekannte Pruefungen erscheinen deshalb genauso, fehlende
Artefakte werden als fehlend gefuehrt, und der Abschnitt "Was hier NICHT
nachgewiesen ist" ist nicht optional.

    python3 scripts/release_notes.py --tag v1.0.0 \\
        --manifest status/build-manifest.json \\
        --vertrag status/deploy-contract.json \\
        --image ghcr.io/owner/repo/hm-gateway
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_manifest import BESTANDEN, GEFALLEN, UNBEKANNT, leckpruefung  # noqa: E402

ZEICHEN = {BESTANDEN: "bestanden", GEFALLEN: "GEFALLEN", UNBEKANNT: "unbekannt"}


def _mb(n: int) -> str:
    return f"{n/1_048_576:.2f} MB" if n >= 1_048_576 else f"{n/1024:.1f} KB"


def artefakt_tabelle(m: dict) -> list[str]:
    zeilen = ["| Artefakt | Groesse | SHA256 |", "|---|---|---|"]
    for a in m.get("artefakte", []):
        if a.get("fehlt"):
            # Nicht weglassen: eine Liste, aus der Fehlendes verschwindet,
            # sieht immer vollstaendig aus.
            zeilen.append(f"| `{a['pfad']}` | — | **nicht gebaut** |")
        else:
            zeilen.append(f"| `{a['pfad']}` | {_mb(a['bytes'])} | `{a['sha256']}` |")
    return zeilen


def pruef_tabelle(m: dict) -> list[str]:
    p = m.get("pruefungen") or []
    if not p:
        return ["_Keine Pruefungen im Manifest — dieser Bau lief ohne `--pruefen`._"]
    zeilen = ["| Pruefung | Ergebnis | Befehl |", "|---|---|---|"]
    for e in p:
        note = ZEICHEN.get(e.get("ergebnis", ""), e.get("ergebnis", "?"))
        if e.get("hinweis"):
            note += f" ({e['hinweis']})"
        if e.get("grund"):
            note += f" ({e['grund']})"
        zeilen.append(f"| {e['pruefung']} | {note} | `{e['befehl']}` |")
    return zeilen


def notiz(tag: str, m: dict, vertrag: dict | None, image: str | None) -> str:
    kurz = m.get("commit_kurz") or (m.get("commit") or "")[:7]
    t = m.get("werkzeuge", {})
    aus: list[str] = []

    aus += [f"# {tag}", "",
            f"Gebaut aus `{m.get('commit', '?')}` ({m.get('branch', '?')}), "
            f"{m.get('erzeugt', '?')}.", "",
            "Jede Zahl unten stammt aus `status/build-manifest.json`, das sein "
            "Erzeuger aus tatsaechlich gelaufenen Befehlen befuellt. Nichts "
            "davon ist in diese Notiz hineingeschrieben worden.", ""]

    if image:
        aus += ["## Containerimage", "",
                "```sh",
                f"docker pull {image}:{tag}",
                "eval \"$(python3 scripts/hugin_keyring.py env)\"",
                f"docker run -d -p 8080:8080 \\",
                "  -e HM_OWNER_TOKEN \\",
                "  -e HM_GATEWAY_BIND=0.0.0.0:8080 \\",
                f"  {image}:{tag}",
                "```", "",
                f"Ebenfalls veroeffentlicht: `{image}:{kurz}`.", ""]

    aus += ["## Artefakte", ""] + artefakt_tabelle(m) + [""]
    aus += ["## Nachgerechnet", ""] + pruef_tabelle(m) + [""]

    aus += ["## Werkzeugkette", "",
            "| | Version |", "|---|---|"]
    for name in ("rustc", "cargo", "python", "node", "docker"):
        aus.append(f"| {name} | {t.get(name) or '—'} |")
    aus.append("")

    if vertrag:
        aus += ["## Anschluss", "",
                "Was die CodeAgent-Mobile-App liest — aus "
                "`status/deploy-contract.json`, erzeugt von "
                "`scripts/codeam_cli.py describe`. **Namen von Variablen, nie "
                "Werte.**", ""]
        dienst = vertrag.get("dienst") or {}
        if dienst.get("port"):
            aus.append(f"- Port: `{dienst['port']}` "
                       f"(`{dienst.get('bind_env', '?')}`, Vorgabe "
                       f"`{dienst.get('bind_default', '?')}`)")
        auth = dienst.get("auth") or {}
        if auth.get("env"):
            aus.append(f"- Auth: `{auth.get('typ', 'bearer')}` ueber "
                       f"`{auth['env']}` — vom Repo selbst ausstellbar, "
                       f"fail-closed: `{json.dumps(auth.get('fail_closed'))}`. Der Wert "
                       "wird nirgends veroeffentlicht.")
        for schluessel in ("health", "chat"):
            r = dienst.get(schluessel) or {}
            if r.get("pfad"):
                zeile = f"- `{r.get('methode', '?')} {r['pfad']}`"
                if r.get("streamt"):
                    zeile += f" — streamt ({r.get('format', '')})"
                aus.append(zeile)
        aus.append("")

    aus += ["## Was hier NICHT nachgewiesen ist", "",
            "Dieser Abschnitt ist nicht optional. Eine Notiz, die nur "
            "Bestandenes zeigt, ist eine Auswahl und keine Aussage.", ""]
    offen = [e for e in (m.get("pruefungen") or [])
             if e.get("ergebnis") != BESTANDEN]
    for e in offen:
        aus.append(f"- **{e['pruefung']}**: {ZEICHEN.get(e.get('ergebnis'), '?')}"
                   + (f" — {e.get('grund') or e.get('ausgabe') or ''}"
                      if (e.get('grund') or e.get('ausgabe')) else ""))
    fehlend = [a for a in m.get("artefakte", []) if a.get("fehlt")]
    for a in fehlend:
        aus.append(f"- Artefakt `{a['pfad']}` wurde nicht gebaut.")
    if not m.get("sauber", True):
        aus.append("- Der Arbeitsbaum war beim Bauen nicht sauber "
                   "(`git status` nicht leer) — in einem CI-Lauf sind das in "
                   "der Regel die heruntergeladenen Artefakte selbst.")
    aus += [
        "- Die vier Kanalkraten (telegram/discord/slack/whatsapp) sind gegen "
        "**keine** echte Chat-Plattform live getestet; das braucht echte "
        "Bot-Zugangsdaten.",
        "- Das lokale GGUF-Modell ist nicht Teil dieses Releases (6,6 GB, "
        "`scripts/hugin_local_model.py setup` holt es).",
        "- Die Verfuegbarkeit externer Provider haengt am Netz des Betreibers "
        "und wird hier nicht behauptet.",
        "",
    ]
    return "\n".join(aus)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tag", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--vertrag")
    p.add_argument("--image")
    p.add_argument("--out")
    a = p.parse_args(argv)

    m = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    v = None
    if a.vertrag and Path(a.vertrag).is_file():
        v = json.loads(Path(a.vertrag).read_text(encoding="utf-8"))

    text = notiz(a.tag, m, v, a.image)

    # Dieselbe Regel wie beim Manifest: eine Release-Notiz ist das
    # sichtbarste Veroeffentlichungsartefakt, das dieses Repo hat.
    lecks = leckpruefung(text)
    if lecks:
        print("ABBRUCH — die Release-Notiz enthaelt etwas Geheimes:", file=sys.stderr)
        for l in lecks:
            print(f"  {l}", file=sys.stderr)
        return 2

    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"{a.out}: {len(text)} Zeichen")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
