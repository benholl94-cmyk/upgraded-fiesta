"""test_dockerignore.py — Build-Context- + Container-Hardening-Wache.

Faustregel: ein `docker build .` ohne .dockerignore kopiert das GESAMTE
Working-Tree in den Builder. Bei diesem Repo mit models/, data/, target/
sind das ~600 MB pro Build-Layer. Mit .dockerignore sind es ~30 MB.

Zusaetzlich pruefen wir:
- Dockerfile hat ein `USER`-Directive am Ende (non-root)
- docker-compose.yml hat POSTGRES_PASSWORD als env-var (nicht literal)
- ui/Dockerfile existiert NICHT (tot, ersetzt durch Dockerfile.ui)
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_dockerignore_exists() -> None:
    """Ohne .dockerignore schickt docker build alles in den Kontext."""
    assert (REPO / ".dockerignore").is_file(), ".dockerignore fehlt"


@pytest.mark.parametrize("pattern", [
    "target/",
    ".git/",
    ".github/",
    "node_modules",
    "docs/",
    "*.log",
    "__pycache__/",
])
def test_dockerignore_excludes_critical(pattern: str) -> None:
    """Die groessten Brocken (target/, .git/, node_modules/) MUESSEN
    ausgeschlossen sein, sonst ist die Datei wirkungslos."""
    text = (REPO / ".dockerignore").read_text(encoding="utf-8")
    assert pattern in text, (
        f".dockerignore schliesst '{pattern}' nicht aus — der Build-Kontext "
        f"wird unnötig aufgebläht."
    )


def test_dockerfile_has_non_root_user() -> None:
    """Container laeuft als unprivilegierter User, nicht als root."""
    text = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "USER" in text, "Dockerfile hat keine USER-Directive — laeuft als root"
    # Pruefe, dass der User eine hohe UID hat (>= 1000).
    import re
    m = re.search(r"useradd.*?-u\s+(\d+)", text)
    if m:
        uid = int(m.group(1))
        assert uid >= 1000, (
            f"Dockerfile erstellt User mit uid {uid} -- sollte >= 1000 sein, "
            f"damit kein Konflikt mit System-Usern entsteht."
        )


def test_dead_ui_dockerfile_removed() -> None:
    """ui/Dockerfile war ein toter Clone des Root-Dockerfiles. Es wurde
    durch Dockerfile.ui ersetzt; das Root-docker-compose verweist jetzt
    explizit darauf."""
    assert not (REPO / "ui" / "Dockerfile").exists(), (
        "ui/Dockerfile existiert noch — sollte entfernt sein "
        "(ersetzt durch Dockerfile.ui)."
    )
    assert (REPO / "Dockerfile.ui").is_file(), "Dockerfile.ui fehlt"


def test_dockercompose_password_not_hardcoded() -> None:
    """POSTGRES_PASSWORD MUSS als env-var (${...}) gesetzt sein, nicht
    als literal im Compose-File — sonst publiziert das Repo ein
    Datenbank-Passwort im Klartext."""
    text = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    # Suche nach POSTGRES_PASSWORD:
    import re
    m = re.search(r"POSTGRES_PASSWORD:\s*(.+)", text)
    assert m, "POSTGRES_PASSWORD fehlt in docker-compose.yml"
    value = m.group(1).strip()
    # Wert muss eine Variable sein, kein literal.
    assert value.startswith("${"), (
        f"POSTGRES_PASSWORD ist literal gesetzt: '{value}'. "
        f"Bitte als env-var ${'{...}'} aus .env laden."
    )


def test_docker_compose_uses_root_dockerfile_ui() -> None:
    """docker-compose.yml UI-Service MUSS explizit Dockerfile.ui nehmen
    (nicht das toter ui/Dockerfile)."""
    text = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "Dockerfile.ui" in text, (
        "docker-compose.yml verweist nicht explizit auf Dockerfile.ui. "
        "Ohne den expliziten dockerfile-Eintrag wuerde build: ./ui "
        "versuchen, ui/Dockerfile zu nutzen (das entfernt wurde)."
    )