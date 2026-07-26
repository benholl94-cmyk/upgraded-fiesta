"""Tests der Limit-Bewertung.

Die teuerste Verwechslung ist QUOTA gegen CONTEXT: beide melden oft "limit",
aber die eine verlangt Warten und die andere verbietet es. Wer einen
Kontextfehler als Kontingent behandelt, wartet Stunden auf etwas, das nie
eintritt.
"""
from __future__ import annotations
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from agents import limits as L


@pytest.mark.parametrize("text, kind", [
    ("Claude usage limit reached for today", L.QUOTA),
    ("insufficient_quota: exceeded your current quota", L.QUOTA),
    ("Daily limit reached", L.QUOTA),
    ("overloaded_error: server is overloaded", L.OVERLOAD),
    ("HTTP 503 Service Unavailable", L.OVERLOAD),
    ("429 Too Many Requests", L.RATE),
    ("You have hit the rate-limit", L.RATE),
    ("prompt is too long: 300000 tokens", L.CONTEXT),
    ("context_length_exceeded", L.CONTEXT),
])
def test_kinds_are_distinguished(text, kind):
    s = L.parse(text)
    assert s and s.kind == kind


def test_context_beats_quota_in_ordering():
    """'maximum context' enthaelt kein 'quota', aber die Reihenfolge muss
    sicherstellen, dass Kontext nie als Kontingent durchgeht."""
    s = L.parse("Error: maximum context length is 200000 tokens")
    assert s.kind == L.CONTEXT and not s.waiting_helps


def test_waiting_helps_everywhere_except_context():
    for k in (L.OVERLOAD, L.RATE, L.QUOTA):
        assert L.LimitSignal(k, "x", "m", 1).waiting_helps
    assert not L.LimitSignal(L.CONTEXT, "x", "m", 0).waiting_helps


def test_wait_ordering_reflects_severity():
    assert (L.DEFAULT_WAIT_S[L.OVERLOAD] < L.DEFAULT_WAIT_S[L.RATE]
            < L.DEFAULT_WAIT_S[L.QUOTA])
    assert L.DEFAULT_WAIT_S[L.CONTEXT] == 0


@pytest.mark.parametrize("text, secs", [
    ("rate limit, retry-after: 42", 42),
    ("rate limit — try again in 5 minutes", 300),
    ("429, retry_after=7", 7),
])
def test_provider_stated_wait_wins(text, secs):
    """Nennt die Gegenstelle eine Wartezeit, gilt sie -- sie weiss es besser."""
    assert L.parse(text).wait_s == secs


def test_falls_back_to_default_wait_when_none_stated():
    assert L.parse("429 Too Many Requests").wait_s == L.DEFAULT_WAIT_S[L.RATE]


def test_unknown_is_reported_not_swallowed():
    """Riecht nach Limit, kein Muster greift -> UNKNOWN, nicht None.
    Ein stilles 'kein Limit' laesst den Aufrufer in dieselbe Wand laufen."""
    s = L.parse("Your throttling policy applies here")
    assert s and s.kind == L.UNKNOWN


@pytest.mark.parametrize("text", [
    "", "   ", "alles in Ordnung", "Die Funktion prueft die Obergrenze der Liste",
])
def test_ordinary_text_is_not_a_limit(text):
    assert L.parse(text) is None and not L.is_limit(text)


def test_provider_filter_narrows_signatures():
    s = L.parse("prompt is too long", provider="anthropic")
    assert s and s.kind == L.CONTEXT and s.provider == "anthropic"


def test_every_kind_has_an_action():
    for k in (L.OVERLOAD, L.RATE, L.QUOTA, L.CONTEXT, L.UNKNOWN):
        assert L.ACTION[k].strip()


def test_signal_renders_kind_wait_and_action():
    out = str(L.parse("usage limit reached"))
    assert "QUOTA" in out and "warte" in out and "Stufe wechseln" in out


def test_excerpt_carries_context_for_diagnosis():
    s = L.parse("some prefix here 429 Too Many Requests and more after")
    assert s.raw_excerpt and "429" in s.raw_excerpt
