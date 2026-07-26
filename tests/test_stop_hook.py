"""Tests für den versionierten Stop-Hook (`.claude/hooks/stop-hook-git-check.sh`).

Geprüft wird die **Repo-Fassung**, nicht die unter `~/.claude/` installierte:
die Repo-Fassung ist die autoritative, `scripts/install_hooks.py` spiegelt sie
nur. Ein Test gegen die installierte Kopie würde je nach Container etwas
anderes messen.

Hintergrund des Regressionstests weiter unten: der Hook verglich gegen
`origin/<branch>..HEAD`. Nachdem ein PR gemergt und der lokale Branch auf
main zurückgesetzt wurde, zeigte `origin/<branch>` noch auf den Stand vor dem
Merge — die Differenz enthielt dann den Merge-Commit und CI-Bot-Commits, also
fremde, bereits gemergte Arbeit. Der Hook verlangte, sie umzuschreiben.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
HOOK = REPO / ".claude" / "hooks" / "stop-hook-git-check.sh"

pytestmark = pytest.mark.skipif(not HOOK.is_file(), reason="Hook nicht im Repo")


def git(*args: str, cwd: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(("git",) + args, cwd=cwd, capture_output=True, text=True)


def run_hook(cwd: pathlib.Path, active: bool = False) -> tuple[int, str]:
    proc = subprocess.run(
        ["bash", str(HOOK)], cwd=cwd, capture_output=True, text=True,
        input=json.dumps({"stop_hook_active": active}),
    )
    return proc.returncode, proc.stderr


@pytest.fixture()
def repo(tmp_path):
    """Wegwerf-Repo mit Remote. Signing bleibt aus, bis ein Test es einschaltet."""
    remote, work = tmp_path / "remote", tmp_path / "work"
    remote.mkdir(); work.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git("init", "-q", "-b", "main", ".", cwd=work)
    git("remote", "add", "origin", str(remote), cwd=work)
    git("config", "user.email", "noreply@anthropic.com", cwd=work)
    git("config", "user.name", "Claude", cwd=work)
    git("config", "commit.gpgsign", "false", cwd=work)
    (work / "a.txt").write_text("a\n")
    git("add", "a.txt", cwd=work)
    git("commit", "-qm", "base", cwd=work)
    git("push", "-q", "-u", "origin", "main", cwd=work)
    return work


def commit(repo: pathlib.Path, name: str, msg: str, email: str | None = None) -> None:
    (repo / name).write_text(name + "\n")
    git("add", name, cwd=repo)
    args = ["commit", "-qm", msg]
    if email:
        args = ["-c", f"user.email={email}"] + args
    git(*args, cwd=repo)


# --------------------------------------------------------------------------
# Der Hook muss schweigen, wenn nichts zu tun ist
# --------------------------------------------------------------------------

def test_clean_repo_passes(repo):
    assert run_hook(repo)[0] == 0


def test_recursion_guard_short_circuits(repo):
    commit(repo, "b.txt", "ungepusht")
    assert run_hook(repo, active=True)[0] == 0


def test_repo_without_remote_is_skipped(tmp_path):
    work = tmp_path / "solo"
    work.mkdir()
    git("init", "-q", "-b", "main", ".", cwd=work)
    git("config", "user.email", "x@y.z", cwd=work)
    git("config", "user.name", "x", cwd=work)
    (work / "f").write_text("f")
    git("add", "f", cwd=work)
    git("commit", "-qm", "solo", cwd=work)
    assert run_hook(work)[0] == 0


# --------------------------------------------------------------------------
# ... und anschlagen, wenn es etwas zu tun gibt
# --------------------------------------------------------------------------

def test_uncommitted_changes_are_caught(repo):
    (repo / "a.txt").write_text("geaendert\n")
    code, err = run_hook(repo)
    assert code == 2 and "uncommitted changes" in err


def test_untracked_files_are_caught(repo):
    (repo / "neu.txt").write_text("x\n")
    code, err = run_hook(repo)
    assert code == 2 and "untracked files" in err


def test_genuinely_unpushed_commit_is_caught(repo):
    commit(repo, "b.txt", "neue arbeit")
    code, err = run_hook(repo)
    assert code == 2 and "unpushed commit" in err


def test_pushing_clears_the_unpushed_warning(repo):
    commit(repo, "b.txt", "neue arbeit")
    git("push", "-q", "origin", "main", cwd=repo)
    assert run_hook(repo)[0] == 0


def test_unsigned_commit_is_caught_when_signing_is_on(repo):
    git("config", "commit.gpgsign", "true", cwd=repo)
    commit(repo, "b.txt", "unsigniert")
    code, err = run_hook(repo)
    assert code == 2 and "Unverified" in err


def test_foreign_committer_email_is_named(repo):
    git("config", "commit.gpgsign", "true", cwd=repo)
    commit(repo, "b.txt", "fremd", email="fremd@example.com")
    code, err = run_hook(repo)
    assert code == 2 and "fremd@example.com" in err


def test_signature_check_is_skipped_when_signing_is_off(repo):
    git("config", "commit.gpgsign", "false", cwd=repo)
    commit(repo, "b.txt", "unsigniert")
    code, err = run_hook(repo)
    assert code == 2 and "Unverified" not in err      # nur die Unpushed-Meldung


# --------------------------------------------------------------------------
# Regression: der Zustand nach einem Merge
# --------------------------------------------------------------------------

def merged_branch_reset_onto_main(repo: pathlib.Path) -> None:
    """Stellt exakt den Zustand her, der den Fehlalarm ausgeloest hat:
    Feature-Branch gemergt, lokaler Branch auf main zurueckgesetzt, waehrend
    origin/<branch> noch auf den Stand vor dem Merge zeigt."""
    git("checkout", "-q", "-b", "feature", cwd=repo)
    commit(repo, "f.txt", "feature-arbeit")
    git("push", "-q", "-u", "origin", "feature", cwd=repo)
    git("checkout", "-q", "main", cwd=repo)
    git("merge", "-q", "--no-ff", "feature", "-m", "Merge pull request #1", cwd=repo)
    commit(repo, "bot.txt", "Update visible platform status [skip ci]")
    git("push", "-q", "origin", "main", cwd=repo)
    git("checkout", "-q", "-B", "feature", "origin/main", cwd=repo)


def test_merged_branch_reset_onto_main_is_silent(repo):
    """Kern des Fixes: nach dem Merge liegt alles auf origin/main. Es gibt
    nichts zu pushen und nichts umzuschreiben — der Hook muss schweigen."""
    merged_branch_reset_onto_main(repo)
    code, err = run_hook(repo)
    assert code == 0, f"Fehlalarm nach Merge:\n{err}"


def test_merge_and_bot_commits_are_not_claimed_as_local_work(repo):
    """Die alte Fassung verlangte einen Rebase ueber Merge- und Bot-Commits.
    Beides gehoert anderen Autoren und liegt bereits auf main."""
    git("config", "commit.gpgsign", "true", cwd=repo)
    merged_branch_reset_onto_main(repo)
    code, err = run_hook(repo)
    assert "Merge pull request" not in err
    assert "skip ci" not in err
    assert code == 0


def test_local_work_on_top_of_merged_main_is_still_caught(repo):
    """Gegenprobe: der Fix darf den Hook nicht taub machen. Echte neue
    Arbeit oberhalb des gemergten Stands muss weiterhin anschlagen."""
    merged_branch_reset_onto_main(repo)
    commit(repo, "neu.txt", "arbeit nach dem merge")
    code, err = run_hook(repo)
    assert code == 2 and "unpushed commit" in err


# --------------------------------------------------------------------------
# Der Spiegel-Mechanismus selbst
# --------------------------------------------------------------------------

import importlib.util  # noqa: E402
import sys  # noqa: E402

_INST = REPO / "scripts" / "install_hooks.py"
_spec = importlib.util.spec_from_file_location("install_hooks", _INST)
_inst = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _inst
_spec.loader.exec_module(_inst)


def test_repo_holds_the_authoritative_hook():
    assert HOOK.is_file() and HOOK.name in _inst.HOOKS


def test_install_is_repo_to_home_only():
    """Richtungsfestlegung: das Skript liest aus dem Repo und schreibt nach
    Home. Die Gegenrichtung waere genau die stille Divergenz, gegen die es
    gebaut ist."""
    assert _inst.SRC_DIR == REPO / ".claude" / "hooks"
    assert _inst.DST_DIR == pathlib.Path.home() / ".claude"


def test_state_detects_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(_inst, "SRC_DIR", tmp_path / "repo")
    monkeypatch.setattr(_inst, "DST_DIR", tmp_path / "home")
    (tmp_path / "repo").mkdir(); (tmp_path / "home").mkdir()
    src = tmp_path / "repo" / "h.sh"
    dst = tmp_path / "home" / "h.sh"

    src.write_text("eins")
    assert _inst.state("h.sh")[0] == "nicht-installiert"
    dst.write_text("zwei")
    assert _inst.state("h.sh")[0] == "drift"
    dst.write_text("eins")
    assert _inst.state("h.sh")[0] == "synchron"


def test_install_without_consent_refuses_loudly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(_inst, "SRC_DIR", tmp_path / "repo")
    monkeypatch.setattr(_inst, "DST_DIR", tmp_path / "home")
    monkeypatch.setattr(_inst, "HOOKS", ("h.sh",))
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "h.sh").write_text("neu")

    assert _inst.cmd_install(consent=False) == 2
    assert not (tmp_path / "home" / "h.sh").exists()   # kein stilles Schreiben


def test_install_with_consent_writes_and_backs_up(tmp_path, monkeypatch):
    monkeypatch.setattr(_inst, "SRC_DIR", tmp_path / "repo")
    monkeypatch.setattr(_inst, "DST_DIR", tmp_path / "home")
    monkeypatch.setattr(_inst, "HOOKS", ("h.sh",))
    (tmp_path / "repo").mkdir(); (tmp_path / "home").mkdir()
    (tmp_path / "repo" / "h.sh").write_text("neu")
    (tmp_path / "home" / "h.sh").write_text("alt")

    assert _inst.cmd_install(consent=True) == 0
    assert (tmp_path / "home" / "h.sh").read_text() == "neu"
    assert (tmp_path / "home" / "h.sh.bak").read_text() == "alt"


def test_check_reports_sync_state_of_this_repo():
    assert _inst.cmd_check() in (0, 1)      # 0 synchron, 1 Drift — nie Absturz
