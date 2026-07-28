#!/usr/bin/env python3
"""hugin_clarity.py -- was ist unklar, welche Werte fehlen genau, was schliesst es.

Der Supervisor prueft die *Verfassung*: darf das so sein. Diese Datei prueft die
*Einsatzbereitschaft*: traegt das gerade, und wenn nicht, welcher konkrete Wert
fehlt und mit welchem Befehl kommt er hin.

## Warum ein Programm und keine Liste

Eine Liste offener Punkte in einer Markdown-Datei ist am Tag ihrer Entstehung
richtig und danach nie wieder. Genau das ist in diesem Repo schon passiert: die
Zeile "31 Dateien getrackt trotz .gitignore" stand noch in CLAUDE.md, als es
laengst 0 waren. Deshalb steht hier kein Zustand, sondern die Messung, die ihn
ermittelt — dasselbe Prinzip wie beim Supervisor und beim Ledger-Anker.

## Die drei Antworten

    OK       nachgerechnet und in Ordnung
    OFFEN    fehlt etwas Bestimmtes; `befehl` sagt genau was
    EXTERN   nicht von hier aus entscheidbar (Hardware, Konto, Master)

`EXTERN` ist kein Schoenreden von `OFFEN`. Es trennt "noch nicht getan" von
"kann von hier aus prinzipiell nicht getan werden" — wer beides vermischt,
bekommt eine Liste, die nie leer wird, und hoert auf hinzusehen.

## Begrenzt oder blockiert

Ein fehlendes lokales Modell **begrenzt** das System: T0 traegt, das Gateway
laeuft, Befehle und Belege funktionieren. Ein fehlendes Owner-Token
**blockiert** es: der Prozess startet absichtlich gar nicht erst.

Diese Unterscheidung fehlte zuerst, und der Schaden war sofort sichtbar — die
uebergebene Startzeile lautete

    python3 scripts/hugin_clarity.py --offen && cargo run -p hm-gateway

und startete das Gateway **nie**, weil ein nicht heruntergeladenes 6,6-GB-Modell
den Ausgang auf 1 setzte. Ein Vorschalt-Check, der den Start bei jeder
Unvollstaendigkeit verweigert, wird nach dem zweiten Mal umgangen — und damit
ist er schlechter als keiner.

    python3 scripts/hugin_clarity.py              # Bericht
    python3 scripts/hugin_clarity.py --offen      # nur, was noch fehlt
    python3 scripts/hugin_clarity.py --start      # Exit 1 nur bei echten Startsperren
    python3 scripts/hugin_clarity.py --json       # maschinenlesbar
"""

from __future__ import annotations

# Strukturiertes Logging (Plan B.3). Idempotent -- mehrfach
# aufgerufen waere ein No-Op, weil `_configure_once()` einen
# Flag abfragt, bevor sie Handler anhaengt.
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PARENT = _os.path.dirname(_HERE)
_SCRIPTS = _os.path.join(_PARENT, 'scripts')
if _SCRIPTS not in _sys.path:
    _sys.path.insert(0, _SCRIPTS)
from _log import get_logger
log = get_logger(__name__)

import argparse
import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OK, OFFEN, EXTERN = "OK", "OFFEN", "EXTERN"


@dataclass
class Punkt:
    id: str
    frage: str                  # was unklar war
    stand: str                  # OK | OFFEN | EXTERN
    gemessen: str               # der tatsaechliche Wert, nicht die Erwartung
    braucht: str = ""           # welcher Wert genau fehlt
    befehl: str = ""            # womit er hinkommt
    warum: str = ""             # was passiert, wenn es fehlt
    blockiert_start: bool = False   # verhindert den Betrieb, statt ihn zu begrenzen

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v}


def _run(*argv, cwd=REPO) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


