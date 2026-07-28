"""test_exception_hygiene.py — Wache ueber 'stilles Verschlucken' von Fehlern.

Sucht nach den drei Problem-Mustern, die `bare except` von einer Wache
in eine Verstopfung verwandeln:

1. `except Exception:` ohne Variablen-Bindung und ohne `log.*` davor
   (-> wir wissen nicht, was passiert ist)
2. `except: pass` (die schlimmste Form: 'ich will nichts wissen')
3. `except Exception: pass` (etwas weniger schlimm, aber immer noch
   stillschweigend)

## Was NICHT getestet wird

- `except Exception as e: log.exception(...)` -- korrekt
- `except (ValueError, KeyError):` mit konkreter Auswahl -- korrekt
- Tests selbst -- die duerfen `except Exception: pytest.skip(...)`
  enthalten, das ist im Testcode der Normalfall.

## Wo wir suchen

In allen produktiven Skripten unter scripts/, plugins/, agents/,
ghm_core/. NICHT in tests/ (Testcode hat eigene Konventionen) und
NICHT in status/ (Output, nicht Source).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Verzeichnisse, die produktiven Code enthalten (kein Test-Code).
PROD_DIRS = ["scripts", "plugins", "agents", "ghm_core", "crates"]


def _all_py_files() -> list[Path]:
    out = []
    for d in PROD_DIRS:
        root = REPO / d
        if not root.is_dir():
            continue
        out.extend(root.rglob("*.py"))
        # Rust-Dateien: hier suchen wir nicht nach Python-Patterns.
    return sorted(out)


# Heuristik: ein `except Exception:` (ohne `as e:`) ohne unmittelbar
# darauffolgendes `log.error`/`log.warning`/`log.exception` ist verdächtig.
# Wir lesen den Body 3 Zeilen weit.
_BARE_EXCEPT_RE = re.compile(r"^(\s*)except\s+Exception\s*:\s*$", re.MULTILINE)


def _has_logging_within(text: str, match_end: int, max_lines: int = 3) -> bool:
    """Sucht nach `log.error/log.warning/log.exception` in den naechsten
    `max_lines` Zeilen nach `match_end` (Position direkt nach dem `:`)."""
    after = text[match_end:].splitlines(keepends=True)
    window = "".join(after[:max_lines])
    return bool(re.search(r"log\.(error|warning|exception|info|debug)", window))


# ---------------------------------------------------------------------------
# 1 — `except Exception:` ohne Logging-Variante im Body (3 Zeilen Kontext)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pyfile", _all_py_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_bare_except_exception_without_log(pyfile: Path):
    """Wenn ein `except Exception:` keine Logging-Zeile in den naechsten
    3 Zeilen hat, ist die Suppression stillschweigend -- und damit genau
    die Klasse von Bug, die wir vermeiden wollen.

    Wichtig: wir melden NICHT, wenn die Exception weiter oben (z.B. als
    `except Exception as e:`) geloggt wird, weil das mit dem Heuristik-
    Regex nicht erfassbar ist und der Heuristik sonst zu viele false
    positives produziert. Wer eine Subtilitaet einfuehrt, fuegt hier eine
    Ausnahme-Liste an.
    """
    text = pyfile.read_text(encoding="utf-8", errors="replace")
    bad = []
    for m in _BARE_EXCEPT_RE.finditer(text):
        if not _has_logging_within(text, m.end()):
            # Line-Number fuer Diagnose
            line_no = text.count("\n", 0, m.start()) + 1
            bad.append((line_no, m.group(0).strip()))
    assert not bad, (
        f"{pyfile.relative_to(REPO)} hat stille `except Exception:` ohne "
        f"Logging im Body:\n"
        + "\n".join(f"  Zeile {ln}: {snippet}" for ln, snippet in bad)
    )


# ---------------------------------------------------------------------------
# 2 — `except Exception: pass` und `except: pass` sind explizit verboten
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pyfile", _all_py_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_silent_pass_in_except(pyfile: Path):
    """`except Exception: pass` schluckt JEDEN Fehler ohne Spur. Wenn
    das in einem Cron-Job steht, faellt der Job still aus und niemand
    merkt es bis zum naechsten manuellen Lauf."""
    text = pyfile.read_text(encoding="utf-8", errors="replace")
    # Suche Zeile, die nur 'pass' enthaelt (nach except).
    # Wir nutzen multiline und matchen 'except X:\n    pass' mit optional
    # Blank-Zeilen dazwischen.
    pattern = re.compile(
        r"except(?:\s+\w+(?:\s+as\s+\w+)?)?\s*:\s*\n\s*pass\b",
        re.MULTILINE,
    )
    bad = []
    for m in pattern.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        bad.append((line_no, m.group(0).strip()))
    assert not bad, (
        f"{pyfile.relative_to(REPO)} enthaelt stummes `except: pass`:\n"
        + "\n".join(f"  Zeile {ln}: {snippet}" for ln, snippet in bad)
    )


# ---------------------------------------------------------------------------
# 3 — Bare `except:` ohne Klassenangabe ist verboten (faengt BaseException)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pyfile", _all_py_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_bare_except_clause(pyfile: Path):
    """`except:` faengt KeyboardInterrupt und SystemExit mit. In einem
    Daemon fuehrt das dazu, dass Ctrl+C nicht mehr funktioniert und der
    Prozess stattdessen in der naechsten Iteration stirbt."""
    text = pyfile.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(r"^\s*except\s*:\s*$", re.MULTILINE)
    bad = []
    for m in pattern.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        bad.append((line_no, m.group(0).strip()))
    assert not bad, (
        f"{pyfile.relative_to(REPO)} hat bare `except:` (faengt BaseException):\n"
        + "\n".join(f"  Zeile {ln}: {snippet}" for ln, snippet in bad)
    )


# ---------------------------------------------------------------------------
# 4 — `except Exception as e: pass` (mit Bindung) -- weniger schlimm,
#     aber immer noch still. Hier nur Stichproben.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pyfile", _all_py_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_except_as_e_pass(pyfile: Path):
    """Wenn jemand `except Exception as e: pass` schreibt, ist die
    Intention 'ich weiss, dass das passieren kann, aber ich will nichts
    tun'. Das ist legitim, ABER muss als bewusste Entscheidung kommentiert
    sein. Diese Wache meldet nur das unkommentierte Muster."""
    text = pyfile.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(
        r"except\s+Exception\s+as\s+\w+\s*:\s*\n\s*pass\b",
        re.MULTILINE,
    )
    bad = []
    for m in pattern.finditer(text):
        # Erlaube, wenn der Block 2 Zeilen vorher einen Kommentar hat,
        # der mit "WARN", "NOTE" oder "Bewusst" / "intentional" anfaengt.
        line_start = text.rfind("\n", 0, m.start()) + 1
        prev_text = text[max(0, line_start - 400):line_start]
        if re.search(r"#\s*(WARN|NOTE|Bewusst|intentional|expected)", prev_text):
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        bad.append((line_no, m.group(0).strip()))
    assert not bad, (
        f"{pyfile.relative_to(REPO)} hat `except Exception as e: pass` ohne "
        f"Bewusst-Kommentar (WARN/NOTE/Bewusst/intentional):\n"
        + "\n".join(f"  Zeile {ln}: {snippet}" for ln, snippet in bad)
    )
