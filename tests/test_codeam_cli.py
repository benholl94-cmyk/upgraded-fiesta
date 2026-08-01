"""Tests der CodeAgent-Mobile-Bruecke.

Der Auftrag lautete: ein Deploy aus der App soll **ohne Rueckfrage**
funktionieren. Jede Stelle, an der ein Mensch etwas eintippen oder eine
Variable exportieren muesste, ist damit ein Defekt und kein Bedienschritt.

Zwei reale Fehler haben diese Datei ausgeloest, beide von der Sorte
"vorhanden, wohlgeformt, wirkungslos":

1. `.devcontainer/dev-container.json` — mit Bindestrich. Die Spezifikation
   kennt den Namen nicht und meldet das nicht: der Codespace bootet dann
   still das Standardimage.
2. `verify` las den Owner-Token aus der aufrufenden Shell und meldete
   `HTTP 401`, waehrend derselbe Dienst lief. Die "Loesung" waere gewesen:
   der Mensch exportiert eine Variable.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import codeam_cli as cc  # noqa: E402

DEVCONTAINER = REPO / ".devcontainer" / "devcontainer.json"


def _json_ohne_kommentare(pfad: pathlib.Path) -> dict:
    """devcontainer.json erlaubt `//`-Schluessel als Kommentare (jsonc-nah).
    Hier stehen sie als normale String-Keys, also ist es echtes JSON."""
    return json.loads(pfad.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Der Devcontainer muss ueberhaupt gelesen werden
# ---------------------------------------------------------------------------

def test_the_devcontainer_has_a_name_the_spec_actually_recognises():
    """Die Spezifikation kennt genau drei Pfade. Jeder andere Name wird
    ignoriert — ohne Fehlermeldung."""
    gueltig = [
        REPO / ".devcontainer" / "devcontainer.json",
        REPO / ".devcontainer.json",
    ]
    gueltig += list((REPO / ".devcontainer").glob("*/devcontainer.json"))
    assert any(p.is_file() for p in gueltig), \
        "keine Datei an einem von der Spezifikation gelesenen Pfad"


def test_the_hyphenated_name_is_gone():
    """Gegentest zum konkreten Vorfall. Laege beides da, gaebe es zwei
    Wahrheiten und die falsche waere die aeltere."""
    assert not (REPO / ".devcontainer" / "dev-container.json").is_file()


def test_the_devcontainer_is_valid_json():
    _json_ohne_kommentare(DEVCONTAINER)


def test_node_is_at_least_22_because_codeam_cli_requires_it():
    """codeam-cli 2.61.76 setzt `engines.node >= 22`. Mit Node 20 bricht
    `codeam deploy` ab, NACHDEM er den Codespace schon gestartet hat — die
    teure Reihenfolge."""
    d = _json_ohne_kommentare(DEVCONTAINER)
    node = d["features"]["ghcr.io/devcontainers/features/node:1"]["version"]
    assert int(str(node).split(".")[0]) >= 22, f"Node {node} ist zu alt fuer codeam-cli"


def test_the_github_cli_is_present_because_deploy_reuses_its_oauth():
    """`codeam deploy` fragt bewusst nach keinem eigenen Token, sondern nutzt
    die Sitzung von `gh`. Ohne `gh` gibt es keinen Deploy."""
    d = _json_ohne_kommentare(DEVCONTAINER)
    assert any("github-cli" in f for f in d["features"])


def test_the_gateway_binds_to_all_interfaces():
    """127.0.0.1 waere im Codespace unerreichbar: die Portweiterleitung
    greift nur auf 0.0.0.0."""
    d = _json_ohne_kommentare(DEVCONTAINER)
    assert d["remoteEnv"]["HM_GATEWAY_BIND"].startswith("0.0.0.0:")


def test_the_service_port_is_forwarded_and_matches_the_contract():
    d = _json_ohne_kommentare(DEVCONTAINER)
    port = cc.konfig()["dienst"]["port"]
    assert port in d["forwardPorts"], f"Port {port} wird nicht weitergeleitet"


def test_setup_runs_and_can_fail():
    """Der frueher hier stehende Aufruf endete auf `2>/dev/null || true`.
    Ein Setup, das nicht scheitern kann, sagt auch nie, dass es nichts
    getan hat."""
    d = _json_ohne_kommentare(DEVCONTAINER)
    befehl = d["postCreateCommand"]
    assert "codeam_cli.py prepare" in befehl
    assert "|| true" not in befehl and "2>/dev/null" not in befehl


# ---------------------------------------------------------------------------
# Kein Schritt darf einen Menschen verlangen
# ---------------------------------------------------------------------------

def test_the_owner_token_comes_from_the_project_not_from_a_shell(monkeypatch, tmp_path):
    """Der eigentliche Punkt: das Projekt stellt seinen Owner-Token selbst
    aus. Verlangte `verify` eine exportierte Variable, waere der Deploy nicht
    automatisiert, sondern nur dokumentiert.

    Geprueft wird in einem LEEREN HOME — also genau die Lage eines frisch
    gebooteten Codespace. Die erste Fassung dieses Tests behauptete, der
    Token sei immer ableitbar, und war auf dieser Maschine gruen, weil hier
    laengst ein Seed lag. Auf dem CI-Runner fiel er sofort: ohne Seed gibt es
    nichts abzuleiten. Der Test hatte damit die eigene Umgebung geprueft
    statt die Zusicherung.

    Die Zusicherung lautet nicht "immer ableitbar", sondern: **kein Mensch
    noetig**. Genau diesen Weg geht der Devcontainer im postCreate.
    """
    monkeypatch.delenv("HM_OWNER_TOKEN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    # Vorher: leeres HOME, kein Seed, also auch kein Token.
    assert not cc.eigene_umgebung().get("HM_OWNER_TOKEN"), \
        "ohne Seed darf kein Token erscheinen — sonst kommt er von woanders"

    # Der automatisierte Schritt, den postCreate faehrt. Kein Mensch beteiligt.
    schritt = cc.s_schluessel(apply=True)
    assert schritt.stand == cc.OK, schritt.detail

    # Danach traegt es — ohne dass jemand etwas exportiert hat.
    assert cc.eigene_umgebung().get("HM_OWNER_TOKEN"), \
        "nach prepare immer noch kein Token — dann braucht der Deploy einen Menschen"


def test_an_already_set_token_is_never_overwritten(monkeypatch):
    """Ein von aussen gesetzter Token gewinnt: ein laufender Dienst kennt
    ihn bereits, und ihn zu ersetzen wuerde die Gegenstelle aussperren."""
    monkeypatch.setenv("HM_OWNER_TOKEN", "vorgegeben-123")
    assert cc.eigene_umgebung()["HM_OWNER_TOKEN"] == "vorgegeben-123"


def test_setup_steps_are_idempotent_by_description():
    """Ein zweiter Lauf darf nichts aendern — die App darf `prepare`
    wiederholen duerfen, ohne Schaden anzurichten."""
    schritte = cc.prepare(apply=False)
    ids = [s.id for s in schritte]
    assert ids == ["werkzeuge", "schluessel", "bauen", "selbsterhalt"]
    # Trockenlauf aendert nichts: zweimal aufgerufen dasselbe Ergebnis.
    assert [s.stand for s in cc.prepare(apply=False)] == [s.stand for s in schritte]


# ---------------------------------------------------------------------------
# Der Vertrag, den die App liest
# ---------------------------------------------------------------------------

def test_describe_names_everything_needed_to_talk_to_the_service():
    d = cc.describe()
    dienst = d["dienst"]
    assert dienst["port"] and dienst["auth"]["env"] and dienst["auth"]["typ"] == "bearer"
    assert dienst["chat"]["pfad"] and dienst["health"]["pfad"]
    assert dienst["chat"]["streamt"] is True


def test_describe_warns_against_eventsource():
    """EventSource kann keinen Authorization-Header setzen; die Route ist
    bearer-gated. Ohne diesen Hinweis baut jeder Client es einmal falsch."""
    d = cc.describe()
    assert "EventSource" in json.dumps(d["dienst"]["chat"], ensure_ascii=False)


def test_describe_measures_instead_of_claiming():
    """`laeuft_bereits` muss eine Messung sein, keine Konfigurationsangabe."""
    d = cc.describe()
    assert isinstance(d["gemessen"]["laeuft_bereits"], bool)
    assert cc._tcp("127.0.0.1", 1) is False, "die Sonde misst nichts"


def test_describe_states_the_limits_honestly():
    """Was fehlt, gehoert in den Vertrag — sonst haelt die App T0-Belege
    fuer eine kaputte Modellantwort."""
    grenzen = json.dumps(cc.describe()["grenzen"], ensure_ascii=False).lower()
    assert "gesperrt" in grenzen and "modell" in grenzen


def test_the_suggested_commands_all_exist_in_the_brain():
    """Ein Vorschlag, den das Gehirn nicht kennt, ist ein Knopf, der nichts
    tut."""
    sys.path.insert(0, str(REPO))
    from agents import brain
    bekannt = set(brain.COMMANDS) | {"help", "tiers"}
    for vorschlag in cc.konfig()["befehle"]["vorschlaege"]:
        assert vorschlag.lstrip("/") in bekannt, f"{vorschlag} kennt das Gehirn nicht"


def test_doctor_is_machine_readable():
    """Die App liest das, kein Mensch."""
    p = subprocess.run([sys.executable, "scripts/codeam_cli.py", "doctor"],
                       cwd=REPO, capture_output=True, text=True, timeout=300)
    d = json.loads(p.stdout)
    assert "describe" in d and "verify" in d


@pytest.mark.parametrize("cmd", ["describe", "verify"])
def test_every_command_supports_json(cmd):
    argv = [sys.executable, "scripts/codeam_cli.py", cmd, "--json"]
    p = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=300)
    json.loads(p.stdout)


def test_prepare_reports_machine_readable_steps():
    """`prepare` wird bewusst NICHT als Unterprozess geprueft: es startet den
    Selbsterhalt-Lauf, und der fuehrt die gesamte Testsuite aus — aus pytest
    heraus waere das eine Schachtelung, die je Aufruf ueber eine Minute
    kostet und nichts zusaetzlich beweist. Geprueft wird die Form der
    Ausgabe, und die entsteht hier."""
    schritte = cc.prepare(apply=False)
    daten = json.loads(json.dumps([s.to_dict() for s in schritte], ensure_ascii=False))
    assert daten and all("id" in d and "stand" in d for d in daten)


def test_prepare_without_yes_changes_nothing():
    """Ein Trockenlauf, der doch etwas tut, ist die gefaehrlichste Variante."""
    seed = pathlib.Path.home() / ".hugin" / "master.seed"
    vorher = seed.stat().st_mtime if seed.is_file() else None
    cc.prepare(apply=False)
    nachher = seed.stat().st_mtime if seed.is_file() else None
    assert vorher == nachher


def test_describe_enumerates_the_env_vars_the_gateway_actually_reads():
    d = cc.describe()
    dienst = json.dumps(d["dienst"], ensure_ascii=False)
    for var in ("HM_OWNER_TOKEN", "HM_GATEWAY_ALLOW_NO_AUTH", "HM_BRAIN_REPO", "HM_BRAIN_PYTHON", "HM_ALLOWED_ORIGINS"):
        assert var in dienst, f"{var} fehlt im appseitigen Vertrag"


def test_preview_declares_the_required_env():
    import json as _json
    preview = _json.loads(pathlib.Path(".codeam/preview.json").read_text())
    for var in ("HM_GATEWAY_BIND", "HM_OWNER_TOKEN", "HM_BRAIN_REPO", "HM_BRAIN_PYTHON"):
        assert var in preview.get("required_env", []), f"{var} fehlt im preview.json required_env"
