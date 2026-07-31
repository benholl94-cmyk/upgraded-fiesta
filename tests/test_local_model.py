"""Der lokale Modellkern (T1b) — gemessen, nicht gelesen.

Diese Datei hält drei Fehler fest, die alle live aufgetreten sind, als T1b
zum ersten Mal wirklich lief. Jeder davon sah vorher richtig aus.

1. **Verfügbarkeit wurde aus Dateien geschlossen.** `tiers()` prüfte, ob
   `models/model.gguf` und ein `llama-cli` existieren. Beides lag vor, T1b
   meldete `[x]` — und der erste echte Aufruf brach mit SIGABRT in
   `cli_server::wait_ready` ab. Eine vorhandene Datei ist kein laufender
   Dienst.

2. **Die Belegsuche fand nichts, wegen deutscher Flexion.** Die Frage sagt
   *atomarer*, der Ledgereintrag *atomar*; der exakte Mengenschnitt ergab
   0,000 — und zwar über **alle** 133 Fälle der Historie. Der Kern
   antwortete darum auf jede Frage „nicht belegt", und das 7-GB-Modell war
   unbenutzbar.

3. **Eine Frage wurde verboten.** `_FORBIDS` fand das Wort *kein* in der
   erklärenden Invariante „Hier *kein* Randfall: MemoryStore persistiert bei
   jedem remember()" und antwortete „VERWEIGERT — eine Invariante verbietet
   das" — unter Zitat genau der Invariante, die die Antwort enthielt.

Die Tests, die den laufenden Dienst brauchen, überspringen sich, wenn er
nicht läuft — aber sie sagen dabei, womit er zurückkommt. Die Tests der
Punkte 2 und 3 brauchen kein Modell und laufen immer.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agents import brain, kernel  # noqa: E402

SKRIPT = REPO / "scripts" / "hugin_local_model.py"


def _server_laeuft() -> bool:
    return brain.local_llm_status()[0]


dienst_noetig = pytest.mark.skipif(
    not _server_laeuft(),
    reason=("lokaler Modellserver nicht erreichbar — "
            "python3 scripts/hugin_local_model.py setup"),
)


# ── 1. Verfügbarkeit wird gemessen ───────────────────────────────────────────

def test_tier_availability_is_measured_not_read_from_files():
    """T1b darf nicht an der Anwesenheit einer Datei hängen.

    Gegenprobe zur Regression: die Begründung muss den Dienst nennen, nicht
    einen Dateinamen. Stünde hier wieder eine Dateiprüfung, meldete die
    Stufe `[x]`, während der Aufruf abstürzt.
    """
    erreichbar, grund = brain.local_llm_status()
    assert isinstance(erreichbar, bool)
    assert grund.strip(), "eine Stufe ohne Begründung lässt den Betreiber raten"
    if erreichbar:
        assert "llama-server" in grund and brain.LOCAL_LLM_URL in grund
    else:
        # Der Negativfall muss den Befehl nennen, der ihn behebt.
        assert "hugin_local_model.py" in grund


def test_an_unreachable_server_is_never_reported_as_available():
    """Ein Port, auf dem nichts lauscht, darf nie `True` ergeben."""
    alt = brain.LOCAL_LLM_URL
    try:
        brain.LOCAL_LLM_URL = "http://127.0.0.1:1"
        erreichbar, grund = brain.local_llm_status(timeout=1.0)
        assert erreichbar is False
        assert grund.strip()
    finally:
        brain.LOCAL_LLM_URL = alt


# ── 2. Belegsuche über deutsche Flexion ──────────────────────────────────────

def test_declined_german_words_still_find_their_evidence():
    """Die Regression: *atomarer* muss *atomar* finden.

    Ohne das ist jede Ähnlichkeit 0,000 und der Kern antwortet auf alles
    „nicht belegt".
    """
    faelle = kernel.extract_cases()
    treffer = [c for c in faelle if "atomar" in c.text.lower()]
    assert treffer, ("Im Ledger fehlt der Fall über atomares Schreiben — "
                     "dieser Test prüft damit nichts mehr")

    s = kernel.Situation(text="warum ist ein atomarer Schreibvorgang mit rename sicherer?")
    beste = max(kernel.similarity(s, c) for c in treffer)
    assert beste >= kernel.MIN_SIMILARITY, (
        f"Ähnlichkeit {beste:.3f} liegt unter der Schwelle {kernel.MIN_SIMILARITY} — "
        "der einschlägige Beleg bleibt unsichtbar"
    )


def test_stem_matching_does_not_match_everything():
    """Gegenprobe: eine sachfremde Frage darf keine Belege erzeugen.

    Ohne diese Richtung wäre „alles matcht" ebenfalls grün — und wertlos.
    """
    faelle = kernel.extract_cases()
    s = kernel.Situation(text="Bananenkuchen Urlaubsfotos Fahrradkette")
    assert max(kernel.similarity(s, c) for c in faelle) < kernel.MIN_SIMILARITY


@pytest.mark.parametrize("frage,fall,erwartet", [
    ("atomar", "atomarer", True),      # Flexion
    ("datei", "dateien", True),        # Plural
    ("verzeichnis", "verboten", False),  # bloße Silbengleichheit
    ("test", "testament", False),      # zu kurz für einen Stamm
    ("rename", "rename", True),        # identisch
])
def test_stem_rule_boundaries(frage, fall, erwartet):
    assert kernel._stamm_treffer(frage, fall) is erwartet


# ── 3. Eine Frage ist kein Vorhaben ──────────────────────────────────────────

def test_a_question_is_never_blocked_by_an_invariant():
    """Verbieten kann man ein Vorhaben, keine Frage.

    Die erklärende Invariante enthält das Wort „kein"; ohne die
    Unterscheidung wurde die Frage danach mit „VERWEIGERT" beantwortet.
    """
    s = kernel.Situation(text="warum ist ein atomarer Schreibvorgang mit rename sicherer?")
    r = kernel.infer(s)
    assert r.verdict != "verboten", (
        "Eine Frage wurde verboten. Zitiert wurde: "
        + "; ".join(c.text[:80] for c in r.blocking)
    )


def test_a_proposal_can_still_be_blocked():
    """Gegenprobe: die Schranke darf nicht einfach abgeschaltet sein.

    Ein Vorhaben, das eine einschlägige verbietende Invariante trifft, muss
    weiterhin blockiert werden — sonst hätte der Fix die Wache entfernt
    statt sie zu schärfen.
    """
    faelle = kernel.extract_cases()
    verbietend = [c for c in faelle
                  if c.kind == "invariante" and kernel._FORBIDS.search(c.text)]
    assert verbietend, "keine verbietende Invariante im Ledger — Test ohne Subjekt"

    # Aus dem Wortlaut der Invariante selbst ein Vorhaben bauen: so ist die
    # Ähnlichkeit garantiert hoch genug, und geprüft wird die Schranke, nicht
    # die Ähnlichkeitsrechnung.
    fall = verbietend[0]
    s = kernel.Situation(text=fall.text, kind="implement")
    r = kernel.infer(s, faelle)
    assert r.verdict == "verboten", (
        f"Vorhaben mit Wortlaut einer verbietenden Invariante wurde nicht "
        f"blockiert (verdict={r.verdict})"
    )


# ── 4. Das Skript selbst ─────────────────────────────────────────────────────

def test_status_reports_json_that_parses():
    out = subprocess.run([sys.executable, str(SKRIPT), "status", "--json"],
                         cwd=REPO, capture_output=True, text=True, timeout=120)
    daten = json.loads(out.stdout)
    for feld in ("erreichbar", "url", "modell_vorhanden", "laufzeit_vorhanden"):
        assert feld in daten, f"{feld} fehlt in der Statusausgabe"
    assert isinstance(daten["erreichbar"], bool)
    # Exit-Code trägt dieselbe Aussage wie das Feld — sonst könnte ein
    # Skript den einen prüfen und den anderen bekommen.
    assert (out.returncode == 0) is daten["erreichbar"]


def test_ask_without_a_running_server_fails_loudly():
    """Kein stiller Erfolg: ohne Dienst muss `ask` nichtnull enden."""
    out = subprocess.run(
        [sys.executable, str(SKRIPT), "ask", "Testfrage", "--url", "http://127.0.0.1:1"],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert out.returncode != 0
    assert "nicht bereit" in out.stderr.lower()


@dienst_noetig
def test_the_local_model_actually_answers():
    """Der Kern selbst: eine Frage, eine nichtleere Antwort, Exit 0."""
    out = subprocess.run(
        [sys.executable, str(SKRIPT), "ask", "Antworte mit genau einem Wort: Hallo"],
        cwd=REPO, capture_output=True, text=True, timeout=900)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip(), "leere Antwort ist kein Erfolg"


@dienst_noetig
def test_the_brain_routes_a_question_to_the_local_tier():
    """Die ganze Kette: Frage -> Erdung -> lokales Modell -> Antwort."""
    out = subprocess.run(
        [sys.executable, "-m", "agents.brain", "--json",
         "warum ist ein atomarer Schreibvorgang mit rename sicherer?"],
        cwd=REPO, capture_output=True, text=True, timeout=900)
    ereignisse = [json.loads(z) for z in out.stdout.splitlines() if z.strip()]
    stufen = {(e.get("meta") or {}).get("tier") for e in ereignisse}
    assert brain.T1B in stufen, f"nicht auf T1b beantwortet, Stufen: {stufen}"

    text = "".join(e["text"] for e in ereignisse if e.get("typ") == "token")
    assert text.strip(), "keine Antwort erzeugt"
    assert "nicht belegt" not in text.lower(), (
        "Der Kern hielt die Frage für unbelegt — die Belegsuche greift nicht"
    )
