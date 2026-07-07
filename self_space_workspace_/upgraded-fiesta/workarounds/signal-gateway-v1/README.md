# signal-gateway-v1

Version: `1.0.0`

## Fixed workaround

This is the single fixed workaround for iPhone/a-Shell Signal gateway use.

The iPhone does not run Docker. The gateway runs on a private remote Ubuntu/Debian VPS and binds only to `127.0.0.1:9922`. The iPhone connects through a private local forward or private VPN and uses the Python client binder.

## Files

```text
workarounds/signal-gateway-v1/VERSION
workarounds/signal-gateway-v1/manifest.json
workarounds/signal-gateway-v1/server_bootstrap.sh
workarounds/signal-gateway-v1/ashell_bind_client.py
```

## Server path

```text
/opt/upgraded-fiesta-signal/
```

## Server state path

```text
/opt/upgraded-fiesta-signal/data/signal-cli/
```

## iPhone local config

```text
settings/signal-cli-client.local.json
settings/signal-gateway-workaround.version
```

## Invariants

- One workaround only: `signal-gateway-v1`.
- Versioned state: `1.0.0`.
- Gateway bind: `127.0.0.1:9922`.
- Public exposure of the gateway port is not part of this workaround.
- Signal account setup remains an account-level action and is not encoded into this repository.
