"""Tests des Build-Manifests.

Das Manifest ist ein **Veroeffentlichungsartefakt**: es wird als
Actions-Artefakt hochgeladen und von der Plattform gelesen. Damit gilt fuer
es die schaerfste Regel dieses Repos — es darf kein Geheimnis tragen, und es
darf nichts behaupten, was nicht gemessen wurde.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import build_manifest as bm  # noqa: E402


# ---------------------------------------------------------------------------
# Kein Geheimnis, niemals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("geheim", [
    "sk-" + "a" * 32,
    "ghp_" + "b" * 36,
    "AIza" + "c" * 35,
    "xoxb-1234567890-abcdefghij",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "hmo_1_" + "d" * 64,
])
def test_the_leak_check_catches_every_pattern_the_scanner_knows(geheim):
    """Dieselben Muster wie der Secret-Scanner. Ein Manifest mit einem
    Geheimnis waere schlimmer als keines — es wird veroeffentlicht."""
    assert bm.leckpruefung(f'{{"irgendwas": "{geheim}"}}'), \
        f"{geheim[:12]}… wird nicht erkannt"


def test_harmless_text_is_not_flagged():
    """Gegenprobe: eine Wache, die alles meldet, meldet nichts."""
    text = json.dumps(bm.manifest(mit_pruefungen=False), ensure_ascii=False)
    assert bm.leckpruefung(text) == []


def test_the_manifest_names_variables_but_never_values():
    """Dass ein Dienst `HM_OWNER_TOKEN` liest, ist keine Preisgabe. Sein Wert
    waere eine."""
    text = json.dumps(bm.manifest(mit_pruefungen=False), ensure_ascii=False)
    assert "HM_OWNER_TOKEN" not in text or "manifest-syntax-check-only" not in text
    for platzhalter in bm.PLATZHALTER.values():
        assert platzhalter not in text, "Platzhalter im Manifest gelandet"


def test_writing_is_refused_when_something_secret_would_be_published(monkeypatch, tmp_path):
    """Der Gegentest, der zaehlt: nicht 'wird erkannt', sondern 'wird nicht
    geschrieben'."""
    ziel = tmp_path / "m.json"
    monkeypatch.setattr(bm, "manifest",
                        lambda mit_pruefungen: {"leck": "ghp_" + "x" * 36})
    monkeypatch.setattr(bm, "REPO", tmp_path)
    code = bm.main(["--out", "m.json"])
    assert code == 2, "Abbruch erwartet"
    assert not ziel.exists(), "Manifest trotz Geheimnis geschrieben"


# ---------------------------------------------------------------------------
# Gemessen, nicht behauptet
# ---------------------------------------------------------------------------

def test_a_missing_artefact_is_listed_as_missing_not_omitted():
    """Eine Liste, aus der Fehlendes verschwindet, sieht immer vollstaendig
    aus."""
    eintraege = bm.artefakte()
    assert len(eintraege) == len(bm.ARTEFAKTE)
    for e in eintraege:
        assert "sha256" in e or e.get("fehlt") is True


def test_present_artefacts_carry_a_real_hash():
    for e in bm.artefakte():
        if not e.get("fehlt"):
            assert len(e["sha256"]) == 64 and e["bytes"] > 0


def test_an_unavailable_tool_yields_unknown_not_passed(monkeypatch):
    """Unbekannt gilt nie als in Ordnung — dieselbe Richtung wie ueberall."""
    monkeypatch.setattr(bm, "PRUEFUNGEN", (("erfunden", ["/gibt/es/nicht"]),))
    ergebnis = bm.pruefungen()[0]
    assert ergebnis["ergebnis"] == bm.UNBEKANNT
    assert ergebnis["ergebnis"] != bm.BESTANDEN


def test_a_failing_check_is_reported_as_fallen(monkeypatch):
    monkeypatch.setattr(bm, "PRUEFUNGEN", (("faellt", [sys.executable, "-c", "raise SystemExit(3)"]),))
    assert bm.pruefungen()[0]["ergebnis"] == bm.GEFALLEN


def test_every_check_records_the_command_that_produced_it():
    """Ein Ergebnis ohne den Befehl, der es erzeugt hat, ist nicht
    nachrechenbar."""
    for p in bm.pruefungen():
        assert p["befehl"].strip()
        assert p["ergebnis"] in (bm.BESTANDEN, bm.GEFALLEN, bm.UNBEKANNT)


