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
    git("-c", "commit.gpgsign=false", "commit", "-qm", "base", cwd=work)
    git("push", "-q", "-u", "origin", "main", cwd=work)
    return work


def commit(repo: pathlib.Path, name: str, msg: str, email: str | None = None) -> None:
    """Commit erzeugen — immer mit abgeschaltetem Signing.

    Zwei Gruende, beide in CI gelernt: (1) mit `commit.gpgsign=true` und ohne
    Schluessel bricht `git commit` hart ab, die Datei bleibt staged und der
    Hook meldet dann "uncommitted changes" statt der erwarteten Meldung.
    (2) Ob die Umgebung einen Signaturschluessel hat, darf ueber das
    Testergebnis nicht entscheiden. Tests, die den Signaturpfad pruefen wollen,
    setzen `commit.gpgsign` NACH dem Commit — das aendert nur die Sicht des
    Hooks, nicht die Erzeugbarkeit des Commits.
    """
    (repo / name).write_text(name + "\n")
    git("add", name, cwd=repo)
    args = ["-c", "commit.gpgsign=false", "commit", "-qm", msg]
    if email:
        args = ["-c", f"user.email={email}"] + args
    proc = git(*args, cwd=repo)
    # Ein verschluckter Fehlschlag hier erzeugt weiter unten eine voellig
    # irrefuehrende Assertion — genau das ist in CI passiert.
    assert proc.returncode == 0, f"git commit fehlgeschlagen: {proc.stderr}"


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
    git("-c", "commit.gpgsign=false", "commit", "-qm", "solo", cwd=work)
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
    commit(repo, "b.txt", "unsigniert")
    git("config", "commit.gpgsign", "true", cwd=repo)
    code, err = run_hook(repo)
    assert code == 2 and "Unverified" in err


def test_foreign_committer_email_is_named(repo):
    commit(repo, "b.txt", "fremd", email="fremd@example.com")
    git("config", "commit.gpgsign", "true", cwd=repo)
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
    git("-c", "commit.gpgsign=false", "merge", "-q", "--no-ff", "feature",
        "-m", "Merge pull request #1", cwd=repo)
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
    merged_branch_reset_onto_main(repo)
    git("config", "commit.gpgsign", "true", cwd=repo)
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


# ---------------------------------------------------------------------------
# Signatur-PRÄSENZ statt Signatur-URTEIL
#
# Der Anlass ist gemessen, nicht konstruiert: der Hook forderte einen Rebase
# für Commit 9d29122, dessen Rohobjekt nachweislich einen
# `gpgsig -----BEGIN SSH SIGNATURE-----`-Header trägt. Ursache war `%G? == N`.
# CCR signiert per SSH ohne `gpg.ssh.allowedSignersFile`; git kann die
# Signatur dann nicht einmal prüfen und meldet für signierte wie unsignierte
# Commits dasselbe. Die vorgeschlagene Abhilfe hätte einen Force-Push auf
# bereits gepushte Commits verlangt — verboten und wirkungslos zugleich.
#
# Die Signatur wird hier per git-Plumbing in das Objekt geschrieben statt mit
# ssh-keygen erzeugt. Das ist kein Notbehelf: der Hook liest den Header, also
# prüft der Test den Header — ohne Abhängigkeit von einer Signier-Toolchain,
# die in dieser Umgebung ohnehin fehlt.
# ---------------------------------------------------------------------------

SIG_HEADER = (
    "gpgsig -----BEGIN SSH SIGNATURE-----\n"
    " U1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTkAAAAgrLzsfFISF4by8Q+FKz27\n"
    " -----END SSH SIGNATURE-----"
)


def signiere_head(repo: pathlib.Path) -> str:
    """Schreibt HEAD neu, sodass das Objekt einen gpgsig-Header trägt."""
    roh = subprocess.run(["git", "cat-file", "commit", "HEAD"], cwd=repo,
                         capture_output=True, text=True, check=True).stdout
    kopf, _, rumpf = roh.partition("\n\n")
    neu = f"{kopf}\n{SIG_HEADER}\n\n{rumpf}"
    sha = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"],
                         cwd=repo, input=neu, capture_output=True, text=True,
                         check=True).stdout.strip()
    git("update-ref", "HEAD", sha, cwd=repo)
    return sha


