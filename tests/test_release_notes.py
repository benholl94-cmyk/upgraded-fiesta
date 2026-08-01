"""Tests der Release-Notiz und des Workflows, der sie veroeffentlicht.

Eine Release-Notiz ist das **sichtbarste** Veroeffentlichungsartefakt dieses
Repos: sie steht auf der Startseite des Projekts und wird gelesen, wenn sonst
nichts gelesen wird. Zwei Eigenschaften muessen deshalb erzwungen sein und
duerfen nicht auf Sorgfalt beruhen:

1. Sie traegt kein Geheimnis — und zwar so, dass sie im Zweifel **nicht
   geschrieben** wird, nicht bloss gewarnt.
2. Sie behauptet nichts, was nicht im Manifest steht. Insbesondere darf
   Gefallenes nicht verschwinden: eine Notiz, die nur Bestandenes zeigt, ist
   eine Auswahl und keine Aussage.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import build_manifest as bm  # noqa: E402
import release_notes as rn  # noqa: E402


def _manifest(**ueberschreiben) -> dict:
    d = {
        "schema": "hugin.build.v1",
        "erzeugt": "2026-07-31T15:28:46+00:00",
        "commit": "f" * 40,
        "commit_kurz": "fffffff",
        "branch": "main",
        "sauber": True,
        "werkzeuge": {"rustc": "rustc 1.97.1", "cargo": "cargo 1.97.1",
                      "python": "3.12.13", "node": "v22.23.1",
                      "docker": "Docker version 28.0.4"},
        "artefakte": [
            {"name": "gateway", "pfad": "target/release/hm-gateway",
             "bytes": 5748768, "sha256": "a" * 64},
        ],
        "pruefungen": [
            {"pruefung": "repo-struktur", "befehl": "validate_repo.py",
             "ergebnis": bm.BESTANDEN},
        ],
    }
    d.update(ueberschreiben)
    return d


# ---------------------------------------------------------------------------
# Kein Geheimnis, niemals
# ---------------------------------------------------------------------------

def test_a_secret_in_the_notes_prevents_the_file_from_being_written(tmp_path, monkeypatch):
    """Der Gegentest, der zaehlt: nicht 'wird erkannt', sondern 'wird nicht
    geschrieben'. Dieselbe Regel wie beim Manifest."""
    ziel = tmp_path / "notes.md"
    m = tmp_path / "m.json"
    m.write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setattr(rn, "notiz",
                        lambda *a, **k: "# x\n\nghp_" + "y" * 36 + "\n")
    code = rn.main(["--tag", "v1.0.0", "--manifest", str(m), "--out", str(ziel)])
    assert code == 2, "Abbruch erwartet"
    assert not ziel.exists(), "Notiz trotz Geheimnis geschrieben"


def test_a_normal_note_carries_nothing_secret(tmp_path):
    text = rn.notiz("v1.0.0", _manifest(), None, "ghcr.io/o/r/hm-gateway")
    assert bm.leckpruefung(text) == []


def test_the_note_names_the_auth_variable_but_no_value():
    """Dass ein Dienst `HM_OWNER_TOKEN` liest, ist keine Preisgabe. Sein Wert
    waere eine."""
    vertrag = {"dienst": {"port": 8080, "bind_env": "HM_GATEWAY_BIND",
                          "auth": {"typ": "bearer", "env": "HM_OWNER_TOKEN",
                                   "fail_closed": True}}}
    text = rn.notiz("v1.0.0", _manifest(), vertrag, None)
    assert "HM_OWNER_TOKEN" in text
    assert "fail-closed: `true`" in text, "Python-Repr statt JSON in der Notiz"


# ---------------------------------------------------------------------------
# Nichts verschwindet
# ---------------------------------------------------------------------------

def test_a_failed_check_appears_in_the_note():
    m = _manifest(pruefungen=[
        {"pruefung": "compose-syntax", "befehl": "docker compose config",
         "ergebnis": bm.GEFALLEN, "ausgabe": "boom"},
    ])
    text = rn.notiz("v1.0.0", m, None, None)
    assert "GEFALLEN" in text
    assert "compose-syntax" in text.split("NICHT nachgewiesen")[1], \
        "Gefallenes fehlt im Grenzen-Abschnitt"