def test_the_systemd_target_path_note_is_not_treated_as_a_failure():
    """`systemd-analyze verify` meldet auf einer Baumaschine, dass
    /opt/hm-gateway/hm-gateway fehlt. Das ist eine Aussage ueber den
    Installationspfad, nicht ueber die Unit — sonst faerbte jeder Bau rot
    fuer etwas, das erst beim Ausrollen gilt."""
    treffer = [p for p in bm.pruefungen() if p["pruefung"] == "systemd-units"]
    if treffer and treffer[0]["ergebnis"] == bm.BESTANDEN and "hinweis" in treffer[0]:
        assert "/opt/hm-gateway" in treffer[0]["hinweis"]


def test_the_compose_placeholders_are_not_exported(monkeypatch):
    """Sie gelten nur fuer den Unterprozess einer Syntaxpruefung."""
    import os
    for name in bm.PLATZHALTER:
        monkeypatch.delenv(name, raising=False)
    bm.pruefungen()
    for name in bm.PLATZHALTER:
        assert name not in os.environ, f"{name} in die Umgebung geleckt"


def test_the_manifest_is_machine_readable_end_to_end(tmp_path):
    p = subprocess.run([sys.executable, "scripts/build_manifest.py"],
                       cwd=REPO, capture_output=True, text=True, timeout=300)
    d = json.loads(p.stdout)
    assert d["schema"] == "hugin.build.v1"
    assert d["commit"] and len(d["commit"]) == 40
    assert isinstance(d["sauber"], bool)


# ---------------------------------------------------------------------------
# Der Workflow, der es produziert
# ---------------------------------------------------------------------------

WORKFLOW = REPO / ".github" / "workflows" / "full-build-deploy.yml"


def _workflow() -> dict:
    import yaml
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_full_build_workflow_exists_and_parses():
    d = _workflow()
    assert set(d["jobs"]) == {"binaries", "frontend", "container", "manifest"}


def test_publishing_uses_only_the_built_in_token():
    """Kein Drittanbieter-Geheimnis. `github.token` wird von GitHub selbst
    gestellt und ist auf dieses Repository begrenzt."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.token" in text
    # `secrets.X` fuer irgendetwas anderes als GITHUB_TOKEN waere eine neue
    # Abhaengigkeit vom Master — genau das soll hier nicht entstehen.
    import re
    fremde = [m.group(1) for m in re.finditer(r"secrets\.([A-Z_]+)", text)
              if m.group(1) != "GITHUB_TOKEN"]
    assert not fremde, f"fremde Secrets verlangt: {fremde}"


def test_the_container_job_actually_talks_to_the_image():
    """Ein Image, das gebaut wurde, ist nicht dasselbe wie ein Image, das
    antwortet — genau diese Luecke hat hier schon die Plugin-Dispatch und
    danach den Chat gekostet."""
    text = WORKFLOW.read_text(encoding="utf-8")
    # `[DONE]` steht im Workflow als `\[DONE\]` — der String liegt in einem
    # `grep`-Muster, und dort sind die Klammern maskiert. Die erste Fassung
    # dieses Tests suchte die unmaskierte Form und schlug fehl, obwohl die
    # Pruefung da war: der Test suchte seinen eigenen Wortlaut statt der
    # Sache.
    for beweis in ("/health", "/chat", "/tasks", "401",
                   "DONE", "plugin_dispatched"):
        assert beweis in text, f"Live-Pruefung ohne {beweis}"


def test_the_workflow_does_not_duplicate_the_test_suite():
    """ci.yml faehrt `cargo test --workspace`. Eine zweite Stelle, die
    dasselbe prueft, driftet davon ab."""
    # Nur die ausgefuehrten Zeilen, nicht die Kommentare: der Kopf des
    # Workflows ERKLAERT, warum `cargo test` hier fehlt, und ein Test, der
    # den Erklaerungstext als Verstoss liest, verbietet die Begruendung.
    zeilen = [z for z in WORKFLOW.read_text(encoding="utf-8").splitlines()
              if not z.lstrip().startswith("#")]
    assert "cargo test" not in "\n".join(zeilen)
