"""Tests für den Supervisor.

Schwerpunkt liegt auf den *positiven* Fällen: ein Auditor, der nie anschlägt,
sieht von aussen identisch aus wie ein sauberes Repo. Jede Prüfung muss
nachweislich mindestens einmal feuern können.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "munin_supervisor.py"
_spec = importlib.util.spec_from_file_location("munin_supervisor", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

Finding = _mod.Finding
Report = _mod.Report
VIOLATION, DRIFT, RISK, OK = _mod.VIOLATION, _mod.DRIFT, _mod.RISK, _mod.OK


# --------------------------------------------------------------------------
# Severity-Logik
# --------------------------------------------------------------------------

def test_empty_report_is_clean():
    r = Report(ts="t")
    assert r.worst == OK and r.exit_code() == 0


def test_violation_dominates_lesser_findings():
    r = Report(ts="t", findings=[
        Finding("a", RISK, "x"), Finding("b", VIOLATION, "y"), Finding("c", DRIFT, "z"),
    ])
    assert r.worst == VIOLATION and r.exit_code() == 2


def test_drift_alone_is_exit_one():
    r = Report(ts="t", findings=[Finding("a", DRIFT, "x")])
    assert r.exit_code() == 1


def test_render_sorts_violations_first():
    r = Report(ts="t", findings=[
        Finding("risky", RISK, "r"), Finding("bad", VIOLATION, "v"),
    ])
    out = _mod.render(r)
    assert out.index("bad") < out.index("risky")


def test_render_reports_clean_state_explicitly():
    assert "SAUBER" in _mod.render(Report(ts="t"))


# --------------------------------------------------------------------------
# Secret-Erkennung -- die Muster müssen echte Key-Formen treffen
# --------------------------------------------------------------------------

import re  # noqa: E402


def _matches(text: str) -> bool:
    return any(re.search(p, text) for p, _ in _mod.SECRET_PATTERNS)


def test_secret_patterns_match_real_key_shapes():
    assert _matches("sk-" + "a" * 32)
    assert _matches("ghp_" + "B" * 36)
    assert _matches("AIza" + "c" * 35)
    assert _matches("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert _matches("xoxb-123456789012-abcdefghij")


def test_secret_patterns_do_not_fire_on_ordinary_prose():
    assert not _matches("Das Skript liest den Token aus der Umgebung.")
    assert not _matches("sk-kurz")                     # zu kurz für einen Key
    assert not _matches("https://api.example.com/v1")


# --------------------------------------------------------------------------
# Doc-Drift: die Glob-Familien müssen erkannt werden
# --------------------------------------------------------------------------

def test_family_glob_maps_channel_crates():
    fam = lambda n: re.sub(                                            # noqa: E731
        r"-(telegram|discord|slack|whatsapp|browser|media|web|exec)$", "-*", n)
    assert fam("hm-channel-telegram") == "hm-channel-*"
    assert fam("hm-tool-browser") == "hm-tool-*"
    assert fam("hm-sessions") == "hm-sessions"          # keine Familie, bleibt


def test_doc_drift_finds_the_channel_crates_in_this_repo():
    """Regression: die erste Fassung prüfte nur den vollen Crate-Namen und
    liess damit genau die Familien durchrutschen, die CLAUDE.md als Glob
    beschreibt."""
    names = {f.detail.split()[2] for f in _mod.check_doc_drift()}
    assert any(n.startswith("hm-channel-") for n in names)


def test_stub_threshold_is_meaningfully_low():
    assert _mod.STUB_MAX_FUNCTIONS <= 3


# --------------------------------------------------------------------------
# Prüfungen gegen das echte Repo
# --------------------------------------------------------------------------

def test_hugin_index_is_a_byte_copy():
    assert _mod.check_hugin_sync() == []


def test_repo_structure_validates():
    assert _mod.check_repo_structure() == []


def test_audit_survives_a_broken_check(monkeypatch):
    def explode():
        raise RuntimeError("kaputt")
    monkeypatch.setattr(_mod, "CHECKS", (("boom", explode),))
    rep = _mod.audit(quick=True)
    assert len(rep.findings) == 1
    assert "kaputt" in rep.findings[0].detail
    assert rep.findings[0].severity == RISK      # ein kaputter Check ist kein Bruch


def test_audit_quick_skips_the_test_run(monkeypatch):
    called = []
    monkeypatch.setattr(_mod, "check_claims", lambda: called.append(1) or [])
    monkeypatch.setattr(_mod, "CHECKS", ())
    _mod.audit(quick=True)
    assert not called
    _mod.audit(quick=False)
    assert called


def test_oracle_gate_exempts_the_pwa():
    """hugin/ ruft Provider bewusst direkt aus dem Browser -- das ist kein
    Gate-Bruch und darf keinen Dauerbefund erzeugen."""
    assert any(x.startswith("hugin/") for x in _mod.ORACLE_EXEMPT)
    hits = [f for f in _mod.check_oracle_gate() if f.evidence.startswith("hugin/")]
    assert hits == []
