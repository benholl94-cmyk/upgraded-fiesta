"""Einstiegspunkt fuer `python3 -m agents`.

Reicht an `agents.cli` weiter. Als Datei direkt aufgerufen scheitert dieses
Modul absichtlich: es ist Teil eines Pakets und benutzt relative Importe --
der richtige Aufruf ist `python3 -m agents`.
"""
from .cli import main

raise SystemExit(main())
