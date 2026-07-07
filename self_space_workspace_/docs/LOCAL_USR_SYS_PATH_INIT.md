# local_usr/sys Path Init

`local_usr/sys/bin/path_init.py` initializes a standalone local control-plane tree below `local_usr/sys`.

It creates only local, verifiable structures:

- required system-like directories
- channel descriptors and JSONL streams
- dataset descriptors and materialized local datasets
- standalone self-made live-sets from local observations
- runtime validation state

It does not fabricate external data and does not perform network operations.

## Execute

```sh
python3 local_usr/sys/bin/path_init.py
```

## Main Outputs

| Path | Role |
| --- | --- |
| `local_usr/sys/etc/sys_manifest.json` | Control-plane manifest |
| `local_usr/sys/etc/channels/*.channel.json` | Channel descriptors |
| `local_usr/sys/var/lib/channels/*.events.jsonl` | Channel event streams |
| `local_usr/sys/etc/datasets/*.dataset.json` | Dataset descriptors |
| `local_usr/sys/var/lib/data/*.dataset.json` | Generated local datasets |
| `local_usr/sys/var/lib/live_sets/*.live.json` | Checked standalone live-sets |
| `local_usr/sys/var/run/state.json` | Latest init state |
| `local_usr/sys/var/run/validation.json` | Latest validation result |

## Live-Set Policy

If a required structure is missing or false, the initializer generates a standalone live-set from measured local facts:

- runtime command availability
- Python/platform information
- path readiness
- local git/log event state
- bridge configuration presence by environment variable names only

No credential values are read and no external data is invented.
