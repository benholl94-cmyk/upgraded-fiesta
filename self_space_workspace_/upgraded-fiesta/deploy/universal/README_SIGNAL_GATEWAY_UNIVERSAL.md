# Universal Signal Gateway VPS Bootstrap

## Purpose

Provider-independent deployment notes for the Signal gateway on any Ubuntu or Debian VPS that can run Docker.

## Target class

- netcup VPS x86
- Hetzner Cloud VPS
- DigitalOcean Droplet
- Vultr VPS
- OVH, IONOS, Scaleway, or comparable Ubuntu VPS
- Oracle Cloud VM, using `SIGNAL_CLI_MODE=json-rpc` if native mode fails on ARM

## Bootstrap artifact

Use this repository file on the server:

```text
deploy/universal/signal-gateway-bootstrap.sh
```

The script creates the permanent server directory:

```text
/opt/upgraded-fiesta-signal/
```

It also writes or uses:

```text
/opt/upgraded-fiesta-signal/.env.signal.local
/opt/upgraded-fiesta-signal/docker-compose.signal.yml
/opt/upgraded-fiesta-signal/data/signal-cli/
```

## Server verification

The gateway health endpoint is:

```text
http://127.0.0.1:9922/v1/about
```

## iPhone/a-Shell connection model

The iPhone should connect through a private transport, normally an SSH local port forward or a VPN. The mobile client config then points to:

```text
http://127.0.0.1:9922
```

## Security invariant

Port `9922` remains private on the server. Do not expose the Signal REST gateway directly to the public internet.

## Signal account state

The bootstrap does not fake Signal registration or device linking. Registration or linking needs the real Signal account flow, phone number verification, or linked-device approval.
