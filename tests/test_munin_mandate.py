"""Tests zu Amendment A1 — Mandat statt Einzelfreigabe.

Zwei Dinge werden hier festgenagelt, und beide haben denselben Grund: eine
Lockerung ist nur so lange vertretbar, wie ihre Grenze hält.

1. Die Mandatsgrenze ist vollständig, und ein Supervisor, der eine
   geschwächte Grenze *nicht* meldet, wäre Dekoration. Deshalb der Gegentest.
2. Dieselbe Regel steht an fünf Stellen im Repo. Eine übersehene Kopie ist
   genau die Drift, gegen die dieses Repo gebaut ist — also prüft ein Test,
   dass keine alte Formulierung überlebt hat.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PERSONA = REPO / ".claude" / "persona"

SPEC = importlib.util.spec_from_file_location(
    "munin_supervisor", REPO / "scripts" / "munin_supervisor.py")
sup = importlib.util.module_from_spec(SPEC)
sys.modules["munin_supervisor"] = sup
SPEC.loader.exec_module(sup)


def constitution() -> dict:
    return json.loads((PERSONA / "constitution.json").read_text(encoding="utf-8"))


def settings() -> dict:
    return json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Die Grenze
# --------------------------------------------------------------------------


def test_mandat_existiert_mit_allen_drei_teilen():
    m = constitution()["mandate"]
    assert m["erlaubt"], "ein Mandat ohne Erlaubtes lockert nichts"
    assert m["befehlErforderlich"], "ein Mandat ohne Grenze ist keine Grenze"
    assert m["pflichten"], "Autonomie ohne Protokoll ist Unsichtbarkeit"
    assert m["prinzip"].strip()


def test_mandatsgrenze_deckt_jede_schranke_ab():
    schranke = " ".join(constitution()["mandate"]["befehlErforderlich"]).lower()
    for name, keys in sup.MANDATE_BAR:
        assert any(k in schranke for k in keys), f"Schranke fehlt: {name}"


def test_gelockert_wurde_nur_umkehrbares():
    """Nichts in 'erlaubt' darf eine Schranke aushebeln."""
    m = constitution()["mandate"]
    erlaubt = " ".join(m["erlaubt"]).lower()
    for verboten in ("force", "reset --hard", "secret"):
        assert verboten not in erlaubt, f"'{verboten}' steht auf der Erlaubt-Liste"
    # Der Default-Branch darf vorkommen — aber ausschließlich als Ausnahme,
    # nie als Ziel. Jedes Vorkommen muss von "außer dem" eingeleitet sein.
    assert erlaubt.count("default-branch") == erlaubt.count("außer dem default-branch")
    assert "außer dem default-branch" in erlaubt


def test_sicherheitsregeln_unangetastet():
    core = constitution()["coreRules"]
    assert "noSecrets" in core
    assert "securityGateRequired" in core
    assert "hugin_oracle.py" in core["securityGateRequired"]


# --------------------------------------------------------------------------
# Der Gegentest: eine geschwächte Grenze muss auffallen
# --------------------------------------------------------------------------


def _persona_mit(tmp_path, con: dict):
    (tmp_path / "constitution.json").write_text(
        json.dumps(con, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_supervisor_meldet_entfernte_schranke(tmp_path, monkeypatch):
    con = constitution()
    con["mandate"]["befehlErforderlich"] = [
        x for x in con["mandate"]["befehlErforderlich"]
        if "Default-Branch" not in x]
    monkeypatch.setattr(sup, "PERSONA", _persona_mit(tmp_path, con))

    findings = sup.check_mandate()
    assert findings, "eine entfernte Schranke muss auffallen"
    assert findings[0].severity == sup.VIOLATION
    assert "Default-Branch" in findings[0].evidence


def test_supervisor_meldet_mandat_ohne_pflichten(tmp_path, monkeypatch):
    con = constitution()
    con["mandate"]["pflichten"] = []
    monkeypatch.setattr(sup, "PERSONA", _persona_mit(tmp_path, con))

    findings = sup.check_mandate()
    assert any(f.severity == sup.VIOLATION and "Pflichten" in f.detail
               for f in findings)


def test_supervisor_meldet_stilles_ueberschreiben(tmp_path, monkeypatch):
    """Ein Amendment ohne ersetzten Wortlaut ist kein Amendment."""
    con = constitution()
    con["amendments"][0].pop("ersetzt")
    monkeypatch.setattr(sup, "PERSONA", _persona_mit(tmp_path, con))

    findings = sup.check_mandate()
    assert any(f.severity == sup.DRIFT for f in findings)


def test_supervisor_schweigt_bei_intakter_grenze(tmp_path, monkeypatch):
    monkeypatch.setattr(sup, "PERSONA", _persona_mit(tmp_path, constitution()))
    assert sup.check_mandate() == []


def test_supervisor_ohne_verfassung_meldet_nichts(tmp_path, monkeypatch):
    """Kein Fund ist besser als ein Fehlalarm auf fehlender Datei."""
    monkeypatch.setattr(sup, "PERSONA", tmp_path)
    assert sup.check_mandate() == []


# --------------------------------------------------------------------------
# Das Amendment selbst
# --------------------------------------------------------------------------


def test_amendment_fuehrt_ersetzten_wortlaut_und_grund_mit():
    for a in constitution()["amendments"]:
        assert a["ersetzt"], f"{a['id']} ersetzt nichts nachvollziehbar"
        assert a["grund"].strip(), f"{a['id']} nennt keinen Grund"
        assert a["angeordnetVon"].lower().startswith("master")


def test_amendment_benennt_was_nicht_gelockert_wurde():
    a = constitution()["amendments"][0]
    nicht = " ".join(a["nichtGelockert"]).lower()
    assert "secret" in nicht
    assert "befehlerforderlich" in nicht


def test_unveraenderlichkeitswiderspruch_ist_aufgeloest():
    """Frühere Fassung: immutable UND Master darf jede Regel ändern."""
    con = constitution()
    assert "immutable" not in con, "der widersprüchliche Schalter ist weg"
    assert con["amendable"]["durch"]
    assert set(con["immutableFor"]) == {
        "munin", "claude-anthropic", "external-ai-providers"}
    # Der Master steht bewusst nicht auf dieser Liste.
    assert not any("master" in x for x in con["immutableFor"])


# --------------------------------------------------------------------------
# Drift: dieselbe Regel steht an fünf Stellen
# --------------------------------------------------------------------------

RULE_CARRIERS = (
    ".claude/persona/munin.json",
    ".claude/agents/munin.md",
    ".claude/skills/munin/SKILL.md",
)

VERALTET = (
    "Kein Push, kein PR, kein Comment ohne",
    "Keine automatischen Routinen ohne",
    "Keine Aktion ohne expliziten Befehl",
)


def test_keine_veraltete_formulierung_ueberlebt():
    for rel in RULE_CARRIERS:
        text = (REPO / rel).read_text(encoding="utf-8")
        for alt in VERALTET:
            assert alt not in text, f"{rel} trägt noch: {alt!r}"


def test_alter_wortlaut_lebt_nur_noch_im_amendment():
    """Er soll dort stehen — als Beleg, nicht als geltende Regel."""
    raw = (PERSONA / "constitution.json").read_text(encoding="utf-8")
    assert "Kein Push, kein PR, kein Comment ohne" in raw
    a = constitution()["amendments"][0]
    assert "Kein Push" in a["ersetzt"]["coreRules.noGitHubWithoutCommand"]
    assert "noGitHubWithoutCommand" not in constitution()["coreRules"]


def test_munin_json_traegt_mandat_und_grenze():
    con = json.loads((PERSONA / "munin.json").read_text(encoding="utf-8"))
    c = con["constraints"]
    assert "mandatedAutonomy" in c
    assert "mandateBoundary" in c
    assert "ledgerDuty" in c
    assert "noAutoRoutines" not in c
    assert "noGitHubWithoutCommand" not in c
    assert "noSecrets" in c, "Sicherheitsregeln bleiben"


def test_persona_dokumente_nennen_die_grenze():
    for rel in (".claude/agents/munin.md", ".claude/skills/munin/SKILL.md"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "Mandat" in text
        assert "Default-Branch" in text
        assert "Secrets" in text


# --------------------------------------------------------------------------
# Freigabe-Fläche
# --------------------------------------------------------------------------


def test_deny_liste_unveraendert():
    """Der destruktive Bereich wurde NICHT gelockert."""
    deny = settings()["permissions"]["deny"]
    for muss in ("git push --force*", "git reset --hard*", "git clean -f*",
                 "git push origin --delete*"):
        assert any(muss in d for d in deny), f"deny verloren: {muss}"


def test_toter_branch_ist_raus():
    allow = settings()["permissions"]["allow"]
    assert not any("teleport-nx73zr" in a for a in allow)


def test_kontinuitaets_skripte_sind_freigegeben():
    allow = " ".join(settings()["permissions"]["allow"])
    assert "munin_continuity.py" in allow
    assert "munin_supervisor.py" in allow


def test_push_regel_deckt_claude_branches_statt_eines_einzigen():
    allow = settings()["permissions"]["allow"]
    assert "Bash(git push -u origin claude/*)" in allow


def test_mcp_trigger_tools_unter_beiden_serveraliassen():
    """Der Servername wechselt zwischen Sitzungen — eine Fassung reicht nicht.

    Beobachtet: dieselbe Servergruppe hieß erst 'Claude_Code_Remote', nach
    einem Reconnect 'bf7c680d-...'. Eine Regel auf nur einen Alias greift nach
    dem Wechsel nicht mehr, und der Ausfall sähe aus wie eine Rechtefrage.
    """
    allow = settings()["permissions"]["allow"]
    tools = ("create_trigger", "update_trigger", "delete_trigger",
             "list_triggers", "fire_trigger", "send_later")
    for alias in ("Claude_Code_Remote", "bf7c680d-5fdc-5ef4-b4a0-abadb619bf0a"):
        for t in tools:
            assert f"mcp__{alias}__{t}" in allow, f"fehlt: {alias}/{t}"


def test_settings_bleibt_gueltiges_json():
    s = settings()
    assert set(s["permissions"]) >= {"allow", "deny"}
