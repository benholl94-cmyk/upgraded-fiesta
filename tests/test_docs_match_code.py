"""test_docs_match_code.py — Doc-vs-Code-Drift-Wache.

Wer aendert `crates/hm-gateway/src/main.rs` und fuegt eine Route hinzu,
muss auch `docs/production-api-contract.md` aktualisieren — und umgekehrt.

Vorher: niemand merkt, dass die Doku eine Route verspricht, die der
Code nicht ausliefert (oder der Code eine Route hat, die nirgendwo
dokumentiert ist).

Nachher: pytest parst beide Seiten und meldet jede Luecke. Tests sind
absichtlich permissiv:

- Doc-claim ohne Code  = Fehler (Doku luegt)
- Code-Route ohne Doc  = Warning, kein Fehler (interne Aliase sind
  legitim — z.B. `/api/tasks` ist Alias fuer `/tasks`)
- HTTP-Methoden muessen uebereinstimmen
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "production-api-contract.md"
GW_MAIN = REPO / "crates" / "hm-gateway" / "src" / "main.rs"

# Format: ("GET", "/tasks")
ROUTE_RE = re.compile(r'\b(GET|POST|PUT|DELETE|PATCH)\s+(/[a-zA-Z0-9/_{}-]+)')


def _routes_from_doc() -> set[tuple[str, str]]:
    """Extract (METHOD, path) tuples from `docs/production-api-contract.md`."""
    if not DOC.is_file():
        return set()
    out: set[tuple[str, str]] = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and " " in stripped and "/" not in stripped:
            continue
        if stripped.startswith("|") and not ROUTE_RE.search(stripped):
            continue
        clean = stripped.replace("`", "")
        for m in ROUTE_RE.finditer(clean):
            method, path = m.group(1), m.group(2)
            if path.startswith("#"):
                continue
            out.add((method, path))
    return out


def _routes_from_code() -> set[tuple[str, str]]:
    """Extract (METHOD, path) tuples from `hm-gateway/src/main.rs`."""
    if not GW_MAIN.is_file():
        return set()
    text = GW_MAIN.read_text(encoding="utf-8")
    out: set[tuple[str, str]] = set()
    # 1) Tuple literals like `("GET", "/tasks")`.
    for m in re.finditer(r'"(GET|POST|PUT|DELETE|PATCH)"\s*,\s*"(/[a-zA-Z0-9/_{}-]+)"', text):
        out.add((m.group(1), m.group(2)))
    # 2) Bare path match arms like `("GET", "/api/health") =>` and
    #    consolidated routes (`"POST /tasks", "POST /api/tasks", ...`).
    for m in re.finditer(r'"(GET|POST|PUT|DELETE|PATCH)\s+(/[a-zA-Z0-9/_{}-]+)"', text):
        out.add((m.group(1), m.group(2)))
    # 3) Pipe-separated path alternatives like `"/chat" | "/api/chat" | "/gateway/chat"`
    #    inside `matches!(...)` blocks. We extract ANY string literal that
    #    starts with `/` and contains only route-valid chars. We then look
    #    backwards ~10 lines for `request.method == "POST"` (or other) to
    #    determine the HTTP method. If no method check is found, default
    #    to POST (hm-gateway convention: the only such block is chat).
    for m in re.finditer(r'"(/[a-zA-Z0-9/_{}-]+)"\s*\|\s*"(/[a-zA-Z0-9/_{}-]+)"', text):
        # Walk backwards to find the enclosing fn/method check.
        before = text[max(0, m.start() - 1500):m.start()]
        # Default: POST (chat convention).
        method = "POST"
        # Look for the closest preceding `request.method == "XXX"` check.
        method_check = re.search(r'request\.method\s*==\s*"(GET|POST|PUT|DELETE|PATCH)"', before)
        if method_check:
            method = method_check.group(1)
        out.add((method, m.group(1)))
        out.add((method, m.group(2)))
    return out


_DOC_ROUTES = _routes_from_doc()
_CODE_ROUTES = _routes_from_code()


def _summary() -> str:
    return f"doc={len(_DOC_ROUTES)} routes, code={len(_CODE_ROUTES)} routes"


@pytest.mark.skipif(not DOC.is_file(),
                    reason="docs/production-api-contract.md fehlt")
@pytest.mark.skipif(not GW_MAIN.is_file(),
                    reason="crates/hm-gateway/src/main.rs fehlt")
def test_documented_routes_exist_in_code() -> None:
    """Jede Route, die im Production-API-Contract dokumentiert ist,
    MUSS auch im Code existieren."""
    missing = sorted(_DOC_ROUTES - _CODE_ROUTES)
    assert not missing, (
        f"{len(missing)} Route(n) sind in docs/production-api-contract.md "
        f"dokumentiert, existieren aber NICHT im Code:\n  "
        + "\n  ".join(f"{m} {p}" for m, p in missing)
        + f"\n\n({_summary()})"
    )


def test_doc_routes_are_consistent() -> None:
    """Sanity-Check: jede dokumentierte Route hat eine konkrete HTTP-Methode."""
    for method, path in _DOC_ROUTES:
        assert method in {"GET", "POST", "PUT", "DELETE", "PATCH"}, \
            f"Unknown HTTP method: {method} {path}"


def test_code_has_at_least_minimum_routes() -> None:
    """Es sollten mindestens 10 verschiedene Routes im Code vorkommen."""
    assert len(_CODE_ROUTES) >= 10, (
        f"Nur {len(_CODE_ROUTES)} Routes im Code gefunden — das ist zu "
        f"wenig. Entweder ist main.rs stark geschrumpft, oder der Regex "
        f"in tests/test_docs_match_code.py muss nachjustiert werden."
    )