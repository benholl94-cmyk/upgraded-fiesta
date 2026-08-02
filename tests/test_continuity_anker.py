"""Anker des Gedaechtnisses — was verrottet, und was nie halten konnte.

Drei Anker liefen ins Leere. Sie hatten **zwei verschiedene Wurzeln**, und
nur eine war ein Verlust:

* `s3-19 → path:.github/workflows` — ein **Messfehler**. Der Pruefer fragte
  `is_file()`, der Anker zeigt auf ein Verzeichnis, und das Verzeichnis lag
  die ganze Zeit da. Ein falscher Rot-Befund ist teurer als keiner: er
  trainiert das Weglesen.
* `s4-3`/`s4-4 → sha:b724047` — **echt tot**, aber nicht verrottet: der SHA
  stammte vom Branch zu PR #106. Beim Squash-Merge entsteht ein neuer
  Commit, der alte wird unerreichbar. Der Anker konnte in diesem Workflow
  nie halten.

Die Lehre steckt in der zweiten Zeile: **nicht jeder tote Anker ist Drift.
Manche waren beim Anlegen schon zum Tod verurteilt** — und dagegen hilft
keine Reparatur, sondern eine Warnung zum richtigen Zeitpunkt.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import munin_continuity as mc  # noqa: E402

LEDGER = REPO / ".claude" / "continuity" / "ledger.json"


def test_a_directory_anchor_is_valid():
    """`s3-19` haelt eine Sackgasse ueber `.github/workflows` als Ganzes
    fest — der OAuth-Token des Codespace hat keinen workflow-Scope, das
    betrifft jede Datei darin und keine einzelne."""
    status, detail = mc.verify_anchor("path:.github/workflows")
    assert status == "ok", detail


def test_a_missing_path_is_still_reported():
    """Gegenprobe: `exists()` statt `is_file()` darf die Wache nicht
    stumpf machen."""
    status, _ = mc.verify_anchor("path:gibt/es/nicht/xyz")
    assert status == "rot"


def test_a_line_anchor_still_resolves():
    status, detail = mc.verify_anchor("path:scripts/munin_continuity.py:1")
    assert status == "ok", detail


def test_a_dead_sha_names_the_squash_cause():
    """Ein Befund ohne Ursache ist eine Beschwerde. Wer `Commit nicht im
    Repo` liest, sucht; wer die Ursache liest, ankert um."""
    status, detail = mc.verify_anchor("sha:b724047")
    assert status == "rot"
    assert "Squash" in detail and "umankern" in detail


def test_an_ephemeral_sha_is_flagged_at_capture_time():
    """**Die Wurzel, nicht das Symptom.** Gewarnt wird beim Schreiben, wo
    der Autor den Anker noch ersetzen kann — beim Verify ist der Commit
    schon weg und niemand weiss mehr, worauf er zeigte."""
    kopf = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                          capture_output=True, text=True, timeout=60).stdout.strip()
    auf_main = subprocess.run(
        ["git", "merge-base", "--is-ancestor", kopf, "origin/main"],
        cwd=REPO, capture_output=True, timeout=60).returncode == 0
    assert mc._fluechtiger_sha(f"sha:{kopf}") is (not auf_main)


def test_a_sha_on_the_default_branch_is_not_flagged():
    """Gegenprobe: sonst warnte die Wache immer und wuerde ueberlesen."""
    r = subprocess.run(["git", "rev-parse", "--short", "origin/main"], cwd=REPO,
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 0 and r.stdout.strip():
        assert not mc._fluechtiger_sha(f"sha:{r.stdout.strip()}")


def test_a_nonexistent_sha_is_not_called_ephemeral():
    """Ein Commit, den es nicht gibt, ist ein Fall fuer `verify_anchor` —
    zwei Meldungen fuer dieselbe Sache waeren eine Doppelung."""
    assert not mc._fluechtiger_sha("sha:0000000")


def test_no_anchor_in_the_ledger_points_into_the_void():
    """**Das Ziel, maschinell nachgerechnet.** Faellt dieser Test, ist ein
    Anker verrottet — und dann soll er fallen."""
    d = json.loads(LEDGER.read_text(encoding="utf-8"))
    rot = []
    for e in d.get("entries", []):
        for an in e.get("anchors", ()):
            status, detail = mc.verify_anchor(an)
            if status == "rot":
                rot.append(f"{e.get('id')} → {an} ({detail})")
    assert not rot, rot
