# Hetzner Signal Gateway Runbook

## Decision

Use a small Hetzner Cloud VPS with Docker for the real Signal gateway. The iPhone/a-Shell environment remains the client/control plane.

## Why this option

`signal-cli` needs a long-running daemon, persistent local state, filesystem access, predictable debugging, and controlled networking. A VPS gives full Docker control and avoids platform-specific volume/runtime caveats from app platforms.

## Recommended baseline

- Provider: Hetzner Cloud or equivalent VPS provider
- Region: Germany or Finland for low latency from Germany
- OS: Ubuntu LTS
- App: Docker CE / Docker runtime
- Exposure model: do not expose port 9922 publicly
- Access model: SSH tunnel, Tailscale/private VPN, or reverse proxy with authentication

## Cloud-init deployment

Use `deploy/hetzner/signal-gateway-cloud-init.yml` as the user-data/cloud-init script when creating the VPS.

The cloud-init script installs Docker, writes a local gateway env file, pulls the compose file from this repository, enables a basic firewall, and starts the `signal-cli-rest-api` container bound to `127.0.0.1:9922`.

## After server boot

SSH into the server:

```sh
ssh root@SERVER_IP
```

Check container state:

```sh
docker ps
```

Check local gateway endpoint:

```sh
curl -fsS http://127.0.0.1:9922/v1/about
```

Edit local Signal values:

```sh
nano /opt/upgraded-fiesta-signal/.env.signal.local
```

Restart after edits:

```sh
docker compose --env-file /opt/upgraded-fiesta-signal/.env.signal.local -f /opt/upgraded-fiesta-signal/docker-compose.signal.yml up -d
```

## Connect from iPhone/a-Shell through SSH tunnel

From iPhone/a-Shell:

```sh
ssh -L 9922:127.0.0.1:9922 root@SERVER_IP
```

Keep that SSH session open. In a second a-Shell tab/session, run:

```sh
python3 scripts/ashell_signal_client_setup.py --gateway http://127.0.0.1:9922 --write --check
```

## Operational rules

- Never commit `/opt/upgraded-fiesta-signal/.env.signal.local`.
- Never commit `/opt/upgraded-fiesta-signal/data/signal-cli`.
- Keep gateway port `9922` bound to localhost unless a private network or authenticated reverse proxy is configured.
- Back up `/opt/upgraded-fiesta-signal/data/signal-cli` securely; it contains Signal account/session state.

## Remaining manual actions

The server can be bootstrapped automatically, but Signal account registration/linking cannot be truthfully automated here without the account phone number, verification flow, and/or linked-device approval from the Signal app.
