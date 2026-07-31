#!/usr/bin/env python3
"""codeam_cli.py -- die repo-interne Seite des CodeAgent-Mobile-Deploys.

## Was hier wozu gehoert

`codeam-cli` (npm, 2.61.76) ist das Werkzeug **der Gegenseite**: `codeam deploy`
legt einen GitHub-Codespace fuer ein Repo an, installiert Claude Code und
`codeam-cli` darin, haelt die Sitzung mit PM2 am Leben und paart das Telefon.
Es weiss nichts ueber das Repo, das es deployt — und muss es auch nicht.

Diese Datei ist das Gegenstueck **in** diesem Repo: sie macht dieses Projekt
in einem frisch gebooteten Codespace ohne eine einzige Rueckfrage
einsatzbereit. Sie ersetzt `codeam-cli` nicht und spricht auch nicht mit
dessen Backend — sie stellt sicher, dass der Agent, den die App startet, eine
laufende Umgebung vorfindet statt einer leeren.

## Der Fehler, der das noetig machte

`.devcontainer/dev-container.json` — mit Bindestrich. Die Devcontainer-
Spezifikation kennt genau drei Pfade: `.devcontainer/devcontainer.json`,
`.devcontainer.json`, `.devcontainer/<ordner>/devcontainer.json`. Ein
abweichender Name erzeugt **keinen Fehler**, sondern wird stillschweigend
ignoriert: der Codespace bootet dann das Standardimage, ohne Rust, ohne
gepinntes Python, ohne Portweiterleitung, ohne postCreate. Die Konfiguration
war vollstaendig, wohlgeformt und wirkungslos — dieselbe Fehlerklasse wie der
`apple-touch-icon` als SVG und die nie gelesene CORS-Allowlist.

## Warum stdlib und Python

Der Codespace hat Python, bevor er irgendetwas anderes hat. Ein Werkzeug, das
erst `npm install` oder einen Cargo-Build braucht, um zu sagen *was zu tun
ist*, kommt zu spaet.

## Die Grenze

`prepare` tut nur Deterministisches: Schluessel ausstellen (beide Enden
gehoeren dem Projekt), bauen, pruefen. Es fragt nichts, raet nichts und ruft
keinen kostenpflichtigen Dienst. Was eine Entscheidung verlangt, wird
gemeldet — dieselbe Linie wie `hugin_selfheal.py`.

    python3 scripts/codeam_cli.py describe        # was die App wissen muss
    python3 scripts/codeam_cli.py prepare --yes   # einrichten, ohne Rueckfrage
    python3 scripts/codeam_cli.py verify          # traegt es?
    python3 scripts/codeam_cli.py up              # Gateway starten
    python3 scripts/codeam_cli.py doctor          # was fehlt und womit es kommt
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KONFIG = REPO / "config" / "codeam.json"

OK, FEHLT, EXTERN = "ok", "fehlt", "extern"


def konfig() -> dict:
    if not KONFIG.is_file():
        raise SystemExit(f"Fehlt: {KONFIG.relative_to(REPO)}")
    return json.loads(KONFIG.read_text(encoding="utf-8"))


def _run(*argv, timeout: int = 900, cwd: Path | None = None,
         env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd or REPO, capture_output=True,
                          text=True, timeout=timeout, env=env)


def eigene_umgebung() -> dict:
    """Umgebung samt der Schluessel, die das Projekt selbst ausstellt.

    Fruehere Fassung: `verify` las `HM_OWNER_TOKEN` aus der aufrufenden Shell
    und meldete `HTTP 401`, waehrend derselbe Dienst laut `up` einwandfrei
    lief — der Unterschied war nur, dass `up` den Token aus dem Keyring
    nachzog und `verify` nicht. Damit haette die App eine gesunde Umgebung
    als kaputt gemeldet, und die Loesung waere gewesen: "der Mensch exportiert
    eine Variable". Genau diese Abhaengigkeit soll hier nicht existieren.

    Der Owner-Token ist einer der sechs Schluessel, die dieses Projekt selbst
    ausstellt — beide Enden gehoeren ihm. Ihn aus dem eigenen Keyring zu
    holen ist kein Umgehen der fail-closed-Sperre: die gilt Fremden.
    """
    umgebung = dict(os.environ)
    if umgebung.get("HM_OWNER_TOKEN"):
        return umgebung
    r = _run(sys.executable, "scripts/hugin_keyring.py", "env", timeout=60)
    for zeile in (r.stdout or "").splitlines():
        if zeile.startswith("export ") and "=" in zeile:
            name, _, wert = zeile[len("export "):].partition("=")
            umgebung.setdefault(name.strip(), wert.strip())
    return umgebung


def _tcp(host: str, port: int, timeout: float = 0.5) -> bool:
    """Ein Handshake. Ob ein Dienst laeuft, ist keine Frage der Konfiguration."""
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# describe — was die App wissen muss, ohne zu fragen
# ---------------------------------------------------------------------------

def describe() -> dict:
    """Der vollstaendige Vertrag als eine JSON-Antwort.

    Bewusst statisch aus `config/codeam.json` plus wenigen gemessenen Werten:
    die App soll das lesen koennen, BEVOR irgendetwas laeuft. Ein Manifest,
    das erst nach dem Start verfuegbar ist, hilft beim Starten nicht.
    """
    k = konfig()
    port = k["dienst"]["port"]
    return {
        "schema": k["schema"],
        "projekt": k["projekt"],
        "dienst": k["dienst"],
        "befehle": k["befehle"]["vorschlaege"],
        "einrichtung": k["einrichtung"],
        "grenzen": k["grenzen"],
        "gemessen": {
            "laeuft_bereits": _tcp("127.0.0.1", port),
            "token_ableitbar": bool(eigene_umgebung().get(k["dienst"]["auth"]["env"], "")),
            "binary_gebaut": (REPO / "target" / "release" / "hm-gateway").is_file()
            or (REPO / "target" / "debug" / "hm-gateway").is_file(),
        },
    }


# ---------------------------------------------------------------------------
# prepare — deterministisch, ohne Rueckfrage
# ---------------------------------------------------------------------------

@dataclass
class Schritt:
    id: str
    stand: str
    detail: str = ""
    befehl: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v}


def s_werkzeuge() -> Schritt:
    fehlend = [w for w in ("python3", "cargo") if shutil.which(w) is None]
    if fehlend:
        return Schritt("werkzeuge", FEHLT, f"nicht im PATH: {', '.join(fehlend)}",
                       "Devcontainer-Feature rust/python — siehe .devcontainer/devcontainer.json")
    return Schritt("werkzeuge", OK, "python3 und cargo vorhanden")


def s_schluessel(apply: bool) -> Schritt:
    """Das Projekt stellt seinen eigenen Owner-Token aus.

    Beide Enden gehoeren dem Projekt, also ist ein frisch erzeugter Wert
    gueltig — niemand muss den alten kennen. Genau deshalb braucht dieser
    Schritt weder ein Backup noch den Master.
    """
    seed = Path.home() / ".hugin" / "master.seed"
    if seed.is_file():
        return Schritt("schluessel", OK, "Seed vorhanden, Token ableitbar")
    if not apply:
        return Schritt("schluessel", FEHLT, "Seed fehlt (dry-run: nichts erzeugt)",
                       "python3 scripts/hugin_keyring.py init")
    r = _run(sys.executable, "scripts/hugin_keyring.py", "init", timeout=120)
    if r.returncode != 0 or not seed.is_file():
        return Schritt("schluessel", FEHLT,
                       (r.stderr or r.stdout).strip()[:200] or "init lieferte keinen Seed",
                       "python3 scripts/hugin_keyring.py init")
    return Schritt("schluessel", OK, "Seed erzeugt")


def s_bauen(apply: bool) -> Schritt:
    ziel = REPO / "target" / "release" / "hm-gateway"
    if ziel.is_file():
        return Schritt("bauen", OK, "hm-gateway (release) vorhanden")
    if not apply:
        return Schritt("bauen", FEHLT, "Binary fehlt (dry-run: nicht gebaut)",
                       "cargo build --release -p hm-gateway")
    r = _run("cargo", "build", "--release", "-p", "hm-gateway", timeout=1800)
    if r.returncode != 0 or not ziel.is_file():
        return Schritt("bauen", FEHLT, (r.stderr or "").strip().splitlines()[-1][:200]
                       if r.stderr.strip() else "Build ohne Binary",
                       "cargo build --release -p hm-gateway")
    return Schritt("bauen", OK, "hm-gateway gebaut")


def s_selbsterhalt(apply: bool) -> Schritt:
    """Die vorhandene Reparaturschleife mitlaufen lassen statt sie zu kopieren.

    Zwei Stellen, die dasselbe reparieren, driften auseinander.
    """
    skript = REPO / "scripts" / "hugin_selfheal.py"
    if not skript.is_file():
        return Schritt("selbsterhalt", EXTERN, "hugin_selfheal.py fehlt")
    if not apply:
        # Der Selbsterhalt-Lauf fuehrt die gesamte Testsuite aus (~20 s). Ihn
        # im Trockenlauf zu starten waere kein Trockenlauf, sondern ein
        # Vollaudit -- und aus pytest heraus eine Schachtelung, die pro
        # Aufruf ueber eine Minute kostet. Ein Trockenlauf sagt, was
        # geschehen WUERDE.
        return Schritt("selbsterhalt", OK, "wuerde laufen (dry-run: nicht gestartet)",
                       "python3 scripts/hugin_selfheal.py --apply")
    r = _run(sys.executable, str(skript), "--apply", timeout=900)
    letzte = [z for z in (r.stdout or "").splitlines() if z.startswith("[")]
    repariert = sum(1 for z in letzte if "REPARIERT" in z)
    return Schritt("selbsterhalt", OK if r.returncode == 0 else FEHLT,
                   f"{repariert} Reparatur(en), Ausgang {r.returncode}")


def prepare(apply: bool) -> list[Schritt]:
    return [s_werkzeuge(), s_schluessel(apply), s_bauen(apply), s_selbsterhalt(apply)]


# ---------------------------------------------------------------------------
# verify — traegt es wirklich
# ---------------------------------------------------------------------------

def verify() -> list[Schritt]:
    """Nicht 'ist eingerichtet', sondern 'antwortet'.

    `hugin_clarity.py --start` beantwortet genau eine Frage: verhindert etwas
    den Betrieb. Was den Betrieb nur *begrenzt* (fehlendes lokales Modell)
    darf hier nicht rot faerben — ein Vorschalt-Check, der bei jeder
    Unvollstaendigkeit scheitert, wird beim zweiten Mal umgangen.
    """
    out = []
    umgebung = eigene_umgebung()
    clarity = REPO / "scripts" / "hugin_clarity.py"
    if clarity.is_file():
        r = _run(sys.executable, str(clarity), "--start", timeout=300, env=umgebung)
        out.append(Schritt("startfrei", OK if r.returncode == 0 else FEHLT,
                           (r.stdout or "").strip().splitlines()[0][:160]
                           if r.stdout.strip() else "",
                           'eval "$(python3 scripts/hugin_keyring.py env)"'))
    k = konfig()
    port = k["dienst"]["port"]
    laeuft = _tcp("127.0.0.1", port)
    out.append(Schritt("dienst", OK if laeuft else FEHLT,
                       f"Port {port} {'antwortet' if laeuft else 'still'}",
                       "" if laeuft else "python3 scripts/codeam_cli.py up"))
    if laeuft:
        out.append(_health(k, umgebung))
    return out


def _health(k: dict, umgebung: dict | None = None) -> Schritt:
    """Ein echter HTTP-Aufruf gegen /health, mit Token.

    Ein offener Port beweist, dass etwas lauscht — nicht, dass es dieses
    Gateway ist.
    """
    import urllib.error
    import urllib.request
    port = k["dienst"]["port"]
    token = (umgebung or eigene_umgebung()).get(k["dienst"]["auth"]["env"], "")
    pfad = k["dienst"]["health"]["pfad"]
    req = urllib.request.Request(f"http://127.0.0.1:{port}{pfad}",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            koerper = json.loads(r.read().decode("utf-8", "replace") or "{}")
            return Schritt("health", OK, f"{r.status} status={koerper.get('status', '?')}")
    except urllib.error.HTTPError as e:
        return Schritt("health", FEHLT, f"HTTP {e.code}",
                       'eval "$(python3 scripts/hugin_keyring.py env)"' if e.code == 401 else "")
    except Exception as e:
        return Schritt("health", FEHLT, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# up — Gateway starten
# ---------------------------------------------------------------------------

def up(wartezeit: int = 30) -> int:
    """Startet den Dienst und wartet, bis er wirklich antwortet.

    Ein `Popen` und ein sofortiges "gestartet" waeren eine Behauptung. Der
    Prozess kann in derselben Sekunde am fehlenden Token sterben — genau das
    ist der vorgesehene fail-closed-Fall.
    """
    k = konfig()
    port = k["dienst"]["port"]
    if _tcp("127.0.0.1", port):
        print(f"laeuft bereits auf Port {port}")
        return 0

    umgebung = eigene_umgebung()
    umgebung.setdefault("HM_GATEWAY_BIND", k["dienst"]["bind_default"])
    umgebung.setdefault("HM_BRAIN_REPO", str(REPO))

    binaer = REPO / "target" / "release" / "hm-gateway"
    argv = [str(binaer)] if binaer.is_file() else ["cargo", "run", "--release", "-p", "hm-gateway"]

    protokoll = REPO / "status" / "codeam-gateway.log"
    protokoll.parent.mkdir(parents=True, exist_ok=True)
    with protokoll.open("ab") as fh:
        proc = subprocess.Popen(argv, cwd=REPO, env=umgebung, stdout=fh,
                                stderr=subprocess.STDOUT, start_new_session=True)

    for _ in range(wartezeit * 2):
        if _tcp("127.0.0.1", port):
            print(f"laeuft auf Port {port} (pid {proc.pid}), Protokoll: "
                  f"{protokoll.relative_to(REPO)}")
            return 0
        if proc.poll() is not None:
            schwanz = protokoll.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
            print(f"beendet mit {proc.returncode}:\n  " + "\n  ".join(schwanz),
                  file=sys.stderr)
            return 1
        time.sleep(0.5)
    print(f"antwortet nach {wartezeit}s nicht — Protokoll: "
          f"{protokoll.relative_to(REPO)}", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

MARKE = {OK: "[ok    ]", FEHLT: "[FEHLT ]", EXTERN: "[extern]"}


def _drucken(schritte: list[Schritt]) -> int:
    for s in schritte:
        print(f"{MARKE[s.stand]} {s.id:<14} {s.detail}")
        if s.befehl and s.stand == FEHLT:
            print(f"          → {s.befehl}")
    return 1 if any(s.stand == FEHLT for s in schritte) else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("describe", help="Vertrag als JSON — was die App wissen muss")
    pr = sub.add_parser("prepare", help="einrichten, ohne Rueckfrage")
    pr.add_argument("--yes", action="store_true",
                    help="wirklich ausfuehren (ohne: Trockenlauf)")
    v = sub.add_parser("verify", help="traegt es gerade")
    u = sub.add_parser("up", help="Gateway starten und auf Antwort warten")
    u.add_argument("--wait", type=int, default=30)
    doc = sub.add_parser("doctor", help="alles auf einmal, maschinenlesbar")
    # `--json` gehoert an JEDEN Unterbefehl, nicht an den Hauptparser: mit
    # argparse muessen Hauptparser-Flags VOR dem Unterbefehl stehen, also
    # scheiterte `codeam_cli.py describe --json` mit leerem stdout. Genau so
    # ruft eine App es aber auf.
    for unter in (d, pr, v, doc):
        unter.add_argument("--json", action="store_true", help="maschinenlesbar")

    a = p.parse_args(argv)

    if a.cmd == "describe":
        # describe ist immer JSON -- das Flag ist erlaubt und wirkungsgleich,
        # damit ein Aufrufer nicht wissen muss, welcher Befehl es braucht.
        print(json.dumps(describe(), ensure_ascii=False, indent=2))
        return 0

    if a.cmd == "prepare":
        schritte = prepare(a.yes)
        if a.json:
            print(json.dumps([s.to_dict() for s in schritte], ensure_ascii=False, indent=2))
            return 1 if any(s.stand == FEHLT for s in schritte) else 0
        if not a.yes:
            print("Trockenlauf — nichts geaendert. Mit --yes ausfuehren.\n")
        return _drucken(schritte)

    if a.cmd == "verify":
        schritte = verify()
        if a.json:
            print(json.dumps([s.to_dict() for s in schritte], ensure_ascii=False, indent=2))
            return 1 if any(s.stand == FEHLT for s in schritte) else 0
        return _drucken(schritte)

    if a.cmd == "up":
        return up(a.wait)

    # doctor: Vertrag + Zustand in einer Antwort, fuer die App gedacht
    bericht = {"describe": describe(),
               "verify": [s.to_dict() for s in verify()]}
    print(json.dumps(bericht, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
