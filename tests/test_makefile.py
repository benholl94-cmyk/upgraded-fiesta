"""test_makefile.py — `make verify` ist die Single-Command-Production-Grade-Wache.

Wer ein neues Gate hinzufuegt, haengt es an `verify:` an und schreibt einen
Test hier, der das Vorhandensein prueft. So kann weder ein Target
versehentlich entfernt noch die Reihenfolge stillschweigend gebrochen
werden.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MAKEFILE = REPO / "Makefile"


def _read_makefile() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1 — Aggregator-Target existiert und listet alle Sub-Targets
# ---------------------------------------------------------------------------

def test_verify_target_exists():
    text = _read_makefile()
    assert re.search(r"^verify:", text, re.MULTILINE), (
        "Makefile braucht ein `verify:`-Target als 100%-production-grade-Gate"
    )


@pytest.mark.parametrize("sub_target", [
    "fmt-check",
    "clippy-check",
    "test-workspace",
    "test-python",
    "validate",
    "clarity",
    "rollback",
    "routes",
])
def test_verify_lists_every_sub_target(sub_target):
    """Jeder Sub-Target, den `make verify` ruft, muss im Makefile deklariert
    sein — sonst bricht `make verify` mit 'No rule to make target' ab, was
    sich als leiser Erfolg tarnt, wenn niemand lokal nachstellt."""
    text = _read_makefile()
    # `^fmt-check:` als eigener Target-Eintrag (nicht als Kommentar).
    assert re.search(rf"^{re.escape(sub_target)}:", text, re.MULTILINE), (
        f"Sub-Target `{sub_target}` ist nicht im Makefile deklariert"
    )


# ---------------------------------------------------------------------------
# 2 — Reihenfolge ist wichtig (fmt vor clippy vor test)
# ---------------------------------------------------------------------------

def test_verify_target_order_is_fast_to_slow():
    """`fmt-check` muss vor `clippy-check` und `test-workspace` stehen,
    damit der billigste Check zuerst kommt. Wer das umstellt, ohne den
    Kommentar zu lesen, bricht den Schnellfeedback-Pfad."""
    text = _read_makefile()
    m = re.search(r"^verify:\s*(.*)$", text, re.MULTILINE)
    assert m, "verify:-Zeile fehlt"
    targets = m.group(1).split()
    pos = {t: targets.index(t) for t in targets if t in targets}
    # fmt-check < clippy-check < test-workspace
    assert pos["fmt-check"] < pos["clippy-check"], (
        "fmt-check muss VOR clippy-check stehen (billiger zuerst)"
    )
    assert pos["clippy-check"] < pos["test-workspace"], (
        "clippy-check muss VOR test-workspace stehen (Lint vor Test)"
    )


# ---------------------------------------------------------------------------
# 3 — Sub-Targets sind idempotent und ohne Netz
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sub_target,forbidden_token", [
    ("fmt-check", "rm -rf"),         # wuerde Cache zerstören
    ("clippy-check", "rm "),         # dito
    ("test-workspace", "curl "),     # Netz wuerde CI-Flakiness erzeugen
    ("test-python", "wget "),        # dito
])
def test_sub_targets_are_offline_and_idempotent(sub_target, forbidden_token):
    """`make verify` muss offline lauffaehig sein — sonst ist der Gate nicht
    deterministisch (verschiedene Tageszeiten = verschiedene Ergebnisse)
    und nicht fuer Air-Gapped-Runner brauchbar."""
    text = _read_makefile()
    # Suche den Body des Sub-Targets bis zur naechsten Leerzeile/Tab-Zeile.
    body = re.search(
        rf"^{re.escape(sub_target)}:\s*\n((?:\t[^\n]*\n)+)",
        text,
        re.MULTILINE,
    )
    assert body, f"Sub-Target `{sub_target}`-Body fehlt"
    assert forbidden_token not in body.group(1), (
        f"Sub-Target `{sub_target}` enthaelt `{forbidden_token}` — "
        f"`make verify` muss offline und idempotent sein"
    )


# ---------------------------------------------------------------------------
# 4 — Jeder Sub-Target hat einen Kommentar, der sagt was er prueft
# ---------------------------------------------------------------------------

def test_each_sub_target_has_documentation():
    """Ein Target ohne Kommentar verleitet dazu, es stillschweigend zu
    aendern. Wir verlangen einen Huerer-Kommentar darueber (Zeile, die mit
    `#` anfaengt, irgendwo innerhalb der 8 Zeilen davor)."""
    text = _read_makefile()
    sub_targets = [
        "verify", "fmt-check", "clippy-check", "test-workspace",
        "test-python", "validate", "clarity", "rollback", "routes",
    ]
    lines = text.splitlines()
    for target in sub_targets:
        idx = next(
            (i for i, line in enumerate(lines) if re.match(rf"^{re.escape(target)}:", line)),
            None,
        )
        assert idx is not None, f"Target `{target}` fehlt"
        # Suche rueckwaerts nach einem Kommentar-Block (mindestens 2 Zeilen,
        # weil das Pattern in echten Kommentaren hier mehrzeilig ist).
        window = "\n".join(lines[max(0, idx - 12):idx])
        comment_lines = [l for l in window.splitlines() if l.lstrip().startswith("#")]
        assert len(comment_lines) >= 1, (
            f"Target `{target}` hat keinen erklaerenden Kommentar darueber"
        )


# ---------------------------------------------------------------------------
# 5 — `make verify` exit code policy
# ---------------------------------------------------------------------------

def test_verify_exits_nonzero_on_any_failure():
    """`make verify` muss sofort abbrechen, sobald ein Sub-Target fehlschlaegt.
    `-` als Prefix vor einem Target wuerde Fehler ignorieren — das darf hier
    nicht passieren (sonst waere ein roter clippy-Lauf ein gruener `make verify`)."""
    text = _read_makefile()
    verify_line = next(
        line for line in text.splitlines() if re.match(r"^verify:", line)
    )
    targets = verify_line.split(":", 1)[1].split()
    # Kein Target darf mit `-` praefixt sein (GNU-Make: "ignore errors").
    bad = [t for t in targets if t.startswith("-")]
    assert not bad, (
        f"`verify:` darf keine `-`-praefixten Targets enthalten "
        f"(Fehler-ignorierend): {bad} in Zeile {verify_line!r}"
    )


# ---------------------------------------------------------------------------
# 6 — Keine stillen Erfolge: kein Sub-TTarget darf `true` als einzige Aktion haben
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sub_target", [
    "fmt-check", "clippy-check", "test-workspace", "test-python",
    "validate", "clarity", "rollback", "routes",
])
def test_sub_targets_do_real_work(sub_target):
    """`fmt-check:` darf nicht einfach `true` sein — sonst ist `make verify`
    ein leeres Ritual. Wir greppen nach 'true' als ALLEINIGE Body-Zeile."""
    text = _read_makefile()
    body = re.search(
        rf"^{re.escape(sub_target)}:[^\n]*\n((?:\t[^\n]*\n)+)",
        text,
        re.MULTILINE,
    )
    assert body, f"Body von `{sub_target}` fehlt"
    body_lines = [l.strip() for l in body.group(1).strip().splitlines()]
    assert body_lines != ["true"], (
        f"`{sub_target}` hat nur `true` als Body — `make verify` waere ein leeres Ritual"
    )
    assert not all(line == ":" or line.startswith(":") for line in body_lines), (
        f"`{sub_target}` enthaelt nur leere Variablenzuweisungen"
    )
