"""Tests für Konsensgrad und Kostenbremse.

Beide Module haben eine sichere und eine unsichere Fehlerrichtung, und die
Tests halten fest, in welche sie fallen müssen:

* Konsens darf lieber **zu wenig** Einigkeit melden als zu viel. Ein System,
  das Übereinstimmung behauptet, die nicht da ist, ist schlimmer als eines,
  das zu oft nachfragt.
* Die Kostenbremse muss bei Unbekanntem **sperren**. Eine Bremse, die
  unbekannte Provider durchlässt, bremst genau dann nicht, wenn jemand einen
  neuen eingetragen hat.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from agents import budget as bg                                      # noqa: E402
from agents import consensus as cs                                   # noqa: E402


def A(provider, text, vendor=""):
    return cs.Answer(provider=provider, text=text, vendor=vendor or provider)


# --------------------------------------------------------------------------
# Konsens: Grundverhalten
# --------------------------------------------------------------------------

def test_identical_answers_reach_consensus():
    r = cs.evaluate([A("a", "Die Antwort ist 42."), A("b", "Die Antwort ist 42.")],
                    "factual")
    assert r.verdict == cs.CONSENSUS and r.score > 0.9 and r.trustworthy


def test_a_single_answer_is_never_consensus():
    """Eine Quelle kann sich nicht selbst bestaetigen."""
    r = cs.evaluate([A("a", "Die Antwort ist 42.")], "factual")
    assert r.verdict == cs.SINGLE and not r.trustworthy


def test_empty_input_does_not_crash():
    r = cs.evaluate([], "factual")
    assert r.verdict == cs.SINGLE and r.score == 0.0


def test_blank_answers_are_dropped():
    r = cs.evaluate([A("a", "Text"), A("b", "   "), A("c", "")], "factual")
    assert len(r.answers) == 1


def test_contradictory_facts_break_consensus():
    r = cs.evaluate([A("a", "Erschienen 2021."), A("b", "Erschienen 2018.")], "factual")
    assert not r.trustworthy
    assert any(d.kind == "year" for d in r.divergences)


def test_divergence_names_who_said_what():
    r = cs.evaluate([A("a", "Version 2021"), A("b", "Version 2018")], "factual")
    d = next(d for d in r.divergences if d.kind == "year")
    assert set(d.values) <= {"a", "b"} and "fehlt bei" in d.note


def test_hallucinated_identifier_is_surfaced():
    """Nennt genau ein Modell eine API, die keiner sonst kennt, ist das das
    klassische Halluzinationsmuster."""
    r = cs.evaluate([
        A("a", "Nutze cargo build und dann cargo.magic_deploy() dafuer."),
        A("b", "Nutze cargo build dafuer."),
        A("c", "Nutze cargo build dafuer."),
    ], "code")
    assert any("magic_deploy" in "".join(d.values.values()) for d in r.divergences)


# --------------------------------------------------------------------------
# Konsens: die Eigenschaften, die den Wert ausmachen
# --------------------------------------------------------------------------

def test_same_house_agreement_is_not_counted_as_independent():
    """Zwei Modelle desselben Anbieters teilen Trainingsdaten und blinde
    Flecken — ihre Einigkeit ist keine unabhaengige Bestaetigung."""
    same = cs.evaluate([A("gpt-a", "Die Antwort ist 42.", vendor="openai"),
                        A("gpt-b", "Die Antwort ist 42.", vendor="openai")], "factual")
    diff = cs.evaluate([A("gpt-a", "Die Antwort ist 42.", vendor="openai"),
                        A("gem-a", "Die Antwort ist 42.", vendor="google")], "factual")
    assert same.houses == 1 and same.verdict != cs.CONSENSUS
    assert diff.houses == 2 and diff.verdict == cs.CONSENSUS


def test_thresholds_differ_by_task_kind():
    """Brainstorming darf divergieren, eine Faktenfrage nicht."""
    answers = [A("a", "Idee: ein Marktplatz fuer Sensoren"),
               A("b", "Idee: ein Abo fuer Wartungsdaten")]
    assert cs.evaluate(answers, "brainstorm").verdict == cs.CONSENSUS
    assert cs.evaluate(answers, "factual").verdict != cs.CONSENSUS


def test_facts_outweigh_wording():
    """Gleicher Satzbau mit anderer Zahl muss schlechter abschneiden als
    anderer Satzbau mit gleicher Zahl."""
    same_number = cs.evaluate(
        [A("a", "Das Ergebnis betraegt 42 Einheiten."),
         A("b", "Es sind 42 Einheiten, wie berechnet.")], "factual")
    same_wording = cs.evaluate(
        [A("a", "Das Ergebnis betraegt 42 Einheiten."),
         A("b", "Das Ergebnis betraegt 99 Einheiten.")], "factual")
    assert same_number.score > same_wording.score


def test_report_is_json_serialisable():
    r = cs.evaluate([A("a", "x 1"), A("b", "x 2")], "factual")
    d = r.to_dict()
    json.dumps(d)
    assert d["verdict"] and d["threshold"] == cs.threshold("factual")


def test_summary_mentions_verdict_and_houses():
    out = cs.evaluate([A("a", "x"), A("b", "y")], "factual").summary()
    assert "Konsens" in out and "Haus" in out


@pytest.mark.parametrize("text, kind, expected", [
    ("Im Jahr 2021 waren es 1.234 Stueck.", "year", "2021"),
    ("Im Jahr 2021 waren es 1.234 Stueck.", "number", "1.234"),
    ('Er sagte "das geht nicht" dazu.', "quote", "das geht nicht"),
    ("Siehe https://example.com/pfad dazu.", "url", "https://example.com/pfad"),
])
def test_fact_extraction(text, kind, expected):
    assert expected in cs.extract_facts(text)[kind]


def test_year_is_not_double_counted_as_number():
    f = cs.extract_facts("Im Jahr 2021.")
    assert "2021" in f["year"] and "2021" not in f["number"]


# --------------------------------------------------------------------------
# Kostenbremse
# --------------------------------------------------------------------------

@pytest.fixture()
def locked():
    return bg.Budget(development_phase=True, allow_metered=False)


@pytest.fixture()
def unlocked():
    return bg.Budget(development_phase=True, allow_metered=True)


def test_free_provider_passes(locked):
    bg.check("pollinations", locked)      # wirft nicht


@pytest.mark.parametrize("provider", ["openai", "gemini", "mistral", "anthropic"])
def test_metered_provider_is_blocked(provider, locked):
    with pytest.raises(bg.BudgetBlocked):
        bg.check(provider, locked)


def test_unknown_provider_is_blocked(locked):
    """Die wichtigste Voreinstellung: im Zweifel sperren. Eine Bremse, die
    Unbekanntes durchlaesst, bremst nicht, wenn jemand etwas Neues eintraegt."""
    assert bg.cost_class("brandneuer_anbieter") == bg.UNKNOWN
    with pytest.raises(bg.BudgetBlocked) as exc:
        bg.check("brandneuer_anbieter", locked)
    assert "nicht eingeordnet" in str(exc.value)


def test_block_message_names_a_way_forward(locked):
    with pytest.raises(bg.BudgetBlocked) as exc:
        bg.check("openai", locked)
    msg = str(exc.value)
    assert "pollinations" in msg          # nennt kostenlose Alternativen
    assert "unlock" in msg                # und wie man bewusst loest


def test_unlocking_lets_metered_through(unlocked):
    bg.check("openai", unlocked)          # wirft nicht


def test_allowed_splits_the_list(locked):
    ok, blocked = bg.allowed(["pollinations", "openai", "hf_free", "gemini"], locked)
    assert ok == ["pollinations", "hf_free"]
    assert blocked == ["openai", "gemini"]


def test_unlock_requires_a_reason(tmp_path):
    p = tmp_path / "budget.json"
    with pytest.raises(ValueError):
        bg.unlock("   ", bg.Budget(), p)
    assert not p.exists()


def test_unlock_records_reason_and_time(tmp_path):
    p = tmp_path / "budget.json"
    b = bg.unlock("Erste zahlende Kundin, Abrechnung gedeckt", bg.Budget(), p)
    assert b.allow_metered and b.unlock_reason and b.unlocked_at
    assert not b.active
    saved = json.loads(p.read_text())
    assert saved["unlock_reason"]          # bleibt im Repo sichtbar


def test_relock_restores_the_guard(tmp_path):
    p = tmp_path / "budget.json"
    bg.unlock("test", bg.Budget(), p)
    b = bg.relock(bg.Budget.load(p), p)
    assert b.active and not b.unlock_reason


def test_repo_ships_with_the_guard_active():
    """Der Auslieferungszustand muss gesperrt sein, nicht offen."""
    b = bg.Budget.load()
    assert b.active, "config/budget.json muss die Bremse aktiv haben"


def test_every_free_provider_is_really_keyless():
    """Was hier als FREE steht, darf kein Abrechnungsverhaeltnis brauchen."""
    for p in bg.free_providers():
        assert bg.COST_CLASS[p] == bg.FREE
    assert "openai" not in bg.free_providers()


# --------------------------------------------------------------------------
# Verdrahtung: die Bremse muss im Ausfuehrungspfad greifen, nicht nur im Status
# --------------------------------------------------------------------------

def test_codex_adapter_is_blocked_by_the_guard():
    from agents import adapters as ad
    ok, why = ad.OracleCodexAdapter(provider="openai").available()
    assert ok is False
    assert "Kostenbremse" in why or "rechnet pro Aufruf" in why


def test_codex_adapter_refuses_execution_under_the_guard():
    from agents import adapters as ad
    from agents.protocol import AgentTask
    task = AgentTask(id="t-budget", kind="explain", instruction="x")
    with pytest.raises(bg.BudgetBlocked):
        ad.OracleCodexAdapter(provider="openai").execute(task)
