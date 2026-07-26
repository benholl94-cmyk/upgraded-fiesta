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


def test_persona_lives_in_config_not_in_code():
    """Die Regelschicht gehoert dem Master. Steht sie im Skript, kann er sie
    nur aendern indem er den Code aendert — das waere eine Auferlegung."""
    src = pathlib.Path(hm.__file__).read_text(encoding="utf-8")
    assert "SYSTEM =" not in src
    assert hm.PERSONA.is_file()
    p = hm.persona()
    assert p["regeln"] and all("aktiv" in r and "quelle" in r for r in p["regeln"])


def test_active_rules_reach_the_prompt():
    txt = hm.system_text()
    aktive = [r["text"] for r in hm.persona()["regeln"] if r["aktiv"]]
    assert aktive, "keine Regel aktiv — dann trifft dieser Test nichts"
    for t in aktive:
        assert t in txt


def test_all_rules_off_yields_a_raw_model():
    """Der entscheidende Fall: sind alle Regeln aus, bleibt kein Satz uebrig.
    Kein Restsatz, der sich durch das Abschalten hindurch behauptet."""
    p = {"identitaet": {"aktiv": False, "text": "x"},
         "regeln": [{"id": "a", "aktiv": False, "text": "y"}]}
    assert hm.system_text(p) == ""


def test_disabled_rule_is_absent_not_merely_weakened():
    p = hm.persona()
    for r in p["regeln"]:
        r["aktiv"] = False
    txt = hm.system_text(p)
    for r in hm.persona()["regeln"]:
        assert r["text"] not in txt


def test_persona_is_never_written_by_the_script():
    """Nur lesen. Ein Skript das die Regeln des Masters zurueckschreibt,
    besitzt sie faktisch."""
    before = hm.PERSONA.read_bytes()
    hm.grounded_prompt("irgendeine frage")
    assert hm.PERSONA.read_bytes() == before


def test_grounding_can_be_switched_off(monkeypatch):
    """Erdung aus -> keine Belege, kein Ohne-Beleg-Hinweis. Dann ist es ein
    beliebiges 12B-Modell, und das ist eine zulaessige Wahl des Masters."""
    p = hm.persona()
    p["erdung"] = {"aktiv": False}
    p["regeln"] = []
    p["identitaet"] = {"aktiv": False}
    monkeypatch.setattr(hm, "persona", lambda: p)
    out = hm.grounded_prompt("Ungepushten Commit im Container liegen lassen")
    assert "BELEGE" not in out
    assert out.strip() == "AUFGABE: Ungepushten Commit im Container liegen lassen"


def test_no_rule_originates_from_a_vendor_policy():
    """Jede Regel nennt ihre Herkunft, und keine ist meine."""
    for r in hm.persona()["regeln"]:
        assert r["quelle"], f"{r['id']} ohne Quelle"
        assert "anthropic" not in r["quelle"].lower()


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
