"""migrate_to_log.py — Einmaliger Migrations-Helper fuer Plan B.3.

Fuegt in jedes Migrations-Ziel-Skript einen `from _log import get_logger`-
Block ein (idempotent: ueberspringt, wenn schon vorhanden) und einen
`log = get_logger(__name__)`-Aufruf. Fuehrt KEINE print->log-Konvertierung
durch -- die ist pro Skript manuell zu machen (print ist nicht immer
1:1 durch log.info ersetzbar, oft hat print eine besondere Bedeutung).

Idempotenz: zweimal laufen lassen ist ein No-Op.

Aufruf:
    python3 scripts/_migrate_to_log.py --dry-run   # zeigen, was passieren wuerde
    python3 scripts/_migrate_to_log.py             # tatsaechlich anwenden
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO / "scripts"
PLUGINS_DIR = REPO / "plugins"

# Welche Skripte sollen migriert werden? (siehe Plan B.3)
TARGETS = [
    "scripts/hm_gateway_watchdog.py",
    "scripts/munin_continuity.py",
    "scripts/munin_supervisor.py",
    "scripts/rotation_daemon.py",
    "scripts/knowledge_loop.py",
    "scripts/security_sentinel.py",
    "scripts/repo_tracker.py",
    "scripts/monitor_platform.py",
    "scripts/hugin_selfheal.py",
    "scripts/hugin_clarity.py",
    "scripts/llm_key_manager.py",
    "plugins/channel_send_plugin.py",
    "plugins/llm_chat_plugin.py",
    "plugins/echo_plugin.py",
]


def _resolve_path(rel: str) -> Path:
    return REPO / rel


def _insert_logger_block(path: Path, dry_run: bool) -> str:
    """Fuegt unter den ersten `from __future__ import annotations`-Block
    einen Logger-Import + Initialisierung ein.

    Idempotenz: wenn `from _log import get_logger` schon im File steht,
    wird nichts geaendert.
    """
    text = path.read_text(encoding="utf-8")
    if "from _log import get_logger" in text or "import _log" in text:
        return "skip (already has _log import)"
    # Pfad-Trick: _log.py liegt unter scripts/. Wenn das Skript auch dort
    # liegt, ist `..` der REPO-Root; sonst (z.B. plugins/) zwei Ebenen
    # hoch. Beide Faelle fuegen scripts/ zum sys.path und importieren
    # dann als Modul ohne Package-Marker.
    block = (
        "\n# Strukturiertes Logging (Plan B.3). Idempotent -- mehrfach\n"
        "# aufgerufen waere ein No-Op, weil `_configure_once()` einen\n"
        "# Flag abfragt, bevor sie Handler anhaengt.\n"
        "import os as _os, sys as _sys\n"
        "_HERE = _os.path.dirname(_os.path.abspath(__file__))\n"
        "_PARENT = _os.path.dirname(_HERE)\n"
        "_SCRIPTS = _os.path.join(_PARENT, 'scripts')\n"
        "if _SCRIPTS not in _sys.path:\n"
        "    _sys.path.insert(0, _SCRIPTS)\n"
        "from _log import get_logger\n"
        "log = get_logger(__name__)\n"
    )
    # Suche das Ende des `from __future__`-Blocks (oder Anfang der Datei,
    # wenn kein solcher Block existiert).
    m = re.search(r"(from __future__ import annotations[^\n]*\n)+", text)
    if m:
        insert_at = m.end()
    else:
        insert_at = 0
    new_text = text[:insert_at] + block + text[insert_at:]
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return f"inserted at offset {insert_at}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true",
                   help="zeigen, was geaendert wuerde, ohne zu schreiben")
    args = p.parse_args(argv)

    for rel in TARGETS:
        path = _resolve_path(rel)
        if not path.is_file():
            print(f"  {rel}: NOT FOUND (uebersprungen)")
            continue
        result = _insert_logger_block(path, dry_run=args.dry_run)
        prefix = "  WOULD" if args.dry_run else "  DONE"
        print(f"{prefix}  {rel}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
