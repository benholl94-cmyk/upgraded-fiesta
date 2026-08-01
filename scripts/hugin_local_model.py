#!/usr/bin/env python3
"""Der lokale Modellkern: holen, bauen, starten, messen — ohne Rückfragen.

Bis hierher war `T1b` eine Zeile in einem Bericht: *„models/model.gguf fehlt
(6,6 GB)"*. Die Datei wurde nie geholt, und die Stufe galt als offen, ohne
dass jemand es versucht hätte. Dieses Skript macht daraus einen Befehl.

Alle Teilschritte sind **idempotent** und **messend**:

* `setup`  — lädt das in `config/model.json` gepinnte GGUF, prüft SHA-256,
             baut `llama-server`, startet ihn. Vorhandenes wird nicht neu
             getan.
* `start`  — startet den Server, wartet bis `/health` `ok` sagt.
* `stop`   — beendet ihn.
* `status` — fragt den Server. Nicht die Dateien: eine vorhandene Datei ist
             kein laufender Dienst. Genau dieser Unterschied kostete einen
             Absturz — Modell und Binary lagen vor, `tiers()` meldete `[x]`,
             und der erste echte Aufruf brach mit SIGABRT ab.
* `ask`    — eine Frage, eine Antwort, Exit-Code sagt ob es klappte.

**Warum ein Server und keine CLI.** `llama-cli` lädt die 7-GB-Datei bei jeder
Frage neu (~40 s bis zum ersten Token) und bricht in aktuellen Builds in
`cli_server::wait_ready` mit SIGABRT ab. Der Server hält das Modell im
Speicher; dieselbe Frage kam über HTTP in 2,9 s zurück.

Weder Modell noch Binärdateien gehören ins Repo: 7 GB lägen in jedem Clone
für immer, auch nach dem Löschen. Beide Pfade stehen in `.gitignore`, und
dieses Skript stellt sie reproduzierbar wieder her.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODELL = REPO / "models" / "model.gguf"
BIN_DIR = REPO / "vendor" / "llama.cpp" / "bin"
SERVER = BIN_DIR / "llama-server"
QUELLE = REPO / "vendor" / "llama.cpp" / "src"
PID_DATEI = REPO / "vendor" / "llama.cpp" / "server.pid"
LOG = REPO / "vendor" / "llama.cpp" / "server.log"

URL_VORLAGE = "https://huggingface.co/{repo}/resolve/{rev}/{datei}"
LLAMA_GIT = "https://github.com/ggml-org/llama.cpp.git"
STANDARD_URL = os.environ.get("HM_LOCAL_LLM_URL", "http://127.0.0.1:8081")


def cfg() -> dict:
    return json.loads((REPO / "config" / "model.json").read_text(encoding="utf-8"))


def _sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with pfad.open("rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


# ── Modell ───────────────────────────────────────────────────────────────────

def modell_holen() -> int:
    """Lädt das gepinnte GGUF und prüft den Hash. Vorhandenes bleibt liegen."""
    up = cfg()["upstream"]
    if MODELL.is_file():
        ist = _sha256(MODELL)
        if ist == up["sha256"]:
            print(f"Modell vorhanden und geprueft: {MODELL} ({MODELL.stat().st_size} B)")
            return 0
        print(f"Modell vorhanden, aber Hash weicht ab:\n  erwartet {up['sha256']}\n  gemessen {ist}")
        print("Wird neu geladen.")
        MODELL.unlink()

    MODELL.parent.mkdir(parents=True, exist_ok=True)
    teil = MODELL.with_suffix(".gguf.part")
    url = URL_VORLAGE.format(repo=up["repo"], rev=up.get("revision", "main"), datei=up["file"])
    print(f"Lade {up['file']} ({up['bytes']/1e9:.1f} GB) …")
    # `--continue-at -` setzt einen Abbruch fort, statt von vorn zu beginnen.
    rc = subprocess.run(
        ["curl", "-L", "--fail", "--retry", "5", "--retry-delay", "3",
         "--continue-at", "-", "-o", str(teil), url],
        cwd=REPO,
    ).returncode
    if rc != 0:
        print(f"Download fehlgeschlagen (curl {rc}). Teildatei bleibt fuer Fortsetzung liegen.")
        return 1

    ist = _sha256(teil)
    if ist != up["sha256"]:
        print(f"SHA-256 stimmt NICHT:\n  erwartet {up['sha256']}\n  gemessen {ist}")
        print("Datei wird nicht uebernommen.")
        return 1
    teil.rename(MODELL)
    print(f"Modell geprueft und abgelegt: {MODELL}")
    return 0


# ── Laufzeit ─────────────────────────────────────────────────────────────────

def laufzeit_bauen() -> int:
    """Baut `llama-server` aus der Quelle. Vorhandenes wird nicht neu gebaut."""
    if SERVER.is_file() and os.access(SERVER, os.X_OK):
        print(f"Laufzeit vorhanden: {SERVER}")
        return 0

    fehlend = [w for w in ("cmake", "git") if shutil.which(w) is None]
    if fehlend:
        print(f"Zum Bauen fehlen: {', '.join(fehlend)}")
        return 1

    QUELLE.parent.mkdir(parents=True, exist_ok=True)
    if not (QUELLE / "CMakeLists.txt").is_file():
        if QUELLE.exists():
            shutil.rmtree(QUELLE)
        print("Hole llama.cpp …")
        if subprocess.run(["git", "clone", "--depth", "1", LLAMA_GIT, str(QUELLE)]).returncode:
            return 1

    print("Baue llama-server (das dauert einige Minuten) …")
    build = QUELLE / "build"
    if subprocess.run(
        ["cmake", "-B", str(build), "-S", str(QUELLE),
         "-DGGML_NATIVE=ON", "-DLLAMA_CURL=OFF", "-DCMAKE_BUILD_TYPE=Release"],
    ).returncode:
        return 1
    if subprocess.run(
        ["cmake", "--build", str(build), "--target", "llama-server",
         "-j", str(os.cpu_count() or 4)],
    ).returncode:
        return 1

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    for datei in sorted((build / "bin").iterdir()):
        if not (datei.is_file() and (datei.name.startswith("lib")
                                     or datei.name.startswith("llama-"))):
            continue
        ziel = BIN_DIR / datei.name
        # Temp-Datei daneben, dann `os.replace` -- NICHT direkt darueber
        # kopieren. Gemessen: laeuft der `llama-server` bereits aus genau
        # dieser Datei, scheitert `shutil.copy2` mit
        # `OSError: [Errno 26] Text file busy`, und `setup` bricht ab,
        # obwohl Modell und Dienst in Ordnung sind. Ein Rename ueber eine
        # laufende Binaerdatei ist auf POSIX erlaubt: der laufende Prozess
        # behaelt seinen alten Inode, neue Starts nehmen den neuen.
        #
        # Dieselbe Regel wie bei `LocalFsStorage::put` und aus demselben
        # Grund: ein Ziel, das jemand gerade benutzt, wird nicht in place
        # ueberschrieben.
        temp = ziel.with_name(ziel.name + f".neu{os.getpid()}")
        try:
            shutil.copy2(datei, temp)
            temp.chmod(0o755)
            os.replace(temp, ziel)
        finally:
            temp.unlink(missing_ok=True)
    print(f"Laufzeit gebaut: {SERVER}")
    return 0


# ── Dienst ───────────────────────────────────────────────────────────────────

def _gesund(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        return d.get("status") == "ok", str(d.get("status"))
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} (laedt vermutlich)"
    except Exception as e:
        return False, type(e).__name__


def _laufende_pid() -> int | None:
    if not PID_DATEI.is_file():
        return None
    try:
        pid = int(PID_DATEI.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        return None


def starten(url: str = STANDARD_URL, warte_s: int = 600) -> int:
    gesund, _ = _gesund(url)
    if gesund:
        print(f"Laeuft bereits: {url}")
        return 0
    if not MODELL.is_file():
        print("Modell fehlt — zuerst: python3 scripts/hugin_local_model.py setup")
        return 1
    if not SERVER.is_file():
        print("Laufzeit fehlt — zuerst: python3 scripts/hugin_local_model.py setup")
        return 1

    lauf = cfg().get("laufzeit", {})
    port = url.rsplit(":", 1)[-1]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("wb") as log:
        proc = subprocess.Popen(
            [str(SERVER), "-m", str(MODELL),
             "-t", str(lauf.get("threads", os.cpu_count() or 4)),
             "-c", str(lauf.get("context", 8192)),
             "-b", str(lauf.get("batch", 256)),
             "--host", "127.0.0.1", "--port", port],
            cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PID_DATEI.write_text(str(proc.pid))
    print(f"Gestartet (PID {proc.pid}), warte auf Modellladung …")

    frist = time.time() + warte_s
    while time.time() < frist:
        if proc.poll() is not None:
            print(f"Server endete sofort (Exit {proc.returncode}). Log: {LOG}")
            return 1
        gesund, grund = _gesund(url)
        if gesund:
            print(f"Bereit: {url} nach {int(warte_s - (frist - time.time()))}s")
            return 0
        time.sleep(3)
    print(f"Nicht bereit nach {warte_s}s (zuletzt: {grund}). Log: {LOG}")
    return 1


def stoppen() -> int:
    pid = _laufende_pid()
    if pid is None:
        print("Kein laufender Server (keine gueltige PID-Datei).")
        PID_DATEI.unlink(missing_ok=True)
        return 0
    os.kill(pid, 15)
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.2)
    PID_DATEI.unlink(missing_ok=True)
    print(f"Gestoppt (PID {pid}).")
    return 0


def status(url: str = STANDARD_URL, als_json: bool = False) -> int:
    gesund, grund = _gesund(url)
    modell_da = MODELL.is_file()
    daten = {
        "erreichbar": gesund,
        "url": url,
        "grund": grund,
        "modell_vorhanden": modell_da,
        "modell_bytes": MODELL.stat().st_size if modell_da else 0,
        "laufzeit_vorhanden": SERVER.is_file(),
        "pid": _laufende_pid(),
    }
    if als_json:
        print(json.dumps(daten, ensure_ascii=False, indent=2))
    else:
        print(f"T1b lokal   : {'BEREIT' if gesund else 'NICHT BEREIT'}  ({url}, {grund})")
        print(f"  Modell    : {'ja' if modell_da else 'nein'}"
              + (f", {daten['modell_bytes']} B" if modell_da else ""))
        print(f"  Laufzeit  : {'ja' if daten['laufzeit_vorhanden'] else 'nein'}  ({SERVER})")
        print(f"  PID       : {daten['pid'] or '—'}")
        if not gesund:
            print("  Befehl    : python3 scripts/hugin_local_model.py "
                  + ("start" if modell_da and daten["laufzeit_vorhanden"] else "setup"))
    return 0 if gesund else 1


def fragen(text: str, url: str = STANDARD_URL, max_tokens: int = 300) -> int:
    """Eine Frage, eine Antwort. Exit 0 nur bei echter Antwort."""
    gesund, grund = _gesund(url)
    if not gesund:
        print(f"Lokales Modell nicht bereit ({grund}). "
              "python3 scripts/hugin_local_model.py start", file=sys.stderr)
        return 1
    koerper = json.dumps({
        "messages": [{"role": "user", "content": text}],
        "temperature": cfg().get("laufzeit", {}).get("temp", 0.2),
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(f"{url}/v1/chat/completions", data=koerper,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            antwort = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        print(f"Anfrage fehlgeschlagen: {exc}", file=sys.stderr)
        return 1
    inhalt = (antwort.get("choices") or [{}])[0].get("message", {}).get("content", "")
    if not inhalt.strip():
        print("Leere Antwort — das ist kein Erfolg.", file=sys.stderr)
        return 1
    print(inhalt)
    return 0


def setup(url: str = STANDARD_URL) -> int:
    """Alles, was T1b braucht — in einem Befehl, ohne Rueckfrage."""
    for schritt, fn in (("Modell", modell_holen), ("Laufzeit", laufzeit_bauen)):
        print(f"── {schritt} ──")
        rc = fn()
        if rc:
            print(f"{schritt} fehlgeschlagen — Abbruch.")
            return rc
    print("── Dienst ──")
    return starten(url)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("befehl", choices=["setup", "fetch", "build", "start", "stop",
                                      "status", "ask", "restart"])
    p.add_argument("text", nargs="?", default="")
    p.add_argument("--url", default=STANDARD_URL)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    if a.befehl == "setup":
        return setup(a.url)
    if a.befehl == "fetch":
        return modell_holen()
    if a.befehl == "build":
        return laufzeit_bauen()
    if a.befehl == "start":
        return starten(a.url)
    if a.befehl == "stop":
        return stoppen()
    if a.befehl == "restart":
        stoppen()
        return starten(a.url)
    if a.befehl == "status":
        return status(a.url, a.json)
    if a.befehl == "ask":
        if not a.text.strip():
            print("ask braucht eine Frage.", file=sys.stderr)
            return 2
        return fragen(a.text, a.url)
    return 2


if __name__ == "__main__":
    sys.exit(main())
