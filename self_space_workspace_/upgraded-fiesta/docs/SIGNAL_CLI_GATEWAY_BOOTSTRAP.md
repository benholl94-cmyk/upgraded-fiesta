# Signal CLI Gateway Bootstrap

This integration adds a server-side Signal gateway for the upgraded-fiesta control plane.

## Decision

Run `signal-cli` through the Dockerized REST gateway on a Linux/Docker host. Do not run the Signal daemon directly inside iPhone a-Shell. The iPhone/a-Shell side should act as a thin controller and call the gateway through a local tunnel, VPN, or private HTTPS reverse proxy.

## Files

- `integrations/signal-cli/docker-compose.signal.yml` — isolated Signal gateway stack.
- `integrations/signal-cli/signal.env.example` — safe configuration template.
- `scripts/bootstrap_signal_cli_gateway.sh` — Linux/Docker bootstrapper.
- `scripts/signal_cli_smoke_test.py` — stdlib-only health and optional send test.
- `settings/signal-cli-client.example.json` — mobile/client-side connection template.

## Bootstrap on Linux/Docker host

```sh
sh scripts/bootstrap_signal_cli_gateway.sh
```

The bootstrapper creates:

```text
integrations/signal-cli/.env.signal.local
integrations/signal-cli/data/signal-cli/
```

Edit `.env.signal.local` before sending real messages.

## Health test

```sh
set -a
. integrations/signal-cli/.env.signal.local
set +a
python3 scripts/signal_cli_smoke_test.py
```

## Optional send test

```sh
set -a
. integrations/signal-cli/.env.signal.local
set +a
SIGNAL_TEST_MESSAGE='upgraded-fiesta smoke test' python3 scripts/signal_cli_smoke_test.py --send
```

## Security model

- Keep `SIGNAL_BIND_HOST=127.0.0.1` unless the gateway is protected by VPN, SSH tunnel, or reverse proxy authentication.
- Do not commit `.env.signal.local`.
- Do not commit `integrations/signal-cli/data/`.
- Treat the Signal state directory as credential material because it contains account/session keys.
- Use a dedicated automation number or a linked device. Avoid coupling production automation to a personal primary device unless that is intentional.

## iPhone/a-Shell role

The iPhone should not build Docker images or run the Signal daemon. It should call the already-running gateway through a controlled URL, for example:

```sh
python3 scripts/signal_cli_smoke_test.py
```

with:

```sh
export SIGNAL_API_BASE_URL='https://your-private-gateway.example'
export SIGNAL_ACCOUNT_NUMBER='+49...'
export SIGNAL_TEST_RECIPIENT='+49...'
```

## Validation checklist

1. `docker compose ... ps` shows `upgraded-fiesta-signal-api` healthy.
2. `python3 scripts/signal_cli_smoke_test.py` returns HTTP status below 400 for `/v1/about`.
3. A controlled `--send` test reaches the target recipient.
4. `.env.signal.local` and `data/signal-cli/` remain untracked.
5. Gateway is not publicly exposed without authentication.
