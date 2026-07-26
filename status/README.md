# `status/` — publizierte Statusartefakte

Dieses Verzeichnis ist **getrackt**. Was hier liegt, gehört ins Repo und wird von den Monitoring-Workflows fortgeschrieben.

| Datei | Erzeuger | Inhalt |
|---|---|---|
| `monitoring-report.json` | `scripts/monitor_platform.py` | Maschinenlesbarer Plattformbericht |
| `visible-status.json` | `scripts/write_visible_status.py` | Verdichteter Status zum schnellen Lesen |
| `visible-monitoring-report.json` | `scripts/write_visibility_report.py` | Vollbericht inkl. Workflow-Zustand |
| `monitoring-stdout.txt` | `visible-monitoring.yml` | Roher stdout des Monitorlaufs |

Fortgeschrieben von `visible-status.yml` (alle 6 h) und `visible-monitoring.yml` (alle 6 h).

## Warum getrennt von `logs/`

Beide Verzeichnisse enthielten früher dasselbe. `logs/` steht in `.gitignore`, trotzdem committeten zwei Workflows vier Dateien daraus per **`git add -f`** — das `-f` überschreibt die Ignore-Regel absichtlich. Publizieren und Ignorieren widersprachen sich, und der Widerspruch war unsichtbar, weil er in einem Workflow-Flag steckte.

Die Trennung löst das, ohne eine der beiden Absichten aufzugeben:

```
status/   soll sichtbar sein   → getrackt, normales git add
logs/     reine Laufzeitausgabe → ignoriert, nie committed
```

Sieben weitere Dateien in `logs/` (`hugin_*`, `knowledge-loop`, `llm-key-manager`, `oracle-audit`) wurden nie committed — für sie war `logs/` immer richtig.

## Regel für neue Dateien

Bevor hier etwas landet: **Braucht ein Leser des Repos das, ohne den Workflow-Lauf zu öffnen?**

- Ja → `status/`, normal committen.
- Nein → `logs/`, ignoriert lassen.

Ein `git add -f` ist in beiden Fällen das falsche Werkzeug. Wenn es nötig scheint, liegt die Datei im falschen Verzeichnis. Die Supervisor-Regel `tracked-but-ignored` (`scripts/munin_supervisor.py`) schlägt an, sobald diese Trennung wieder aufweicht.
