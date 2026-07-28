"""test_rate_limit_parsing.py — Wache ueber `HM_RATE_LIMIT_PER_MINUTE`-Drift.

Die Variable wird in `.env.production.example` (Default: 120) und in
`crates/hm-gateway/src/main.rs` (Parser) definiert. Frueher haben sich
diese Stellen stillschweigend auseinanderbewegt.

Was wir pruefen:
1. Der Default-Wert im .env-Beispiel ist ein nicht-negativer Integer.
2. Der Parser im Gateway liest die Variable korrekt (siehe Code).
3. Der Default im Code stimmt mit dem .env-Beispiel ueberein.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO / ".env.production.example"
GW_MAIN = REPO / "crates" / "hm-gateway" / "src" / "main.rs"


def _env_default() -> int:
    """Default-Wert aus .env.production.example."""
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*HM_RATE_LIMIT_PER_MINUTE\s*=\s*(\d+)\s*$", line)
        if m:
            return int(m.group(1))
    pytest.fail("HM_RATE_LIMIT_PER_MINUTE nicht in .env.production.example")


def _code_default() -> int:
    """Fallback-Wert aus hm-gateway/main.rs Parser."""
    text = GW_MAIN.read_text(encoding="utf-8")
    # Suche `env::var("HM_RATE_LIMIT_PER_MINUTE").unwrap_or(N).parse()` etc.
    # Strategie: finde den naechsten `.unwrap_or(N)` rechts von
    # `HM_RATE_LIMIT_PER_MINUTE`.
    m = re.search(r'HM_RATE_LIMIT_PER_MINUTE.*?\.unwrap_or\((\d+)\)', text, re.DOTALL)
    if not m:
        m = re.search(r'HM_RATE_LIMIT_PER_MINUTE.*?unwrap_or_else\(\|_\|\s*(\d+)', text, re.DOTALL)
    if not m:
        pytest.fail(
            "Konnte den Default-Wert fuer HM_RATE_LIMIT_PER_MINUTE im "
            "Code-Parser nicht finden. Regex anpassen oder Code-Style-"
            "Drift untersuchen."
        )
    return int(m.group(1))


def test_env_default_is_valid_int() -> None:
    """Der Default im .env-Beispiel MUSS ein nicht-negativer Integer sein
    (0 = deaktiviert, >0 = Anzahl Requests pro Minute)."""
    val = _env_default()
    assert val >= 0, f"HM_RATE_LIMIT_PER_MINUTE={val} ist negativ"


def test_env_and_code_defaults_agree() -> None:
    """Wenn jemand den Default im Code auf z.B. 60 abaendert, aber im
    .env-Beispiel 120 laesst, fuehrt das zu 'funktioniert auf meinem
    System'-Bugs. Beide MUESSEN identisch sein."""
    assert _env_default() == _code_default(), (
        f"HM_RATE_LIMIT_PER_MINUTE-Drift: .env={_env_default()}, "
        f"Code={_code_default()}. Bitte beide Stellen angleichen."
    )


def test_code_parses_env_var() -> None:
    """Der Parser MUSS die Variable ueberhaupt lesen — sonst ist der
    ganze Test-Pfad wirkungslos."""
    text = GW_MAIN.read_text(encoding="utf-8")
    assert "HM_RATE_LIMIT_PER_MINUTE" in text, (
        "HM_RATE_LIMIT_PER_MINUTE wird im Code nicht gelesen — entweder "
        "wurde das Rate-Limit entfernt (dann diesen Test loeschen) oder "
        "die Variable heisst anders (dann .env anpassen)."
    )


def test_zero_means_disabled() -> None:
    """Wenn der Default 0 ist, sollte das irgendwo als 'deaktiviert'
    kommentiert sein — sonst weiss ein Operator nicht, dass 0 nicht
    'unbegrenzt' heisst."""
    if _env_default() == 0:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        # Suche Kommentar im Umkreis von 3 Zeilen.
        ctx = text[:text.index("HM_RATE_LIMIT_PER_MINUTE=")]
        assert "deaktiviert" in ctx[-200:] or "disabled" in ctx[-200:], (
            "HM_RATE_LIMIT_PER_MINUTE=0 sollte als 'deaktiviert' "
            "dokumentiert sein."
        )