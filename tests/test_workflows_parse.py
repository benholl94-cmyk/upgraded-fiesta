"""Jede Workflow-Datei muss gültiges YAML sein.

**Warum das nötig ist.** `munin-link-hourly.yml` enthielt

    run: python3 ... broadcast "CI-Scheduler: stündlicher Status-Check"

Das ist ungültiges YAML: der Wert hinter `run:` ist ein *plain scalar*, die
Anführungszeichen stehen darin statt ihn zu begrenzen, und ein ``": "``
innerhalb eines plain scalar liest YAML als Mapping-Trenner.

GitHub konnte die Datei deshalb nicht parsen und hat den Workflow **nie
gestartet**: ``total_jobs: 0``, ``conclusion: failure``. Weil ungültige
Workflow-Dateien auch bei `push` validiert werden, geschah das bei jedem Push
auf jeden Branch erneut — auf `main` ebenso wie auf Feature-Branches.

Der eigentliche Grund für diesen Test ist aber nicht der Syntaxfehler, sondern
seine **Unsichtbarkeit**: dieser Workflow hängt an keinem Pull Request. Eine
Abfrage der PR-Checks meldete „alles grün", während er stündlich scheiterte.
Wer nur dort nachsieht, wo Ergebnisse angezeigt werden, prüft nicht das System,
sondern seine eigene Auswahl. `pytest` läuft in CI und an jedem PR — hier ist
der Fehler sichtbar, wo er vorher keinen Ort hatte.

Der Test prüft nur, was er prüfen kann: dass die Datei *parst*. Ob die Schritte
darin fachlich richtig sind, sagt er nicht — das wäre eine Behauptung, die er
nicht belegen kann.
"""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="PyYAML fehlt — ohne Parser ist diese Prüfung nicht durchführbar",
)

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO / ".github" / "workflows"

WORKFLOWS = sorted(
    list(WORKFLOW_DIR.glob("*.yml")) + list(WORKFLOW_DIR.glob("*.yaml"))
)


def test_there_are_workflows_to_check():
    """Gegenprobe gegen einen Test, der still nichts prüft.

    Ohne diese Zusicherung wäre eine leere oder umbenannte
    Workflow-Verzeichnisstruktur ein grüner Lauf über null Dateien — genau
    die Sorte leeres Ergebnis, die wie ein bestandener Test aussieht.
    """
    assert WORKFLOW_DIR.is_dir(), f"{WORKFLOW_DIR} fehlt"
    assert len(WORKFLOWS) >= 10, (
        f"nur {len(WORKFLOWS)} Workflow-Dateien gefunden — Verzeichnis "
        "umbenannt oder Glob falsch?"
    )


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_parseable_yaml(path: pathlib.Path):
    """Die Regression: GitHub startet eine unparsebare Datei gar nicht erst."""
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        wo = f"Zeile {mark.line + 1}, Spalte {mark.column + 1}" if mark else "unbekannt"
        pytest.fail(
            f"{path.name} ist kein gültiges YAML: "
            f"{getattr(error, 'problem', error)} ({wo}).\n"
            "GitHub startet eine solche Datei nicht — der Lauf erscheint als "
            "'failure' mit null Jobs. Häufigste Ursache: ein ': ' in einem "
            "unquotierten Wert; `run: |` als Block-Skalar löst das."
        )
    assert isinstance(loaded, dict), f"{path.name} enthält kein Mapping"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_declares_a_trigger_and_at_least_one_job(path: pathlib.Path):
    """Ein Workflow ohne Trigger oder ohne Job läuft nie und sagt es nicht.

    `on` wird von YAML 1.1 als Boolean `True` gelesen — deshalb wird beides
    geprüft, sonst meldet der Test einen fehlenden Trigger, der da ist.
    """
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    trigger = doc.get("on", doc.get(True))
    assert trigger, f"{path.name} deklariert keinen Trigger"
    jobs = doc.get("jobs")
    assert isinstance(jobs, dict) and jobs, f"{path.name} deklariert keine Jobs"