def test_signierter_commit_wird_nicht_als_unsigniert_gemeldet(repo):
    """Der Kern des Fixes. Vorher falsch-positiv."""
    commit(repo, "s.txt", "wird gleich signiert")
    signiere_head(repo)
    git("config", "commit.gpgsign", "true", cwd=repo)

    roh = subprocess.run(["git", "cat-file", "commit", "HEAD"], cwd=repo,
                         capture_output=True, text=True).stdout
    assert "gpgsig" in roh, "Vorbedingung: der Commit trägt eine Signatur"
    urteil = subprocess.run(["git", "log", "--format=%G?", "-1"], cwd=repo,
                            capture_output=True, text=True).stdout.strip()
    assert urteil != "G", "Vorbedingung: git kann die Signatur nicht bestätigen"

    code, err = run_hook(repo)
    assert "Unverified" not in err, (
        "ein signierter Commit darf nicht als unsigniert gemeldet werden")
    # Der Hook meldet hier noch die ungepushte Arbeit — das ist eine andere,
    # richtige Prüfung. Erst nach dem Push muss er vollständig schweigen,
    # sonst wäre nicht belegt, dass die Signatur wirklich niemanden mehr stört.
    assert code == 2 and "unpushed commit(s)" in err
    git("push", "-q", "origin", "HEAD:main", cwd=repo)
    code, err = run_hook(repo)
    assert code == 0 and err.strip() == "", err


def test_unsignierter_commit_bleibt_gefangen(repo):
    """Gegenprobe: die Korrektur darf den echten Fall nicht durchlassen."""
    commit(repo, "u.txt", "ohne Signatur")
    git("config", "commit.gpgsign", "true", cwd=repo)
    code, err = run_hook(repo)
    assert code == 2 and "Unverified" in err
    assert "unsigned" in err


def test_gpgsig_in_der_message_taeuscht_keine_signatur_vor(repo):
    """Nur Header zählen — sonst genügte ein passender Satz im Text."""
    commit(repo, "f.txt", "gpgsig -----BEGIN SSH SIGNATURE-----")
    git("config", "commit.gpgsign", "true", cwd=repo)
    code, err = run_hook(repo)
    assert code == 2 and "Unverified" in err, "eine Message ist keine Signatur"


def test_fremde_mail_wird_auch_bei_vorhandener_signatur_gemeldet(repo):
    """Die zweite Bedingung bleibt unabhängig von der ersten bestehen."""
    commit(repo, "m.txt", "fremd", email="fremd@example.com")
    signiere_head(repo)
    git("config", "commit.gpgsign", "true", cwd=repo)
    code, err = run_hook(repo)
    assert code == 2 and "fremd@example.com" in err


# ---------------------------------------------------------------------------
# Die Supervisor-Regel `hook-drift` — nur dort gemessen, wo die Frage zaehlt
# ---------------------------------------------------------------------------
#
# Der Hook greift in eine Arbeitssitzung ein. Auf einem CI-Runner gibt es
# keine, und `~/.claude` existiert dort nicht — die Regel meldete trotzdem
# `hook-not-installed`, sieben Selbsterhalt-Laeufe lang, in einer Meldung, die
# ausdruecklich nur Master-Entscheidungen sammelt. Ein Befund, der von einem
# echten nicht zu unterscheiden ist und den niemand beheben kann, lehrt alle,
# die Meldung zu ueberfliegen.
#
# Die Regel hatte bis hier **gar keinen Test**. Die drei folgenden pruefen
# beide Richtungen: dass die Ausnahme greift, und — wichtiger — dass sie den
# echten Fall nicht mitnimmt.

import sys as _sys

_sys.path.insert(0, str(REPO / "scripts"))
import munin_supervisor as _sv  # noqa: E402


@pytest.fixture
def heim(tmp_path, monkeypatch):
    """Ein frei setzbares Zuhause — der echte Baum bleibt unberuehrt."""
    monkeypatch.setattr(_sv.Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


def test_ohne_arbeitsumgebung_wird_der_hook_nicht_gemessen(heim):
    """Kein `~/.claude` heisst: keine Arbeitssitzung, Frage nicht gestellt."""
    assert _sv.check_hook_drift() == []


def test_fehlender_hook_in_einer_arbeitsumgebung_bleibt_ein_befund(heim):
    """Die Gegenprobe, ohne die die Ausnahme die Regel abschaltet."""
    (heim / ".claude").mkdir()
    namen = [f.rule for f in _sv.check_hook_drift()]
    assert "hook-not-installed" in namen


def test_abweichender_hook_bleibt_ein_verstoss(heim):
    """Installiert, aber anders — genau der Drift, den die Regel sucht."""
    ziel = heim / ".claude"
    ziel.mkdir()
    for src in sorted((REPO / ".claude" / "hooks").glob("*.sh")):
        (ziel / src.name).write_text("#!/bin/sh\n# abweichend\n", encoding="utf-8")
    befunde = _sv.check_hook_drift()
    assert [f.rule for f in befunde] == ["hook-drift"] * len(befunde)
    assert befunde, "es gibt Hooks im Repo — der Drift muss auffallen"
