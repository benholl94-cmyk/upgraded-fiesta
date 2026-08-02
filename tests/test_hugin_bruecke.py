"""Die Bruecke — plant Provider-Aufrufe und oeffnet dabei keinen Socket.

Diese Datei kam als eigenstaendiges Einzeldatei-Werkzeug ins Repo. Der
Grund, warum sie neben `scripts/hugin_oracle.py` stehen **darf**, ist eine
einzige Eigenschaft: sie sendet nichts. Die Verfassung kennt einen Weg nach
draussen, und das ist das Oracle-Gate; ein zweiter waere kein
Rueckfallplan, sondern die Stelle, an der beide auseinanderlaufen.

Diese Eigenschaft wird hier **nachgerechnet**, nicht der Herkunftsdoku
geglaubt — das ist dieselbe Regel, mit der der Supervisor jede andere
Behauptung dieses Repos behandelt.
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
QUELLE = REPO / "scripts" / "hugin_bruecke.py"
sys.path.insert(0, str(REPO / "scripts"))

import hugin_bruecke as hb  # noqa: E402


@pytest.fixture
def heim(monkeypatch):
    """Ein eigenes Heim je Test — nie `~/.hugin` des Betreibers anfassen."""
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("HUGIN_BRUECKE_HEIM", d)
        yield pathlib.Path(d)


# ---------------------------------------------------------------------------
# Die Eigenschaft, die alles traegt: kein Netz
# ---------------------------------------------------------------------------

NETZ = {"socket", "http", "http.client", "urllib", "urllib.request",
        "requests", "ssl", "ftplib", "smtplib", "telnetlib", "asyncio"}


def test_the_bridge_imports_nothing_that_could_open_a_socket():
    """**Der Test, der diese Datei ueberhaupt zulaessig macht.**

    Sie plant Provider-Aufrufe. Wuerde sie auch senden, gaebe es zwei Wege
    nach draussen — und die Verfassung kennt einen: das Oracle-Gate.
    Geprueft wird der Importbaum, nicht der Kommentar darueber.
    """
    baum = ast.parse(QUELLE.read_text(encoding="utf-8"))
    importe = set()
    for k in ast.walk(baum):
        if isinstance(k, ast.Import):
            importe.update(a.name.split(".")[0] for a in k.names)
        elif isinstance(k, ast.ImportFrom) and k.module:
            importe.add(k.module.split(".")[0])
    verboten = importe & {n.split(".")[0] for n in NETZ}
    assert not verboten, f"Bruecke importiert Netzwerkmodule: {sorted(verboten)}"


def test_the_bridge_never_calls_a_shell():
    assert "shell=True" not in QUELLE.read_text(encoding="utf-8")


def test_the_oracle_gate_remains_the_only_way_out():
    """Gegenprobe: das Gate sendet, die Bruecke nicht. Zwei Rollen, keine
    Verdopplung."""
    gate = (REPO / "scripts" / "hugin_oracle.py").read_text(encoding="utf-8")
    assert "urllib" in gate or "http" in gate, \
        "das Oracle-Gate sendet nicht mehr — dann stimmt die Rollenteilung nicht"


# ---------------------------------------------------------------------------
# Siegel und Doppelfach
# ---------------------------------------------------------------------------

def test_keimen_creates_a_sealed_state(heim):
    assert hb.befehl_keimen([]) == 0
    assert (heim / "schluessel").is_file() or any(heim.iterdir())


def test_a_foreign_key_does_not_unseal_the_state(heim):
    """Fail-closed: ein fremder Schluessel darf den Zustand nicht oeffnen."""
    hb.befehl_keimen([])
    echt = hb.schluessel_laden()
    obj = {"a": 1}
    assert hb.siegel_gueltig(echt, obj, hb.siegeln(echt, obj))
    assert not hb.siegel_gueltig(b"x" * 32, obj, hb.siegeln(echt, obj))


def test_a_damaged_compartment_is_healed_from_the_healthy_one(heim):
    """Das Doppelfach ist der Grund, warum ein halber Schreibvorgang hier
    kein Datenverlust ist — dieselbe Regel wie bei `LocalFsStorage::put`."""
    hb.befehl_keimen([])
    schluessel = hb.schluessel_laden()
    fach_a = heim / "fach_a.json"
    if fach_a.is_file():
        fach_a.write_text("{kaputt", encoding="utf-8")
        zustand, geheilt = hb.zustand_laden(schluessel)
        assert zustand.get("routen") is not None
        assert geheilt


def test_the_chronicle_is_chained(heim):
    """Jede Quittung traegt den Hash der vorigen Zeile. Eine entfernte Zeile
    faellt damit auf, statt zu verschwinden."""
    hb.befehl_keimen([])
    schluessel = hb.schluessel_laden()
    hb.chronik_anhaengen(schluessel, {"was": "eins"})
    hb.chronik_anhaengen(schluessel, {"was": "zwei"})
    anzahl, fehler = hb.chronik_pruefen(schluessel)
    assert anzahl == 2 and not fehler, fehler


def test_a_tampered_chronicle_line_is_detected(heim):
    """**Die Gegenprobe, die zaehlt.** Eine Verhakung, die eine veraenderte
    Zeile nicht bemerkt, ist Zierde. Hier wird eine Zeile veraendert und
    verlangt, dass die Pruefung sie meldet."""
    hb.befehl_keimen([])
    schluessel = hb.schluessel_laden()
    hb.chronik_anhaengen(schluessel, {"was": "eins"})
    hb.chronik_anhaengen(schluessel, {"was": "zwei"})
    p = pathlib.Path(hb.P_CHRONIK())
    zeilen = p.read_text(encoding="utf-8").splitlines()
    d = json.loads(zeilen[0])
    d["was"] = "gefaelscht"
    zeilen[0] = json.dumps(d, ensure_ascii=False, sort_keys=True)
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    _, fehler = hb.chronik_pruefen(schluessel)
    assert fehler, "veraenderte Chronikzeile blieb unbemerkt"


# ---------------------------------------------------------------------------
# Der eigene Selbsttest — 100 Faelle, die mit der Datei kamen
# ---------------------------------------------------------------------------

def test_the_bundled_selftest_passes():
    """Die Datei bringt 100 eigene Faelle mit. Sie hier mitlaufen zu lassen
    ist billiger als sie nachzubauen — und ehrlicher: sie pruefen genau die
    Kette, die ihr Autor gebaut hat."""
    with tempfile.TemporaryDirectory() as d:
        umgebung = dict(os.environ, HUGIN_BRUECKE_HEIM=d)
        r = subprocess.run([sys.executable, str(QUELLE), "--selftest"],
                           cwd=REPO, capture_output=True, text=True,
                           timeout=900, env=umgebung)
        assert r.returncode == 0, r.stdout[-1500:]
        assert "bestanden" in r.stdout


def test_the_cli_answers_help():
    r = subprocess.run([sys.executable, str(QUELLE), "--hilfe"],
                       cwd=REPO, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0
    assert "Socket" in r.stdout, "die Hilfe verschweigt die zentrale Eigenschaft"


# ---------------------------------------------------------------------------
# Einpassung ins Repo
# ---------------------------------------------------------------------------

def test_the_state_lives_under_the_repos_own_home():
    """`~/.hugin/` ist der Ort, an dem dieses Repo seinen lokalen Zustand
    haelt — der Schluesselbund liegt dort ebenfalls. Ein zweites
    Heimverzeichnis waere ein zweiter Ort zum Vergessen."""
    text = QUELLE.read_text(encoding="utf-8")
    assert '".hugin", "bruecke"' in text
    assert "HUGIN_BRUECKE_HEIM" in text


def test_no_trace_of_the_original_name_remains():
    """Eine halbe Umbenennung ist schlimmer als keine: sie laesst zwei Namen
    fuer dieselbe Sache im Baum."""
    text = QUELLE.read_text(encoding="utf-8").lower()
    assert "bifroest" not in text


# ---------------------------------------------------------------------------
# Die Regel, die die Bruecke passieren laesst — und die dabei nicht stumpf wird
# ---------------------------------------------------------------------------

def test_the_oracle_rule_lets_a_planner_pass():
    """Eine Datei darf Provider-Endpunkte *nennen*, ohne sie aufzurufen."""
    sys.path.insert(0, str(REPO / "scripts"))
    import munin_supervisor as ms
    assert not ms._kann_senden("scripts/x.py",
                               'ROUTEN = {"a": "https://api.anthropic.com/v1"}\n')


def test_the_oracle_rule_still_bites_when_a_socket_appears():
    """**Die Gegenprobe, die zaehlt.** Waere die Bruecke einfach in
    `ORACLE_EXEMPT` eingetragen worden, gaelte die Ausnahme auch, nachdem
    jemand `import urllib` ergaenzt — genau die Sorte Eintrag, die hier
    schon einmal ein Loch hinterliess (`KNOWN_SAFE_ENV` zeigte auf eine
    geloeschte Datei). Die Regel prueft deshalb die Eigenschaft."""
    sys.path.insert(0, str(REPO / "scripts"))
    import munin_supervisor as ms
    for quelle in ("import urllib.request\nX='api.anthropic.com'\n",
                   "import socket\n", "from http import client\n",
                   "import requests\n"):
        assert ms._kann_senden("scripts/x.py", quelle), quelle


def test_a_non_python_file_is_never_assumed_harmless():
    """Unbekanntes gilt nie als in Ordnung — dieselbe Richtung wie ueberall."""
    sys.path.insert(0, str(REPO / "scripts"))
    import munin_supervisor as ms
    assert ms._kann_senden("deploy/irgendwas.sh", "curl api.anthropic.com")
