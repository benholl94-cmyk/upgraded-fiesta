"""Tests der Multi-Agent-Integrationsschicht.

Der Schwerpunkt liegt auf den Stellen, an denen eine Integration typischerweise
still falsch wird: ein Agent, der Erfolg meldet ohne Ergebnis; ein Parser, der
kaputte Antworten repariert statt sie abzulehnen; ein Patch, der aus dem Repo
ausbricht; eine Zustimmung, die niemand gegeben hat.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from agents import adapters as ad                                    # noqa: E402
from agents.ledger import Ledger                                     # noqa: E402
from agents.orchestrator import Orchestrator, OrchestratorError      # noqa: E402
from agents.protocol import (                                        # noqa: E402
    AgentPatch, AgentResult, AgentTask, FileContext, ProtocolError, parse_result,
)

REPO = pathlib.Path(__file__).resolve().parents[1]


def task(**kw) -> AgentTask:
    base = dict(id="t-001", kind="implement", instruction="mach etwas")
    base.update(kw)
    return AgentTask(**base)


# --------------------------------------------------------------------------
# Protokoll: Aufgaben
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    {"kind": "hack"},                       # unbekannte Art
    {"instruction": "   "},                 # leere Anweisung
    {"id": "AB"},                           # zu kurz / Grossbuchstaben
    {"id": "hat leerzeichen"},
])
def test_invalid_task_is_rejected(bad):
    with pytest.raises(ProtocolError):
        task(**bad)


def test_prompt_contains_schema_and_context():
    t = task(context_files=(FileContext(path="a.py", content="print(1)"),),
             constraints=("keine neuen Abhaengigkeiten",))
    p = t.render_prompt()
    assert "--- DATEI: a.py ---" in p and "print(1)" in p
    assert "keine neuen Abhaengigkeiten" in p
    assert '"task_id"' in p and "refused" in p      # Schema woertlich enthalten


def test_file_context_hash_is_content_addressed():
    a = FileContext(path="x", content="same")
    b = FileContext(path="anders", content="same")
    assert a.sha == b.sha
    assert a.sha != FileContext(path="x", content="other").sha


# --------------------------------------------------------------------------
# Protokoll: Antworten -- ablehnen statt reparieren
# --------------------------------------------------------------------------

def test_parses_bare_json():
    r = parse_result(json.dumps({"task_id": "t-001", "status": "ok",
                                 "patches": [{"path": "a.py", "action": "create",
                                              "content": "x=1"}]}), task(), "codex")
    assert r.status == "ok" and r.patches[0].path == "a.py"


def test_parses_json_inside_fence():
    raw = "Hier das Ergebnis:\n```json\n" + json.dumps(
        {"task_id": "t-001", "status": "refused", "notes": "nein"}) + "\n```\n"
    assert parse_result(raw, task(), "codex").status == "refused"


@pytest.mark.parametrize("raw, needle", [
    ("", "leere Antwort"),
    ("nur fliesstext ohne json", "kein JSON"),
    ('["liste"]', "erwartet Objekt"),
    ('{"task_id": "andere", "status": "ok"}', "passt nicht"),
    ('{"task_id": "t-001", "status": "erfunden"}', "unbekannt"),
])
def test_broken_response_raises_instead_of_guessing(raw, needle):
    with pytest.raises(ProtocolError) as exc:
        parse_result(raw, task(), "codex")
    assert needle in str(exc.value)


def test_success_without_patch_is_rejected_for_code_tasks():
    """Der teuerste stille Fehler: 'status ok' ohne Ergebnis."""
    raw = json.dumps({"task_id": "t-001", "status": "ok", "patches": []})
    with pytest.raises(ProtocolError) as exc:
        parse_result(raw, task(kind="implement"), "codex")
    assert "ohne Patch" in str(exc.value)


def test_success_without_patch_is_fine_for_explain():
    raw = json.dumps({"task_id": "t-001", "status": "ok", "notes": "erklaert"})
    assert parse_result(raw, task(kind="explain"), "codex").status == "ok"


def test_conflicts_survive_parsing():
    raw = json.dumps({"task_id": "t-001", "status": "partial",
                      "conflicts": ["Vorgabe widerspricht dem Bestandscode"],
                      "patches": [{"path": "a.py", "action": "replace", "content": "x"}]})
    assert parse_result(raw, task(), "codex").conflicts == (
        "Vorgabe widerspricht dem Bestandscode",)


@pytest.mark.parametrize("path", ["/etc/passwd", "../ausserhalb.py", "a/../../b"])
def test_patch_cannot_escape_the_repo(path):
    with pytest.raises(ProtocolError):
        AgentPatch(path=path, action="create", content="x")


def test_patch_action_is_constrained():
    with pytest.raises(ProtocolError):
        AgentPatch(path="a.py", action="delete", content="")


def test_result_dict_hides_patch_content_by_default():
    """Patch-Inhalte gehoeren nicht ungefragt ins Ledger oder auf stdout."""
    r = AgentResult(task_id="t-001", agent="codex", status="ok",
                    patches=(AgentPatch("a.py", "create", "GEHEIM"),), raw="GEHEIM")
    d = r.to_dict()
    assert "GEHEIM" not in json.dumps(d)
    assert d["patches"][0]["sha256"] and d["patches"][0]["bytes"] == 6
    assert "GEHEIM" in json.dumps(r.to_dict(include_raw=True))


# --------------------------------------------------------------------------
# Adapter
# --------------------------------------------------------------------------

def test_loopback_refuses_code_tasks_instead_of_faking_them():
    r = ad.LoopbackAdapter().execute(task(kind="implement"))
    assert r.status == "refused" and r.patches == ()
    assert r.conflicts and "leistet sie nicht" in r.conflicts[0]


def test_loopback_answers_non_code_tasks():
    assert ad.LoopbackAdapter().execute(task(kind="explain")).status == "ok"


def test_codex_adapter_is_marked_unverified():
    """Kernaussage des Auftrags: nichts wird als verifiziert ausgegeben,
    was nie gegen die echte Gegenstelle lief."""
    assert ad.OracleCodexAdapter.VERIFIED is False
    assert ad.CodexCliAdapter.VERIFIED is False
    assert ad.LoopbackAdapter.VERIFIED is True


def test_codex_adapter_reports_missing_key_instead_of_crashing(monkeypatch):
    """Der Key-Grund erscheint erst, wenn die Kostenbremse geloest ist.
    Die Reihenfolge ist Absicht: 'bereit, es fehlt nur der Key' waere eine
    falsche Auskunft ueber einen Provider, der ohnehin nicht laufen darf."""
    monkeypatch.delenv("HUGIN_OPENAI_KEY", raising=False)
    from agents import budget as _bg
    monkeypatch.setattr(_bg.Budget, "load",
                        classmethod(lambda cls, path=None: _bg.Budget(allow_metered=True)))
    ok, why = ad.OracleCodexAdapter().available()
    assert ok is False and "HUGIN_OPENAI_KEY" in why


def test_codex_adapter_refuses_to_run_without_key(monkeypatch):
    monkeypatch.delenv("HUGIN_OPENAI_KEY", raising=False)
    from agents import budget as _bg
    monkeypatch.setattr(_bg.Budget, "load",
                        classmethod(lambda cls, path=None: _bg.Budget(allow_metered=True)))
    with pytest.raises(ad.AdapterError):
        ad.OracleCodexAdapter().execute(task())


def test_cost_guard_takes_precedence_over_the_missing_key(monkeypatch):
    """Mit aktiver Bremse nennt der Adapter die Kosten, nicht den Key —
    sonst repariert jemand den Key und wundert sich, dass es trotzdem
    nicht laeuft."""
    monkeypatch.delenv("HUGIN_OPENAI_KEY", raising=False)
    ok, why = ad.OracleCodexAdapter().available()
    assert ok is False and "Kostenbremse" in why


def test_codex_skill_scope_exists_in_the_oracle_gate():
    """Ohne diesen Scope lehnt das Gate jeden Codex-Aufruf ab -- die
    Integration waere dann nur auf dem Papier verdrahtet."""
    oracle = ad._load_oracle()
    assert ad.CODEX_SKILL in oracle.SKILL_SCOPES
    scope = oracle.SKILL_SCOPES[ad.CODEX_SKILL]
    assert scope["max_prompt_chars"] >= 8000          # Patches brauchen Platz
    assert any("PRIVATE KEY" in p for p in scope["forbidden_patterns"])


def test_codex_scope_blocks_secrets_but_allows_ordinary_code():
    oracle = ad._load_oracle()
    gate = oracle.SecurityGate()
    gate.sanitize_input("def load(token): return token  # kein Wert", ad.CODEX_SKILL)
    with pytest.raises(ValueError):
        gate.sanitize_input('api_key = "abcdefghijklmnop"', ad.CODEX_SKILL)


def test_unknown_adapter_is_rejected():
    with pytest.raises(ad.AdapterError):
        ad.build("gibt-es-nicht")


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------

@pytest.fixture()
def orch(tmp_path):
    return Orchestrator(ledger=Ledger(tmp_path / "ledger.jsonl"))


def test_config_declares_both_roles():
    o = Orchestrator()
    roles = {r["id"]: r["role"] for r in o.status()}
    assert roles.get("claude") == "orchestrator"
    assert roles.get("codex") == "executor"


def test_status_reports_verification_honestly():
    rows = {r["id"]: r for r in Orchestrator().status()}
    assert rows["codex"]["verified"] is False
    assert rows["reference"]["verified"] is True


def test_context_file_must_exist(orch):
    with pytest.raises(OrchestratorError):
        orch.build_task("t-002", "review", "x", files=("gibt/es/nicht.py",))


def test_context_file_cannot_escape_repo(orch):
    with pytest.raises(OrchestratorError):
        orch.build_task("t-003", "review", "x", files=("../../etc/passwd",))


def test_dispatch_records_the_whole_flow(orch):
    t = orch.build_task("t-004", "explain", "erklaere")
    orch.dispatch(t, "reference")
    kinds = [e["kind"] for e in orch.ledger.read("t-004")]
    assert kinds == ["task.created", "task.dispatched", "task.result"]


def test_conflicts_are_recorded_not_smoothed(orch):
    t = orch.build_task("t-005", "implement", "baue etwas")
    orch.dispatch(t, "reference")
    assert any(e["kind"] == "conflict.recorded" for e in orch.ledger.read("t-005"))


def test_ledger_records_which_files_left_the_device(orch):
    t = orch.build_task("t-006", "review", "pruefe", files=("config/agents.json",))
    orch.dispatch(t, "reference")
    disp = [e for e in orch.ledger.read("t-006") if e["kind"] == "task.dispatched"][0]
    assert disp["payload"]["context_files"] == ["config/agents.json"]


def test_dispatch_to_unavailable_agent_fails_loudly(orch, monkeypatch):
    monkeypatch.delenv("HUGIN_OPENAI_KEY", raising=False)
    # Grund egal (Bremse oder Key) -- es muss laut scheitern, nicht still.
    t = orch.build_task("t-007", "explain", "x")
    with pytest.raises(OrchestratorError):
        orch.dispatch(t, "codex")
    assert any(e["kind"] == "task.error" for e in orch.ledger.read("t-007"))


def test_disabled_agent_is_refused(orch):
    with pytest.raises(OrchestratorError):
        orch.adapter_for("codex-local")


# --------------------------------------------------------------------------
# Anwenden: Zustimmung ist nicht optional
# --------------------------------------------------------------------------

def result_with_patch(tmp_path) -> AgentResult:
    return AgentResult(task_id="t-apply", agent="codex", status="ok",
                       patches=(AgentPatch("neu/datei.txt", "create", "inhalt"),))


def test_apply_without_consent_raises_and_writes_nothing(tmp_path):
    o = Orchestrator(ledger=Ledger(tmp_path / "l.jsonl"), repo=tmp_path)
    with pytest.raises(OrchestratorError) as exc:
        o.apply(result_with_patch(tmp_path), consent=False)
    assert "Zustimmung" in str(exc.value)
    assert not (tmp_path / "neu" / "datei.txt").exists()


def test_refusal_is_logged_as_rejection(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    o = Orchestrator(ledger=led, repo=tmp_path)
    with pytest.raises(OrchestratorError):
        o.apply(result_with_patch(tmp_path), consent=False)
    assert any(e["kind"] == "patch.rejected" for e in led.read("t-apply"))


def test_apply_with_consent_writes_the_file(tmp_path):
    o = Orchestrator(ledger=Ledger(tmp_path / "l.jsonl"), repo=tmp_path)
    written = o.apply(result_with_patch(tmp_path), consent=True)
    assert written == ["neu/datei.txt"]
    assert (tmp_path / "neu" / "datei.txt").read_text() == "inhalt"


def test_apply_backs_up_before_overwriting(tmp_path):
    (tmp_path / "vorhanden.txt").write_text("alt")
    o = Orchestrator(ledger=Ledger(tmp_path / "l.jsonl"), repo=tmp_path)
    r = AgentResult(task_id="t-bak", agent="codex", status="ok",
                    patches=(AgentPatch("vorhanden.txt", "replace", "neu"),))
    o.apply(r, consent=True)
    assert (tmp_path / "vorhanden.txt").read_text() == "neu"
    assert any(p.read_text() == "alt" for p in tmp_path.glob("vorhanden.txt.*.bak"))


def test_refused_result_is_never_applied(tmp_path):
    o = Orchestrator(ledger=Ledger(tmp_path / "l.jsonl"), repo=tmp_path)
    r = AgentResult(task_id="t-ref", agent="codex", status="refused",
                    patches=(AgentPatch("a.txt", "create", "x"),))
    with pytest.raises(OrchestratorError):
        o.apply(r, consent=True)
    assert not (tmp_path / "a.txt").exists()


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------

def test_ledger_is_append_only(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    led.record("task.created", "a", {})
    led.record("task.result", "a", {})
    assert len(led.read("a")) == 2


def test_ledger_rejects_unknown_events(tmp_path):
    with pytest.raises(ValueError):
        Ledger(tmp_path / "l.jsonl").record("erfunden", "a", {})


def test_one_broken_line_does_not_kill_the_ledger(tmp_path):
    p = tmp_path / "l.jsonl"
    led = Ledger(p)
    led.record("task.created", "a", {})
    with p.open("a") as fh:
        fh.write("{kaputt\n")
    led.record("task.result", "a", {})
    assert len(led.read()) == 2