def _tcp(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 1 — Die Antwortleiter: welche Stufe traegt wirklich
# ---------------------------------------------------------------------------

def p_stufen() -> list[Punkt]:
    """Jede Stufe einzeln. Eine Sammelmeldung 'System bereit' waere genau die
    Unschaerfe, die diese Datei beseitigen soll."""
    from agents import brain
    out = []
    for tier, ok, why in brain.tiers():
        if tier == brain.T0:
            out.append(Punkt("stufe-T0", "Antwortet das System ohne jedes Modell?",
                             OK if ok else OFFEN, why,
                             warum="T0 ist der Boden. Faellt er, gibt es keinen Zustand "
                                   "mehr, in dem ueberhaupt gearbeitet werden kann."))
        elif tier == brain.T1B:
            out.append(Punkt(
                "stufe-T1b", "Ist das lokale Modell einsatzbereit?",
                OK if ok else OFFEN, why,
                braucht="models/model.gguf (6,6 GB, SHA256 aus config/model.json) "
                        "und ein llama-cli-Binary",
                befehl="gh workflow run hugin-kern.yml -f frage='...'   "
                       "# holt und prueft beides auf Repo-Hardware",
                warum="Ohne T1b gibt es keine formulierte Antwort ohne fremde "
                      "Gegenstelle — nur Belege (T0) oder ein fremdes Konto (T1)."))
        elif tier == brain.T1:
            out.append(Punkt(
                "stufe-T1", "Ist ein keyloser Provider wirklich erreichbar?",
                OK if ok else OFFEN, why,
                braucht="ein laufender lokaler Dienst (Ollama auf 11434) ODER ein "
                        "gesetzter Provider-Key",
                befehl="ollama serve   # oder: export HUGIN_<PROVIDER>_KEY=...",
                warum="Diese Stufe wurde bis zur Messung als verfuegbar GEMELDET, "
                      "ohne es zu sein — Konfiguration als Zustand gelesen."))
        else:
            out.append(Punkt(
                "stufe-T2", "Duerfen kostenpflichtige Provider gerufen werden?",
                OK if not ok else OFFEN, why,
                braucht="nichts — zu sein ist hier der GEWOLLTE Zustand (0 EUR)",
                befehl="python3 -m agents budget unlock --reason \"...\" --yes   "
                       "# nur bewusst",
                warum="Offen bedeutet, dass ein Aufruf Geld kosten kann."))
    return out


# ---------------------------------------------------------------------------
# 2 — Der Kanal: erreicht der Chat den Port, und der Port das Gehirn
# ---------------------------------------------------------------------------

def p_kanal() -> list[Punkt]:
    out = []

    docker = (REPO / "Dockerfile").read_text(encoding="utf-8")
    hat_agents = "COPY agents/" in docker
    out.append(Punkt(
        "container-gehirn", "Funktioniert POST /chat auch im Container?",
        OK if hat_agents else OFFEN,
        "Dockerfile kopiert agents/" if hat_agents else "agents/ fehlt im Image",
        braucht="COPY agents/ /app/agents/ und ENV HM_BRAIN_REPO=/app",
        befehl="# in Dockerfile ergaenzen",
        warum="Ohne agents/ startet das Gateway normal und JEDER Chat-Aufruf "
              "antwortet 'brain not startable' — im Checkout gruen, im "
              "Betrieb tot."))

    main_rs = (REPO / "crates/hm-gateway/src/main.rs").read_text(encoding="utf-8")
    cors_verdrahtet = "apply_cors" in main_rs and "parse_header(&header_text, \"origin\")" in main_rs
    out.append(Punkt(
        "cors-verdrahtet", "Wirkt die Origin-Allowlist ueberhaupt?",
        OK if cors_verdrahtet else OFFEN,
        "Origin wird gelesen und angewandt" if cors_verdrahtet
        else "Origin-Header wird nirgends gelesen — nur '*' wirkt",
        braucht="Origin am HttpRequest + apply_cors auf der fertigen Antwort",
        warum="Sonst ist die einzige funktionierende Einstellung die "
              "unsicherste, und eine gesetzte Allowlist tut still nichts."))

    origins = os.environ.get("HM_ALLOWED_ORIGINS", "").strip()
    out.append(Punkt(
        "cors-gesetzt", "Darf die PWA den Kern im Browser aufrufen?",
        OK if origins else EXTERN,
        f"HM_ALLOWED_ORIGINS={origins!r}" if origins else "HM_ALLOWED_ORIGINS nicht gesetzt",
        braucht="die Origin, von der HUGIN geladen wird — fuer GitHub Pages: "
                "https://benholl94-cmyk.github.io",
        befehl='export HM_ALLOWED_ORIGINS="https://benholl94-cmyk.github.io"',
        warum="Ohne sie blockiert der Browser die Antwort, obwohl das Gateway "
              "korrekt geantwortet hat — der Fehler sieht aus wie ein "
              "Netzproblem und ist keines. curl bleibt davon unberuehrt."))

    token = os.environ.get("HM_OWNER_TOKEN", "")
    out.append(Punkt(
        "owner-token", "Kann das Gateway ueberhaupt starten?",
        OK if token else EXTERN,
        "HM_OWNER_TOKEN gesetzt" if token else "HM_OWNER_TOKEN fehlt",
        braucht="ein Owner-Token; der Keyring erzeugt es selbst",
        blockiert_start=not token,
        befehl='eval "$(python3 scripts/hugin_keyring.py env)"',
        warum="Das Gateway startet ohne Token absichtlich NICHT (fail-closed). "
              "Das ist kein Fehler, sondern die Sperre."))
    return out


# ---------------------------------------------------------------------------
# 3 — Fluechtiger Zustand: was den Container nicht ueberlebt
# ---------------------------------------------------------------------------

def p_fluechtig() -> list[Punkt]:
    out = []
    seed = Path.home() / ".hugin" / "master.seed"
    out.append(Punkt(
        "seed-sicherung", "Ueberlebt der Master-Seed diesen Container?",
        EXTERN,
        f"{seed} {'vorhanden' if seed.is_file() else 'fehlt'} — liegt ausserhalb "
        "des Repos und wird beim Container-Ende geloescht",
        braucht="eine Kopie des Seeds auf einem Geraet des Masters",
        befehl="python3 scripts/hugin_keyring.py export   "
               "# Ausgabe sicher auf dem eigenen Geraet ablegen, NIE committen",
        warum="Aus dem Seed leiten sich alle 6 selbst ausstellbaren Schluessel ab. "
              "Ist er weg, sind alle weg — und jeder Dienst, der einen davon "
              "kennt, muss neu eingerichtet werden."))

    r = _run("git", "rev-list", "origin/HEAD..HEAD", "--count")
    n = int(r.stdout.strip() or 0) if r.returncode == 0 else 0
    out.append(Punkt(
        "ungepusht", "Ist die Arbeit dauerhaft?",
        OK if n == 0 else OFFEN,
        f"{n} Commit(s) lokal, nicht auf dem Remote" if n else "alles gepusht",
        braucht=("ein entscheidender Commit-Push (manuell oder durch "
                 "munin_continuity seal --push), damit die Commits nicht "
                 "nur in diesem Container existieren") if n else "",
        befehl="python3 scripts/munin_continuity.py seal --push",
        warum="Ungepusht heisst nicht vorhanden — so ging 29b701c verloren."))
    return out


# ---------------------------------------------------------------------------
# 4 — Behauptete, nie ausgefuehrte Pfade
# ---------------------------------------------------------------------------

# Jeder Eintrag: (id, Frage, was zum Beweis fehlt, Warum es hier nicht geht)
UNGEPRUEFT = (
    ("kanaele-live",
     "Wurde je eine Nachricht ueber Telegram/WhatsApp/Discord/Slack gesendet?",
     "echte Bot-Zugangsdaten der jeweiligen Plattform",
     "Der Transportcode ist vorhanden und getestet; 'hat Transportcode' und "
     "'nachweislich zugestellt' sind verschiedene Behauptungen."),
    ("llm-chat-live",
     "Wurde plugins/llm_chat_plugin.py je gegen eine echte LLM-API gefuehrt?",
     "HM_LLM_API_URL/-KEY/-MODEL eines echten Anbieters",
     "Bisher nur gegen einen hermetischen lokalen Mock."),
    ("t1b-live",
     "Hat der HUGIN-Kern je eine Antwort erzeugt?",
     "ein Lauf von .github/workflows/hugin-kern.yml",
     "Die 6,6-GB-Datei wurde in dieser Umgebung nie geholt; gepinnt ist sie, "
     "geprueft wurde bisher nur die Pinnung."),
    ("compose-platzhalter",
     "Was startet deploy/fullstack-compose.yml unter dem Namen 'gateway'?",
     "nichts — die Antwort ist bekannt und unangenehm",
     "Bis 2026-07-28 lief dort ein stdlib-Platzhalter `deploy/gateway_service.py`; "
     "seit Wave 1 baut das compose das echte Rust-Gateway aus dem root "
     "`Dockerfile`. Wenn dieser Befund noch 'platzhalter' anzeigt, ist die "
     "Aenderung nicht durch."),
)


def p_ungeprueft() -> list[Punkt]:
    return [Punkt(i, frage, EXTERN, "nie ausgefuehrt", braucht=braucht, warum=warum)
            for i, frage, braucht, warum in UNGEPRUEFT]


# ---------------------------------------------------------------------------
# 5 — Bekannte Luecken im Code selbst
# ---------------------------------------------------------------------------

def p_code() -> list[Punkt]:
    out = []
    plugins = REPO / "crates/hm-plugins/src"
    hat_tests = any("#[test]" in f.read_text(encoding="utf-8", errors="ignore")
                    for f in plugins.rglob("*.rs")) if plugins.is_dir() else False
    out.append(Punkt(
        "hm-plugins-tests", "Ist das Plugin-Protokoll getestet?",
        OK if hat_tests else OFFEN,
        "Tests vorhanden" if hat_tests else "kein einziger #[test] in hm-plugins",
        braucht="Tests fuer Zeilenprotokoll, Timeout und Fehlerpfad",
        warum="Es ist echter Protokollcode, den jeder Task durchlaeuft — "
              "ungetestet faellt ein Formatfehler erst im Betrieb auf."))

    rb = REPO / ".github/workflows/auto-rollback.yml"
    ctx = REPO / "scripts/auto_rollback_ctx.py"
    vorhanden = rb.is_file() or ctx.is_file()
    hold_ok = False
    if ctx.is_file():
        t = ctx.read_text(encoding="utf-8")
        hold_ok = "unknown" in t and "HOLD" in t
    out.append(Punkt(
        "rollback-unknown", "Behandelt das Auto-Rollback ein unbekanntes "
                            "Vorgaenger-Ergebnis als HOLD?",
        OK if (vorhanden and hold_ok) else (OFFEN if vorhanden else EXTERN),
        ("unknown -> HOLD verdrahtet" if hold_ok else
         "unknown wird nicht als HOLD behandelt") if vorhanden
        else "Workflow derzeit nicht in main (hat sich selbst entfernt)",
        braucht="unknown muss HOLD ergeben, und der Test muss eine Richtung "
                "festlegen statt 'REVERT oder HOLD' zu behaupten",
        warum="Auf diesem Repo sind Vorgaengercommits meist [skip ci], also "
              "'unknown'. Als 'nicht failure' gelesen war die Sperre faktisch "
              "abgeschaltet — der Workflow nahm daraufhin seinen eigenen Merge "
              "zurueck."))
    return out


GRUPPEN = (
    ("Antwortleiter — welche Stufe traegt", p_stufen),
    ("Kanal — Chat, Port, Gehirn", p_kanal),
    ("Fluechtig — was den Container nicht ueberlebt", p_fluechtig),
    ("Nie ausgefuehrt — ehrlich benannt statt behauptet", p_ungeprueft),
    ("Code — bekannte Luecken", p_code),
)


def sammle() -> list[tuple[str, list[Punkt]]]:
    out = []
    for titel, fn in GRUPPEN:
        try:
            out.append((titel, fn()))
        except Exception as exc:
            out.append((titel, [Punkt(
                "messung-gescheitert", titel, OFFEN, f"Messung warf {exc!r}",
                warum="Eine gescheiterte Messung ist nicht 'in Ordnung'. Sie "
                      "wird als offen gemeldet, nicht verschluckt.")]))
    return out


MARKE = {OK: "[OK    ]", OFFEN: "[OFFEN ]", EXTERN: "[EXTERN]"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--offen", action="store_true", help="nur OFFEN und EXTERN")
    p.add_argument("--start", action="store_true",
                   help="Exit 1 nur, wenn etwas den Betrieb wirklich verhindert")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    gruppen = sammle()
    if a.json:
        print(json.dumps([{"gruppe": t, "punkte": [x.to_dict() for x in ps]}
                          for t, ps in gruppen], ensure_ascii=False, indent=2))
        return 0

    blocker = [x for _, ps in gruppen for x in ps if x.blockiert_start]
    if a.start:
        if not blocker:
            print("Startfrei: nichts verhindert den Betrieb.")
            print("Was fehlt, begrenzt nur die Faehigkeit — "
                  "`--offen` zeigt es.")
            return 0
        for x in blocker:
            print(f"STARTSPERRE  {x.id}: {x.gemessen}")
            print(f"             {x.befehl}")
        return 1

    zahl = {OK: 0, OFFEN: 0, EXTERN: 0}
    for titel, punkte in gruppen:
        sichtbar = [x for x in punkte if not (a.offen and x.stand == OK)]
        for x in punkte:
            zahl[x.stand] = zahl.get(x.stand, 0) + 1
        if not sichtbar:
            continue
        print(f"\n── {titel}")
        for x in sichtbar:
            print(f"  {MARKE[x.stand]} {x.id}")
            print(f"           {x.frage}")
            print(f"           gemessen: {x.gemessen}")
            if x.braucht:
                print(f"           braucht:  {x.braucht}")
            if x.befehl:
                print(f"           befehl:   {x.befehl}")
            if x.warum:
                print(f"           warum:    {x.warum}")

    print(f"\n{zahl[OK]} in Ordnung · {zahl[OFFEN]} offen · "
          f"{zahl[EXTERN]} extern (Master, Hardware oder Konto)")
    # Exit 1 nur bei OFFEN: EXTERN ist kein Versaeumnis dieses Laufs, und ein
    # Ausgang, der immer 1 ist, wird ignoriert.
    return 1 if zahl[OFFEN] else 0


if __name__ == "__main__":
    raise SystemExit(main())
