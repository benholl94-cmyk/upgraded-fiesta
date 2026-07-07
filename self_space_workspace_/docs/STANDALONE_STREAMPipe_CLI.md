# Standalone streampipe.cli

This is a self-made local CLI for append-only git/log capture. It is not the external Steampipe product and does not require network access or third-party Python packages.

## Purpose

- Capture local git status into `logs/git/local/events.jsonl`.
- Prefer `git` when available.
- Use `lg2` when available on iPhone/a-Shell.
- Fall back to direct `.git` metadata for branch/head when no git-compatible command is available.
- Keep outputs inspectable JSON for Codex/a-Shell control-plane workflows.

## Commands

```sh
python3 logs/git/local/streampipe.cli init
python3 logs/git/local/streampipe.cli capture
python3 logs/git/local/streampipe.cli validate
python3 logs/git/local/streampipe.cli status
python3 logs/git/local/streampipe.cli tail -n 5
python3 logs/git/local/streampipe.cli export
```

Use an explicit iPhone `lg2` command when needed:

```sh
python3 logs/git/local/streampipe.cli --git-cmd lg2 capture
```

Use an explicit repository root:

```sh
python3 logs/git/local/streampipe.cli --root ~/Documents/Developer/upgraded-fiesta.git capture
```

## Files

| Path | Role |
| --- | --- |
| `logs/git/local/streampipe.cli` | Standalone executable CLI |
| `logs/git/local/config.json` | Local runtime config |
| `logs/git/local/manifest.json` | Initialization manifest |
| `logs/git/local/events.jsonl` | Append-only event stream |
| `logs/git/local/latest_event.json` | Most recent capture |
| `logs/git/local/validation.json` | Latest validation result |
| `logs/git/local/snapshot.json` | Consolidated export |

## Validation Rule

The implementation is valid when:

- `init` creates config, manifest, and event stream files.
- `capture` appends one schema-valid event.
- `validate` exits with code `0`.
- No external Python dependency is imported.
- No network operation is performed.
