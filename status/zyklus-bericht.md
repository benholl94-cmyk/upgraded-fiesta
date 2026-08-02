# Zyklus 2026-08-02T12:51:16+00:00

## messen
- **inventar** — ok (2.6s)

## erden
- **korpus** — ok (0.6s) · geaendert

## heilen
- **selfheal** — ok (40.4s) · geaendert

## pruefen
- **startfrei** — befund (0.1s)
  - `{"ts": "2026-08-02T12:50:36.069+00:00", "level": "WARNING", "name": "agents.brain", "message": "swallowed in brain: <urlopen error [Errno 111] Connection refuse`
  - → `eval "$(python3 scripts/hugin_keyring.py env)"`
- **supervisor** — befund (0.6s)
  - `              ↳ /home/runner/.claude/stop-hook-git-check.sh fehlt — python3 scripts/install_hooks.py --yes`
  - → `python3 scripts/munin_supervisor.py`
- **tests** — befund (38.6s)
  - `2 failed, 1465 passed, 2 skipped in 38.29s`
  - → `python3 -m pytest tests/ -q`
- **index** — ok (1.1s)

