# a-Shell Documents Recovery

Observed failure:

- `python3` works.
- `lg2` exists, but `lg2 status` and `lg2 pull` fail because `Documents` is not a Git repository.
- `codex` is not installed in the current PATH.
- `scripts/validate_mobile_iphone_platform.py` and `scripts/mobile_operator.py` are not in `Documents`; they must be run from the project root.

Run:

```sh
python3 local_usr/sys/bin/ashell_documents_recovery.py all
```

If the project is under `~/Documents/Developer/upgraded-fiesta.git` or `~/Documents/Developer/generated_heavy_metal.git`, the tool will select it automatically.

When Codex CLI is missing, the tool creates a local fallback command at:

```text
local_usr/sys/var/lib/ashell_documents_recovery/ashell_cmds/codex
```

This fallback is not a real Codex CLI. It only reports local state honestly so scripts do not confuse `command not found` with a bridge failure.

Use this PATH command in a-Shell:

```sh
export PATH=local_usr/sys/var/lib/ashell_documents_recovery/ashell_cmds:$PATH
```
