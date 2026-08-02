"""Das Fullstack-Compose — Pfade, die beim ersten echten Lauf ins Leere zeigten.

`deploy/fullstack-compose.yml` galt monatelang als gueltig: `docker compose
config` bestand, und das Build-Manifest fuehrte die Pruefung als
`bestanden`. Am 2026-08-02 wurde die Datei zum ersten Mal **wirklich
gestartet** — und war nicht startbar.

Die Ursache ist eine einzige und sie erzeugte drei Fehler: die Datei liegt
in `deploy/`, und docker compose loest `./` gegen das Verzeichnis der
Compose-Datei auf, nicht gegen die Repo-Wurzel.

**Warum `docker compose config` das nicht fand:** es prueft Syntax, nicht ob
ein Bind-Mount-Ziel existiert. Eine Syntaxpruefung, die als
Startbarkeitsnachweis gelesen wird, ist genau die Luecke, die dieses Repo
schon beim Containerimage gekostet hat — gruen gebaut, tot im Betrieb.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = REPO / "deploy" / "fullstack-compose.yml"


def _pfade() -> list[str]:
    """Jeder relative Pfad, den die Datei bindet oder als Kontext nutzt."""
    text = COMPOSE.read_text(encoding="utf-8")
    zeilen = [z.strip() for z in text.splitlines()
              if not z.strip().startswith("#")]
    aus = []
    for z in zeilen:
        m = re.match(r"-\s+(\.\.?/[^:]+):", z)
        if m:
            aus.append(m.group(1))
        m = re.match(r"context:\s*(\S+)", z)
        if m:
            aus.append(m.group(1))
    return aus


def test_every_relative_path_actually_exists():
    """**Der Test, den es vorher nicht gab.**

    Docker legt fuer einen fehlenden Bind-Mount ein *Verzeichnis* an, statt
    zu scheitern. Postgres startete deshalb, legte die Datenbank an und
    starb am Init-Skript mit `psql: could not read from input file: Is a
    directory` — eine Meldung ueber ein Verzeichnis, das es vorher nicht
    gab.
    """
    fehlend = []
    for p in _pfade():
        ziel = (COMPOSE.parent / p).resolve()
        if not ziel.exists():
            fehlend.append(f"{p} → {ziel}")
    assert not fehlend, (
        "relative Pfade zeigen ins Leere (docker compose loest sie gegen "
        f"deploy/ auf, nicht gegen die Repo-Wurzel): {fehlend}")


def test_the_build_context_contains_a_dockerfile():
    """`context: .` zeigte auf `deploy/`, wo kein Dockerfile liegt."""
    for p in _pfade():
        ziel = (COMPOSE.parent / p).resolve()
        if ziel.is_dir() and (ziel / "Dockerfile").is_file():
            return
    kontexte = [p for p in _pfade() if (COMPOSE.parent / p).resolve().is_dir()]
    assert False, f"kein Build-Kontext mit Dockerfile: {kontexte}"


def test_the_init_sql_is_the_real_one():
    """Gegenprobe zur Pfadkorrektur: der gebundene Pfad muss auf die
    tatsaechliche Datei zeigen, nicht irgendwohin."""
    treffer = [p for p in _pfade() if p.endswith("init-db.sql")]
    assert treffer, "kein init-db.sql gebunden"
    ziel = (COMPOSE.parent / treffer[0]).resolve()
    assert ziel == (REPO / "scripts" / "init-db.sql").resolve()
    assert ziel.is_file() and ziel.stat().st_size > 0


def test_syntax_validation_is_not_mistaken_for_startability():
    """Der Kopf der Datei muss den Unterschied benennen. Ohne ihn liest der
    naechste Leser `compose-syntax: bestanden` wieder als 'startbar'."""
    text = COMPOSE.read_text(encoding="utf-8")
    assert "prueft Syntax, nicht ob" in text
