"""Tests der Modell-Beschaffung und Erdung.

Zwei Dinge muessen stimmen, sonst antwortet das System zuversichtlich falsch:
die Datei muss die sein, die gepinnt wurde, und der Prompt muss die Belege
tragen, auf die er sich beruft.
"""
from __future__ import annotations
import hashlib, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
import hugin_model as hm

REPO = pathlib.Path(__file__).resolve().parents[1]


def test_pinning_is_complete():
    u = hm.config()["upstream"]
    for k in ("repo", "file", "revision", "sha256", "license", "attribution"):
        assert u.get(k), f"{k} fehlt in der Pinnung"
    assert len(u["sha256"]) == 64


def test_attribution_is_preserved_for_apache_license():
    """Apache-2.0 erlaubt den Rebrand, verlangt aber die Urheberangabe.
    Ein Rebrand der sie loescht waere lizenzwidrig."""
    u = hm.config()["upstream"]
    assert u["license"] == "Apache-2.0"
    assert "JetBrains" in u["attribution"]


def test_url_points_at_the_pinned_revision():
    u = hm.config()["upstream"]
    url = hm.url()
    assert u["repo"] in url and u["file"] in url and u["revision"] in url


def test_rejection_reasons_are_recorded():
    """Warum NICHT das groessere Modell — sonst fragt die naechste Sitzung
    wieder und misst erneut."""
    v = hm.config()["auswahl"]["verworfen"]
    assert v and all(x.get("grund") and x.get("groesse_gb") for x in v)


def test_verify_detects_wrong_content(tmp_path):
    f = tmp_path / "falsch.gguf"
    f.write_bytes(b"nicht das modell")
    ok, msg = hm.verify(f)
    assert not ok and "weicht ab" in msg


def test_verify_reports_missing_file(tmp_path):
    ok, msg = hm.verify(tmp_path / "gibtsnicht.gguf")
    assert not ok and "existiert nicht" in msg


def test_verify_accepts_matching_content(tmp_path, monkeypatch):
    f = tmp_path / "ok.gguf"
    f.write_bytes(b"inhalt")
    digest = hashlib.sha256(b"inhalt").hexdigest()
    cfg = json.loads(hm.CONFIG.read_text())
    cfg["upstream"]["sha256"] = digest
    p = tmp_path / "model.json"
    p.write_text(json.dumps(cfg))
    monkeypatch.setattr(hm, "CONFIG", p)
    ok, _ = hm.verify(f)
    assert ok


def test_grounded_prompt_carries_evidence():
    """Der eigentliche Rebrand: die Antwort steht auf Repo-Belegen."""
    out = hm.grounded_prompt("Ungepushten Commit im Container liegen lassen")
    assert "BELEGE" in out and "ungepusht" in out.lower()
    assert "AUFGABE:" in out


def test_grounded_prompt_says_so_when_nothing_is_proven():
    """Ohne Praezedenzfall muss der Prompt das ausdruecklich sagen — sonst
    fuellt das Modell die Luecke mit Allgemeinwissen."""
    out = hm.grounded_prompt("voellig unverwandtes thema quantenchemie xyzzy")
    assert "keine" in out.lower() and "Praezedenzfall" in out


def test_system_prompt_forbids_invention():
    assert "erfinde nichts" in hm.SYSTEM.lower()
    assert "invariante" in hm.SYSTEM.lower()


def test_grammar_constrains_to_the_schema():
    g = hm.GRAMMAR
    for token in ("status", "antwort", "belegt_durch", "nicht_belegt", "verweigert"):
        assert token in g


def test_model_blob_is_not_tracked():
    """6,6 GB in git laegen in jedem Clone fuer immer."""
    import subprocess
    out = subprocess.run(["git", "ls-files"], cwd=REPO,
                         capture_output=True, text=True).stdout
    assert ".gguf" not in out
