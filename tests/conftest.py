"""Gemeinsame Voraussetzungen der Testsuite — an einer Stelle, nicht je Workflow.

## Warum diese Datei entstanden ist

Zwei Tests starten einen echten `target/debug/hm-gateway` als Unterprozess.
Bis zum 2026-08-02 uebersprangen sie sich still, wenn die Datei fehlte —
und im Python-Job der CI fehlte sie *immer*, weil der Job keinen
Rust-Schritt hat. Beide Tests liefen dort nie.

Behoben wurde das zuerst in `ci.yml`: der Job baut das Binary jetzt selbst.
**Und genau dort lag der naechste Fehler.** `.github/workflows/zyklus.yml`
faehrt ebenfalls `pytest tests/` — ohne Rust-Schritt. Der erste echte
Kettenlauf meldete prompt `2 failed, 1465 passed`: die Tests, die vorher
still auswichen, fielen jetzt laut. Das war richtig, aber die Ursache war
meine eigene halbe Korrektur.

**Eine Voraussetzung, die jeder Workflow einzeln kennen muss, wird beim
naechsten Workflow vergessen.** Deshalb steht sie hier: die Suite stellt
selbst her, was sie braucht.

## Was die Fixture tut, und was ausdruecklich nicht

Sie baut das Binary **einmal je Sitzung** und nur, wenn es fehlt — `cargo
build` ist bei vorhandenem Artefakt ein No-Op von Millisekunden. Sie
faelscht nichts: fehlt `cargo`, schlaegt der Test fehl und nennt den
Befehl. Ein Skip waere hier wieder die Spur, die dieses Repo verbietet.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
GATEWAY = REPO / "target" / "debug" / "hm-gateway"

#: Ergebnis des einen Bauversuchs. `None` heisst "noch nicht versucht".
_GEBAUT: bool | None = None


def _bauen() -> bool:
    """Einmal je Sitzung. Gibt zurueck, ob das Binary danach da ist."""
    global _GEBAUT
    if _GEBAUT is not None:
        return _GEBAUT
    if GATEWAY.is_file():
        _GEBAUT = True
        return True
    if shutil.which("cargo") is None:
        _GEBAUT = False
        return False
    r = subprocess.run(["cargo", "build", "-p", "hm-gateway"], cwd=REPO,
                       capture_output=True, text=True, timeout=1800)
    _GEBAUT = r.returncode == 0 and GATEWAY.is_file()
    if not _GEBAUT:
        print(r.stderr[-800:], file=sys.stderr)
    return _GEBAUT


@pytest.fixture(scope="session")
def gateway_binary() -> pathlib.Path:
    """Der Pfad zu einem **vorhandenen** `target/debug/hm-gateway`.

    Kein Skip: ein Test, der einen echten Gateway-Prozess braucht und ihn
    nicht bekommt, prueft nichts — und das soll auffallen, nicht
    verschwinden.
    """
    assert _bauen(), (
        "target/debug/hm-gateway fehlt und liess sich nicht bauen. "
        "Dieser Test startet einen echten Gateway-Prozess. "
        "Herstellen mit: cargo build -p hm-gateway"
    )
    return GATEWAY
