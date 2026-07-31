"""test_env_vars.py — Wache ueber `.env.production.example` Vollstaendigkeit.

Jede `HM_*`-Variable, die in produktivem Code (`crates/`, `scripts/`,
`plugins/`, `agents/`, `ghm_core/`, `ui/`) per `os.getenv` oder `env::var`
gelesen wird, MUSS in `.env.production.example` mit Default-Wert (oder
zumindest kommentiertem Platzhalter) auftauchen.

Was NICHT getestet wird:
- Variablen in `tests/` (Testcode hat eigene Konventionen)
- `HM_TESTCHAN_*` / `HM_CORE_NONEXISTENT_VAR__` (Bewusst-Fakes)
- Variablen die nur in Doku-Beispielen vorkommen
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO / ".env.production.example"
PROD_DIRS = ["crates", "scripts", "plugins", "agents", "ghm_core", "ui"]

# False-positive-Whitelist: Test-Fixtures, die absichtlich nicht
# dokumentiert sind.
WHITELIST = {
    "HM_TESTCHAN_EMPTY_BOT_TOKEN",
    "HM_TESTCHAN_MISSING_BOT_TOKEN",
    "HM_TESTCHAN_OK_BOT_TOKEN",
    "HM_TESTCHAN_WS_BOT_TOKEN",
    "HM_CORE_NONEXISTENT_VAR__",
}

HM_RE = re.compile(r"\bHM_[A-Z][A-Z0-9_]{2,40}\b")


def _scan_code_vars() -> set[str]:
    """Return set of HM_* var names found in production code via git grep."""
    cmd = ["git", "grep", "-lE", r"os\.getenv\(.{0,2}HM_|env::var\(.{0,2}HM_",
           "--", *PROD_DIRS]
    try:
        files = subprocess.run(cmd, cwd=REPO, capture_output=True,
                               text=True, check=True).stdout.splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()
    seen: set[str] = set()
    for path in files:
        try:
            text = (REPO / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in HM_RE.finditer(text):
            var = m.group(0)
            if not var.endswith("_") and var not in WHITELIST:
                seen.add(var)
    return seen


def _scan_env_example_vars() -> set[str]:
    """Return set of HM_* var names defined in `.env.production.example`."""
    out: set[str] = set()
    if not ENV_EXAMPLE.is_file():
        return out
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*#?\s*(HM_[A-Z][A-Z0-9_]*)\s*=", line)
        if m:
            out.add(m.group(1))
    return out


# Snapshot zur Testzeit; py-caching ist hier unguenstig (Dateiinhalt aendert
# sich zwischen Test-Runs).
_USED = _scan_code_vars()
_DOCUMENTED = _scan_env_example_vars()
_UNDOCUMENTED: list[str] = sorted(_USED - _DOCUMENTED - WHITELIST)


def _undocumented() -> list[str]:
    return sorted(_USED - _DOCUMENTED - WHITELIST)


def test_env_var_documented() -> None:
    """Jede in produktivem Code verwendete HM_* Variable MUSS in
    `.env.production.example` auftauchen — sonst weiss niemand, dass es
    sie gibt und der Default-Wert (oder "fehlt") bleibt unsichtbar.

    Wenn diese Variable unerwartet fehlschlaegt, ergaenze den Eintrag
    in `.env.production.example` mit Default oder als auskommentierter
    Platzhalter, oder (fuer Test-Fixtures) in WHITELIST oben.
    """
    undoc = _undocumented()
    assert not undoc, (
        f"{len(undoc)} HM_* Variable(n) werden in produktivem Code gelesen, "
        f"sind aber NICHT in .env.production.example dokumentiert:\n  "
        + "\n  ".join(undoc)
        + "\n\nBitte mit Default-Wert (oder auskommentiert) ergaenzen."
    )


def test_env_vars_doc_is_current() -> None:
    """docs/env-vars.md muss aktuell sein. Generator hat einen --check-Mode,
    den `make verify` ebenfalls aufruft; hier rufen wir ihn auf."""
    result = subprocess.run(
        ["python3", "scripts/dump_env_vars.py", "--check"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"docs/env-vars.md ist nicht aktuell:\n{result.stdout}\n{result.stderr}"
    )


def test_whitelist_does_not_drift() -> None:
    """Wenn jemand eine neue HM_TESTCHAN_* Variable einfuehrt, MUSS sie
    in die Whitelist aufgenommen werden — sonst schlaegt der erste Test
    fehl und der Owner weiss, dass er sie hier ergaenzen muss."""
    text = (REPO / "tests" / "test_env_vars.py").read_text(encoding="utf-8")
    # Suche nach allen HM_TESTCHAN_* und HM_CORE_NONEXISTENT* Vorkommen
    # im Test-Code selbst (z.B. test_router_plugin.py).
    cmd = ["git", "grep", "-hoE", r"HM_TESTCHAN_[A-Z_]+|HM_CORE_NONEXISTENT[A-Z_]+",
           "--", "tests"]
    try:
        out = subprocess.run(cmd, cwd=REPO, capture_output=True,
                             text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    found = set(out.split())
    missing = found - WHITELIST
    assert not missing, (
        f"Neue Test-Fixture-Variable(n) {missing} gefunden. Diese sind per\n"
        f"Konvention nicht dokumentierpflichtig, muessen aber in die\n"
        f"WHITELIST in tests/test_env_vars.py aufgenommen werden, sonst\n"
        f"schlaegt test_env_var_documented fehl."
    )