def test_an_unknown_check_is_not_silently_treated_as_passed():
    m = _manifest(pruefungen=[
        {"pruefung": "systemd-units", "befehl": "systemd-analyze verify",
         "ergebnis": bm.UNBEKANNT, "grund": "systemd-analyze nicht vorhanden"},
    ])
    text = rn.notiz("v1.0.0", m, None, None)
    assert "unbekannt" in text
    assert "systemd-units" in text.split("NICHT nachgewiesen")[1]


def test_a_missing_artefact_is_named_as_missing():
    """Eine Liste, aus der Fehlendes verschwindet, sieht immer vollstaendig
    aus."""
    m = _manifest(artefakte=[{"name": "cli", "pfad": "target/release/hm-cli",
                              "fehlt": True}])
    text = rn.notiz("v1.0.0", m, None, None)
    assert "nicht gebaut" in text
    assert "hm-cli" in text.split("NICHT nachgewiesen")[1]


def test_the_limits_section_is_never_empty():
    """Auch bei einem vollstaendig gruenen Bau. Was hier nicht nachgewiesen
    ist, haengt nicht davon ab, ob die Pruefungen bestanden haben — die
    Kanalkraten sind gegen keine echte Plattform getestet, egal wie gruen
    dieser Lauf war."""
    text = rn.notiz("v1.0.0", _manifest(), None, None)
    grenzen = text.split("NICHT nachgewiesen")[1]
    assert "Kanalkraten" in grenzen
    assert "GGUF" in grenzen


def test_every_number_in_the_note_comes_from_the_manifest():
    """Gegenprobe: eine geaenderte Groesse im Manifest aendert die Notiz.
    Waere die Zahl hineingeschrieben, blieben beide gleich."""
    a = rn.notiz("v1.0.0", _manifest(), None, None)
    m = _manifest()
    m["artefakte"][0]["bytes"] = 1234567
    b = rn.notiz("v1.0.0", m, None, None)
    assert a != b


# ---------------------------------------------------------------------------
# Der Workflow, der es veroeffentlicht
# ---------------------------------------------------------------------------

WORKFLOW = REPO / ".github" / "workflows" / "release.yml"


def _workflow() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_release_workflow_is_triggered_by_a_tag_not_by_a_person():
    """Der Punkt der ganzen Datei. Ein Release, das nur jemand mit dem
    richtigen Werkzeug in der Hand herstellen kann, ist genau die
    Abhaengigkeit, die hier verschwinden soll."""
    d = _workflow()
    # `on:` liest PyYAML als Boolean True — das ist der YAML-1.1-Fallstrick,
    # nicht ein Fehler in der Datei.
    ausloeser = d.get("on", d.get(True))
    assert ausloeser["push"]["tags"] == ["v*"]


def test_publishing_uses_only_the_built_in_token():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.token" in text
    import re
    fremde = [m.group(1) for m in re.finditer(r"secrets\.([A-Z_]+)", text)
              if m.group(1) != "GITHUB_TOKEN"]
    assert not fremde, f"fremde Secrets verlangt: {fremde}"


def test_the_image_is_checked_live_before_it_is_published():
    """Ein Image, das gebaut wurde, ist nicht dasselbe wie ein Image, das
    antwortet. Ein Release ist der letzte Ort, an dem das auffallen darf."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for beweis in ("/health", "/chat", "/tasks", "401", "DONE",
                   "plugin_dispatched"):
        assert beweis in text, f"Live-Pruefung ohne {beweis}"
    assert text.index("Image live ansprechen") < text.index("Image veroeffentlichen"), \
        "veroeffentlicht, bevor geprueft wurde"


def test_the_notes_are_computed_from_the_manifest_in_the_workflow():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/build_manifest.py --pruefen" in text
    assert "scripts/release_notes.py" in text
    assert "--notes-file" in text, "Notiz nicht aus der gerechneten Datei"
