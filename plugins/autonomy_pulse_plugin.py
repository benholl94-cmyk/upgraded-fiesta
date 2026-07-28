#!/usr/bin/env python3
"""autonomy-pulse Plugin — hm-plugins-Protokoll-Brücke zu scripts/autonomy_core.py.

Liest eine JSON-Zeile aus stdin (PluginRequest), ruft autonomy_core.run_once() auf,
gibt eine JSON-Zeile auf stdout zurück (PluginResponse).

**stdout gehört dem Protokoll, nicht dem Logging.** `autonomy_core._log()`
schreibt mit `print()`, also nach stdout, und wird aus `heal()` und
`reflect()` heraus gerufen. Ohne Umleitung landet diese Zeile VOR der
Antwort, und hm-plugins liest genau die erste Zeile: aus
`[20:23:20] heal: Verzeichnis erstellt: diagnostics` macht serde eine
Sequenz, deren erstes Element `20` gegen `ok: bool` läuft — die im Betrieb
beobachtete Meldung `invalid type: integer`.

Der Fehler tritt genau dann auf, wenn die Selbstheilung tatsächlich etwas
heilt oder ein Alert eskaliert, also im wichtigsten Moment. Deshalb wird
hier nicht das Logging entfernt (es ist im Dauerbetrieb von
`autonomy_core` erwünscht), sondern der Kanal getrennt: alles, was die
Bibliothek nach stdout schreibt, geht nach stderr; stdout trägt
ausschließlich die eine Protokollzeile.
"""
from __future__ import annotations
import contextlib
import json
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import autonomy_core  # type: ignore
import logging
log = logging.getLogger(__name__)

def main() -> None:
    line = sys.stdin.readline()
    try:
        _req = json.loads(line)
    except Exception as exc:
        log.warning("swallowed in autonomy_pulse_plugin: %s", exc)
        _req = {}

    with contextlib.redirect_stdout(sys.stderr):
        pulse_state = autonomy_core.pulse()
        heal_actions = autonomy_core.heal()
        autonomy_core.reflect(pulse_state, heal_actions)

    result = {
        "ts": pulse_state.get("ts"),
        "alerts": pulse_state.get("alerts", []),
        "healed": len(heal_actions),
        "audit_score": pulse_state.get("audit", {}).get("score"),
    }
    ok = len(pulse_state.get("alerts", [])) == 0
    # allow_nan=False: Python schreibt fuer float('nan')/inf sonst die Literale
    # NaN und Infinity, und die sind KEIN gueltiges JSON. Auf dem Kabel wird
    # daraus beim Empfaenger "invalid number at line 1" -- ein Fehler, der wie
    # ein Protokollfehler aussieht und in Wahrheit ein Zahlenfehler ist.
    # Genau diese Meldung stand einmal im Gedaechtnis des Gateways. Lieber
    # hier laut scheitern als dort unverstaendlich.
    try:
        zeile = json.dumps({"ok": ok, "result": result,
                            "message": "autonomy-pulse complete"}, allow_nan=False)
    except ValueError as exc:
        zeile = json.dumps({"ok": False, "result": {},
                            "message": f"autonomy-pulse: unzulaessiger Zahlenwert: {exc}"})
    sys.stdout.write(zeile + "\n")
    sys.stdout.flush()

if __name__ == "__main__":
    main()
