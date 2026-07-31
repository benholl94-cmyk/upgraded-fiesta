"""_log.py — einheitliches Logging fuer alle scripts/.

Vorher: 529 `print(...)`-Aufrufe quer durch das Repo, alle nach stdout,
keine Log-Level, keine Zeitstempel, keine Felder zum Filtern.

Nachher: ein stdlib `logging`-Logger mit JSON-Formatter nach stderr,
Level aus $LOG_LEVEL (Default INFO). `from _log import get_logger`
und dann `log.info(...)` statt `print(...)`.

## Warum ein Modul und keine Liste

`print("cron heartbeat")` ist nicht filterbar. Wer weiss, ob ein Cron-Lauf
in den letzten 24 h gelaufen ist, muss heute alle Logs greppen und nach
Heartbeats raten. Mit `log.info("cron heartbeat")` reicht ein
`grep '"level": "INFO"'` -- und der Heartbeat hinterlaesst einen
ISO-Zeitstempel und das `extra={...}`-Feld `name`.

## Warum JSON und nicht Plain-Text

Container-Stderr laeuft in Loki / journald / CloudWatch, die alle JSON
bevorzugen. Plain-Text-Logs brechen dort die Filter-Syntax. JSON kostet
ein paar Bytes pro Zeile und ermoeglicht `jq '.level=="ERROR"'` als
Ad-hoc-Filter, was bei der Fehlersuche in einem 12-h-Loglauf den
Unterschied zwischen '5 Minuten' und '5 Stunden' macht.

## Idempotenz

Mehrere Aufrufe von `get_logger(...)` aus verschiedenen Skripten im
selben Prozess (z.B. Tests, die `munin_clarity` und `hugin_selfheal`
beide importieren) duerfen den Logging-Stack nicht doppelt
konfigurieren. `_configure_once` benutzt einen `threading.Lock` und
einen `_already_configured`-Flag, damit `logging.basicConfig` nicht
zum zweiten Mal aufgerufen wird (was stumm bleibt, aber Handler
haengt).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone

# Einmalig pro Prozess. `Lock` schuetzt gegen parallelen Import in
# Multiprozess-Tests; der Flag ist der echte Schutz.
_configure_lock = threading.Lock()
_already_configured = False


class _JsonFormatter(logging.Formatter):
    """ISO-8601-Zeitstempel in UTC, Felder als flache Top-Level-Keys.

    Beispielzeile:
        {"ts":"2026-07-28T12:34:56.789+00:00","level":"INFO","name":"munin_supervisor",
         "message":"CI-Eintrag gefunden","sha":"abc1234"}

    Felder aus `extra={...}` landen automatisch im Top-Level (siehe
    `_JsonFormatter.format`), nicht in einem `extra`-Sub-Key. Das ist
    Absicht: Loki-/CloudWatch-Pipelines indexieren nur Top-Level-Felder.
    """

    # Felder, die Python-intern anhaengen wuerde, aber im JSON nichts zu
    # suchen haben. `args` ist nur sinnvoll, solange das Message-Template
    # nicht aufgeloest wurde; `exc_info` ueberschreiben wir separat.
    _RESERVED = {"name", "msg", "args", "levelname", "levelno", "pathname",
                 "filename", "module", "exc_info", "exc_text", "stack_info",
                 "lineno", "funcName", "created", "msecs", "relativeCreated",
                 "thread", "threadName", "processName", "process", "message",
                 "asctime", "taskName"}

    def format(self, record: logging.LogRecord) -> str:
        # ISO-8601 in UTC mit Millisekunden — Loki und CloudWatch sortieren
        # danach stabil; ein lokales Format ('%H:%M:%S') wuerde in der
        # Cross-Replica-Sortierung brechen.
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        )
        out: dict[str, object] = {
            "ts": ts,
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        # Extras durchreichen (alles, was nicht im Reserved-Set ist).
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            out[key] = value
        if record.exc_info:
            # exc_info=True: format_exception haengt den Traceback als
            # mehrzeiligen String an. JSON verträgt das; die letzte Zeile
            # schliessen wir explizit nicht ab, das macht json.dumps.
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def _configure_once() -> None:
    global _already_configured
    with _configure_lock:
        if _already_configured:
            return
        # Level aus $LOG_LEVEL, Default INFO. Wer debuggen will:
        # `LOG_LEVEL=DEBUG python3 scripts/foo.py`.
        level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, None)
        if not isinstance(level, int):
            # Fallback bei Tippfehlern — `LOG_LEVEL=INFOO` darf nicht in
            # einen stillen NoOp münden, sonst glaubt der Operator, es
            # waere still.
            print(
                f"_log: unbekanntes LOG_LEVEL={level_name!r}, fallback INFO",
                file=sys.stderr,
            )
            level = logging.INFO
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(_JsonFormatter())
        root = logging.getLogger()
        # basicConfig waere verlockend, aber ueberschreibt existierende
        # Handler nicht — was bei Tests, die pytests Caplog benutzen,
        # gewollt ist. Stattdessen direkt auf der Root-Logger-Instanz
        # operieren.
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(level)
        _already_configured = True


def get_logger(name: str) -> logging.Logger:
    """Gibt einen benannten Logger zurueck. Idempotent.

    `name` ist in der Regel `__name__` des aufrufenden Skripts
    (z.B. `scripts.munin_supervisor`), damit klar ist, welches Modul
    die Zeile geschrieben hat.

    Beispiel:
        from _log import get_logger
        log = get_logger(__name__)
        log.info("cron heartbeat", extra={"interval_secs": 3600})
    """
    _configure_once()
    return logging.getLogger(name)
