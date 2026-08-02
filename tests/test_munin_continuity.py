"""Tests für scripts/munin_continuity.py.

Der Schwerpunkt liegt auf der Verdichtung, weil dort der Schaden entstünde:
ein Kompaktierer, der *fast* richtig arbeitet, verliert still offene Arbeit
und sieht dabei aus wie ein funktionierendes Gedächtnis. Genau dieser Fall --
etwas ist weg und niemand merkt es -- ist der Grund für das Modul.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "munin_continuity", REPO / "scripts" / "munin_continuity.py")
mc = importlib.util.module_from_spec(SPEC)
sys.modules["munin_continuity"] = mc
SPEC.loader.exec_module(mc)


def entry(eid: str, session: int, kind: str, *, state: str = "offen",
          weight: int = 1, anchors=None, text: str = "x") -> "mc.Entry":
    return mc.Entry(id=eid, session=session, ts="2026-07-26T00:00:00+00:00",
                    kind=kind, text=text, anchors=list(anchors or []),
                    state=state, weight=weight)


def ledger(session: int, entries) -> "mc.Ledger":
    return mc.Ledger(version=1, updated="2026-07-26T00:00:00+00:00",
                     session=session, entries=list(entries))


# --------------------------------------------------------------------------
# Generationen
# --------------------------------------------------------------------------


def test_generation_grenzen():
    led = ledger(10, [])
    assert led.generation(entry("a", 10, "notiz")) == mc.HOT
    assert led.generation(entry("b", 8, "notiz")) == mc.HOT     # Alter 2
    assert led.generation(entry("c", 7, "notiz")) == mc.WARM    # Alter 3
    assert led.generation(entry("d", 2, "notiz")) == mc.WARM    # Alter 8
    assert led.generation(entry("e", 1, "notiz")) == mc.COLD    # Alter 9


def test_gen0_bleibt_woertlich():
    """Die heiße Generation wird nicht angefasst -- auch Erledigtes nicht."""
    led = ledger(10, [entry("a", 10, "notiz", state="erledigt"),
                      entry("b", 9, "offen", state="erledigt")])
    mc.compact(led)
    assert {e.id for e in led.entries} == {"a", "b"}


def test_gen1_wirft_nur_ab_was_git_haelt():
    led = ledger(10, [
        entry("erledigt-offen", 5, "offen", state="erledigt"),
        entry("erledigt-notiz", 5, "notiz", state="erledigt"),
        entry("offen-offen", 5, "offen"),
        entry("entscheidung", 5, "entscheidung", state="erledigt"),
        entry("sackgasse", 5, "sackgasse"),
    ])
    mc.compact(led)
    ids = {e.id for e in led.entries}
    # Erledigte Fragen und Notizen stehen in der History; alles andere nicht.
    assert "erledigt-offen" not in ids
    assert "erledigt-notiz" not in ids
    assert ids == {"offen-offen", "entscheidung", "sackgasse"}


def test_gen2_behaelt_nur_das_nicht_ableitbare():
    led = ledger(30, [
        entry("inv", 1, "invariante"),
        entry("off", 1, "offen"),
        entry("sack", 1, "sackgasse"),
        entry("ent-schwer", 1, "entscheidung", weight=2),
        entry("ent-leicht", 1, "entscheidung", weight=1),
        entry("notiz", 1, "notiz"),
    ])
    mc.compact(led)
    assert {e.id for e in led.entries} == {"inv", "off", "sack", "ent-schwer"}


# --------------------------------------------------------------------------
# Budget -- die Stelle, an der stilles Vergessen entstünde
# --------------------------------------------------------------------------


def test_budget_verdraengt_niemals_offenes_oder_invarianten():
    """Der Kern. Lieber Budget reißen als offene Arbeit verlieren."""
    lang = "y" * 400
    led = ledger(1, [entry(f"off{i}", 1, "offen", text=lang) for i in range(20)]
                 + [entry(f"inv{i}", 1, "invariante", text=lang) for i in range(20)])
    log, within = mc.compact(led, budget=500)

    assert not within, "Budget muss als gerissen gemeldet werden"
    assert len(led.entries) == 40, "nichts Unverzichtbares darf fallen"
    assert any("Budget" in line and "überschritten" in line for line in log)


def test_budget_verdraengt_geringwertiges_zuerst():
    lang = "y" * 300
    led = ledger(1, [
        entry("offen", 1, "offen", text=lang),
        entry("sackgasse", 1, "sackgasse", text=lang),
        entry("entscheidung", 1, "entscheidung", text=lang),
        entry("notiz", 1, "notiz", text=lang),
    ])
    # Platz für ungefähr zwei Einträge.
    mc.compact(led, budget=900)
    ids = {e.id for e in led.entries}
    assert "offen" in ids, "Offenes geht nie"
    assert "notiz" not in ids, "Notizen gehen zuerst"
    # Sackgasse steht über Entscheidung: was gescheitert ist, steht in keinem
    # Commit und wäre sonst unwiederbringlich.
    if "entscheidung" in ids:
        assert "sackgasse" in ids


def test_budget_eingehalten_meldet_erfolg():
    led = ledger(1, [entry("a", 1, "notiz")])
    _, within = mc.compact(led, budget=mc.DEFAULT_BUDGET)
    assert within
    assert led.size <= mc.DEFAULT_BUDGET


def test_verdichtung_ist_idempotent():
    led = ledger(30, [entry("inv", 1, "invariante"),
                      entry("notiz", 1, "notiz"),
                      entry("off", 29, "offen")])
    mc.compact(led)
    erste = {e.id for e in led.entries}
    mc.compact(led)
    assert {e.id for e in led.entries} == erste


def test_texte_werden_nicht_abgeschnitten():
    """Verdichtet wird über ganze Einträge, nie über halbe Sätze."""
    text = "Ein vollständiger Satz, der seine Bedeutung nur ganz behält."
    led = ledger(30, [entry("inv", 1, "invariante", text=text)])
    mc.compact(led, budget=10)
    assert led.entries[0].text == text


# --------------------------------------------------------------------------
# Anker
# --------------------------------------------------------------------------


def test_anker_auf_existierende_datei_traegt():
    status, _ = mc.verify_anchor("path:scripts/munin_continuity.py")
    assert status == "ok"


def test_anker_auf_fehlende_datei_ist_rot():
    status, detail = mc.verify_anchor("path:scripts/gibt_es_nicht_12345.py")
    assert status == "rot"
    assert "existiert nicht" in detail


def test_anker_auf_zeile_hinter_dateiende_ist_rot():
    status, detail = mc.verify_anchor("path:scripts/munin_continuity.py:999999")
    assert status == "rot"
    assert "Zeile" in detail


def test_anker_auf_gueltige_zeile_traegt():
    status, _ = mc.verify_anchor("path:scripts/munin_continuity.py:10")
    assert status == "ok"


def test_anker_auf_erfundenen_commit_gilt_nie_als_gesund():
    """Ein erfundener Commit darf **nie** als geprueft durchgehen.

    Die vorige Fassung verlangte genau `rot`. Das war eine Beschriftung,
    keine Eigenschaft: in einem **flachen Klon** (CI checkt mit
    `fetch-depth: 1` aus) ist ein unaufloesbarer SHA nicht entscheidbar und
    heisst darum `extern` — dieselbe dritte Kategorie wie in
    `hugin_clarity.py`. Der Test fiel damit auf dem Runner, obwohl die
    Wache genau richtig arbeitete.

    Zugesichert wird deshalb, worauf es ankommt: nicht `ok`. In einem
    vollen Klon bleibt es `rot`, und das ist die schaerfere Aussage.
    """
    status, detail = mc.verify_anchor("sha:" + "0" * 40)
    assert status != "ok", detail
    assert status in ("rot", "extern")
    flach = mc.git("rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    if not flach:
        assert status == "rot", "im vollen Klon ist die Aussage sicher"


def test_nicht_pruefbarer_anker_heisst_extern_nicht_ok():
    """'Ich kann es nicht prüfen' darf nie als 'geprüft' durchgehen."""
    status, _ = mc.verify_anchor("pr:78")
    assert status == "extern"


def test_verify_meldet_nur_die_kaputten():
    led = ledger(1, [
        entry("gut", 1, "offen", anchors=["path:scripts/munin_continuity.py"]),
        entry("kaputt", 1, "offen", anchors=["path:nichts_da_98765.txt"]),
    ])
    rotten = mc.verify(led)
    assert [e.id for e, *_ in rotten] == ["kaputt"]


# --------------------------------------------------------------------------
# Ledger-Mechanik
# --------------------------------------------------------------------------


def test_roundtrip_erhaelt_alles():
    led = ledger(7, [entry("a", 7, "sackgasse", anchors=["sha:abc"], weight=3)])
    wieder = mc.Ledger(
        **{**json.loads(led.to_json()),
           "entries": [mc.Entry.from_dict(e)
                       for e in json.loads(led.to_json())["entries"]]})
    assert wieder.session == 7
    assert wieder.entries[0].anchors == ["sha:abc"]
    assert wieder.entries[0].weight == 3
    assert wieder.entries[0].kind == "sackgasse"


def test_ids_sind_innerhalb_einer_sitzung_eindeutig():
    led = ledger(3, [])
    vergeben = set()
    for _ in range(5):
        eid = led.next_id()
        assert eid not in vergeben
        vergeben.add(eid)
        led.entries.append(entry(eid, 3, "notiz"))
    assert vergeben == {"s3-1", "s3-2", "s3-3", "s3-4", "s3-5"}


def test_kaputtes_ledger_wird_gemeldet_nicht_ueberschrieben(tmp_path, monkeypatch):
    """Ein zweiter Datenverlust wäre, das Unlesbare einfach zu ersetzen."""
    p = tmp_path / "ledger.json"
    p.write_text("{kein json", encoding="utf-8")
    monkeypatch.setattr(mc, "LEDGER_F", p)
    with pytest.raises(SystemExit):
        mc.Ledger.load()
    assert p.read_text(encoding="utf-8") == "{kein json"


def test_fehlendes_ledger_ist_leer_kein_fehler(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "LEDGER_F", tmp_path / "gibtsnicht.json")
    led = mc.Ledger.load()
    assert led.entries == []
    assert led.session == 1


def test_undroppable_nur_solange_offen():
    assert not entry("a", 1, "offen").droppable
    assert not entry("b", 1, "invariante").droppable
    assert entry("c", 1, "offen", state="erledigt").droppable
    assert entry("d", 1, "notiz").droppable


# --------------------------------------------------------------------------
# Der Übergabe-Prompt trägt die Schleife
# --------------------------------------------------------------------------


def test_handoff_prompt_nennt_den_ersten_und_den_letzten_schritt():
    p = mc.HANDOFF_PROMPT
    assert "munin_continuity.py resume" in p
    assert "seal --push" in p
    assert "compact" in p
    # Ohne diesen Satz wiederholt die Folgesitzung gescheiterte Versuche.
    assert "Sackgassen" in p


def test_handoff_prompt_erlaubt_die_leere_runde():
    """Ein Loop, der immer etwas tun muss, erfindet Arbeit."""
    assert "leere Runde" in mc.HANDOFF_PROMPT


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_capture_resolve_resume(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mc, "LEDGER_F", tmp_path / "ledger.json")

    assert mc.main(["capture", "--kind", "offen", "--text", "Gerätebindung"]) == 0
    led = mc.Ledger.load()
    assert led.entries[0].text == "Gerätebindung"

    assert mc.main(["resolve", led.entries[0].id]) == 0
    assert mc.Ledger.load().entries[0].state == "erledigt"

    capsys.readouterr()   # Ausgabe der vorherigen Befehle verwerfen
    mc.main(["resume", "--peek", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["entries"] == [], "Erledigtes gehört nicht in den Brief"


def test_cli_sackgasse_laesst_sich_nicht_schliessen(tmp_path, monkeypatch):
    """Eine Sackgasse bleibt sichtbar, sonst wird sie wieder betreten."""
    monkeypatch.setattr(mc, "LEDGER_F", tmp_path / "ledger.json")
    mc.main(["capture", "--kind", "sackgasse", "--text", "Weg X führt nirgendwo"])
    eid = mc.Ledger.load().entries[0].id
    assert mc.main(["resolve", eid]) == 1
    assert mc.Ledger.load().entries[0].state == "offen"


def test_cli_unbekannte_art_wird_abgelehnt(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "LEDGER_F", tmp_path / "ledger.json")
    with pytest.raises(SystemExit):
        mc.main(["capture", "--kind", "quatsch", "--text", "x"])


def test_resume_erhoeht_sitzung_peek_nicht(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "LEDGER_F", tmp_path / "ledger.json")
    mc.main(["capture", "--kind", "notiz", "--text", "x"])
    vorher = mc.Ledger.load().session

    mc.main(["resume", "--peek"])
    assert mc.Ledger.load().session == vorher

    mc.main(["resume"])
    assert mc.Ledger.load().session == vorher + 1


def test_resume_signalisiert_verrottete_anker_im_exitcode(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "LEDGER_F", tmp_path / "ledger.json")
    mc.main(["capture", "--kind", "offen", "--text", "x",
             "--anchor", "path:weg_98765.txt"])
    assert mc.main(["resume", "--peek"]) == 1


def test_resume_brief_zeigt_offene_punkte_und_sackgassen(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mc, "LEDGER_F", tmp_path / "ledger.json")
    mc.main(["capture", "--kind", "offen", "--text", "unknown-nach-HOLD"])
    mc.main(["capture", "--kind", "sackgasse", "--text", "Blockliste reicht nicht"])
    capsys.readouterr()

    mc.main(["resume", "--peek"])
    out = capsys.readouterr().out
    assert "unknown-nach-HOLD" in out
    assert "Blockliste reicht nicht" in out
    assert "seal --push" in out


# --------------------------------------------------------------------------
# Dauerhaftigkeit -- die Lehre aus 29b701c
# --------------------------------------------------------------------------


def test_ledger_ausserhalb_von_git_ist_nicht_dauerhaft(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "LEDGER_F", tmp_path / "ledger.json")
    (tmp_path / "ledger.json").write_text("{}", encoding="utf-8")
    ok, detail = mc.durability()
    assert not ok
    assert detail

def test_fehlendes_ledger_ist_nicht_dauerhaft(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "LEDGER_F", tmp_path / "fehlt.json")
    ok, detail = mc.durability()
    assert not ok
    assert "existiert nicht" in detail
