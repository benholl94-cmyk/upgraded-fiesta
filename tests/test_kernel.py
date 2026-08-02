"""Tests des Schlussfolgerungs-Kernels.

Zwei Fehlerrichtungen, beide teuer: raten wo nichts belegt ist, und schweigen
wo ein Praezedenzfall vorliegt. Die Tests halten beide fest.
"""
from __future__ import annotations
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from agents.kernel import (Case, Situation, infer, similarity, subsystem,
                           extract_cases, MIN_SIMILARITY)


def C(kind, text, subs=(), anchors=(), rotted=False):
    return Case(cid="x", kind=kind, text=text, subsystems=frozenset(subs),
                anchors=tuple(anchors), rotted=rotted)


@pytest.mark.parametrize("path, expect", [
    ("crates/hm-gateway/src/main.rs", "crates/hm-gateway"),
    ("agents/kernel.py", "agents"),
    ("scripts/x.py", "scripts"),
    ("", ""),
])
def test_subsystem_mapping(path, expect):
    assert subsystem(path) == expect


def test_invariante_outranks_a_commit():
    """Eine geltende Regel wiegt schwerer als ein einzelner Commit."""
    assert C("invariante", "x").weight > C("commit", "x").weight


def test_rotted_case_loses_weight():
    """Selbstreinigung: was auf nichts mehr zeigt, zaehlt weniger."""
    assert C("invariante", "x", rotted=True).weight < C("invariante", "x").weight


def test_similarity_is_coverage_not_jaccard():
    """Kurze Frage gegen langen Eintrag darf nicht bestraft werden."""
    s = Situation("ungepusht commit verloren")
    lang = C("invariante", "Ungepusht heisst nicht vorhanden ein Commit lebt nur "
                           "solange sein Container lebt so ging etwas verloren " * 3)
    assert similarity(s, lang) > 0.5


def test_case_without_paths_is_not_structurally_invisible():
    """Regression: Faelle ohne Pfadanker wurden auf 0.35*lex gedaempft und
    verschwanden — ausgerechnet Sackgassen tragen oft nur sha:-Anker."""
    s = Situation("rollback schleife revert", paths=("scripts/a.py",))
    ohne = C("sackgasse", "rollback schleife revert erneut")
    assert similarity(s, ohne) > MIN_SIMILARITY


def test_refuses_without_precedent():
    s = Situation("voellig unverwandtes thema bildverarbeitung")
    r = infer(s, [C("entscheidung", "gateway auth token pruefung")])
    assert r.verdict == "abgelehnt" and not r.actionable


def test_refuses_on_empty_corpus():
    assert infer(Situation("egal"), []).verdict == "abgelehnt"


def test_invariant_forbidding_the_path_blocks_regardless_of_similarity():
    """Invarianten werden nicht gegen Aehnlichkeit abgewogen."""
    s = Situation("push direkt auf main ohne review")
    r = infer(s, [C("invariante", "push auf main ist niemals erlaubt ohne review"),
                  C("entscheidung", "push auf main war damals in Ordnung")])
    assert r.verdict == "verboten" and r.blocking


def test_dead_end_is_surfaced_first():
    s = Situation("embeddings fuer konsens einbauen")
    r = infer(s, [C("sackgasse", "embeddings fuer konsens brauchen einen "
                                 "weiteren modellaufruf gescheitert")])
    assert r.actionable and "Sackgasse" in r.summary


def test_evidence_is_always_attached_to_a_recommendation():
    s = Situation("embeddings konsens")
    r = infer(s, [C("sackgasse", "embeddings konsens gescheitert")])
    assert r.evidence and r.evidence[0].case.text


def test_real_corpus_finds_the_unpushed_invariant():
    """Gegen den echten Bestand, nicht gegen Attrappen."""
    r = infer(Situation("Ungepushten Commit im Container liegen lassen"))
    assert r.actionable
    assert any("ungepusht" in e.case.text.lower() for e in r.evidence)


def test_real_corpus_refuses_an_unrelated_question():
    """Ohne Praezedenzfall wird abgelehnt, nicht geraten.

    **Dieser Test ist dreimal gebrochen, und beim dritten Mal war klar,
    dass er die falsche Frage stellte.** Die alte Fassung fragte nach einem
    *"Neues Rust-Crate fuer Bildverarbeitung"* — und ein Rust-Crate **hat**
    in diesem Repo Praezedenz. Getroffen haben jedes Mal die generischen
    Woerter (`neues`, `rust-crate`), waehrend das entscheidende Fachwort in
    0 von ueber 900 Faellen vorkam; zuletzt reichte eine einzige lange
    Commit-Botschaft fuer 0,333 gegen die Schwelle 0,30.

    Ein Test, den jeder neue Commit umkippen kann, misst den Korpus und
    nicht den Code. Die Kontrollfrage besteht deshalb jetzt **nur** aus
    Woertern, die nachweislich nirgends vorkommen — und dass sie das tun,
    wird hier zuerst geprueft, statt es zu hoffen.
    """
    frage = "Kolibri Marzipan Wolkenkratzer Rasenmaeher"
    faelle = extract_cases()
    vorhanden = [w for w in frage.lower().split()
                 if any(w in c.text.lower() for c in faelle)]
    assert not vorhanden, (
        f"Kontrollwoerter stehen im Korpus: {vorhanden} — der Test misst "
        "nichts mehr. Andere Woerter waehlen, nicht die Schwelle senken.")
    r = infer(Situation(frage, paths=("crates/hm-image/src/lib.rs",)))
    assert r.verdict == "abgelehnt", f"Naehe {r.confidence:.3f}"


def test_extraction_yields_both_ledger_and_commit_cases():
    kinds = {c.kind for c in extract_cases(commit_limit=30)}
    assert "commit" in kinds and kinds & {"invariante", "sackgasse", "entscheidung"}
