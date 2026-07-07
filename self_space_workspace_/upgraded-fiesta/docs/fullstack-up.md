# Fullstack Up

Production startup path for `benholl94-cmyk/upgraded-fiesta`.

## Added files

- `.env.production.example` supplies the required runtime variables.
- `deploy/fullstack-compose.yml` starts Postgres with pgvector, Redis, the Rust gateway build, and an nginx-served UI.
- `scripts/fullstack_up.sh` validates the repository, checks the compose configuration, starts the stack, and prints service state.
- `scripts/remote_fullstack_up.sh` clones or refreshes the repository on a server and then delegates to `scripts/fullstack_up.sh`.
- `scripts/fullstack_status.sh` and `scripts/fullstack_down.sh` provide operational status and shutdown commands.

## Server usage

```sh
git clone https://github.com/benholl94-cmyk/upgraded-fiesta.git
cd upgraded-fiesta
cp .env.production.example .env
# edit POSTGRES_PASSWORD before public deployment
sh scripts/fullstack_up.sh
```

## Remote bootstrap file

`scripts/remote_fullstack_up.sh` may be copied to a server and run with `sh`. It requires `git`, Docker, and the Docker Compose plugin.

## Ports

- Gateway: `${GATEWAY_PORT:-8080}`
- UI: `${UI_PORT:-3000}`
- Postgres: bound to `127.0.0.1` by default
- Redis: bound to `127.0.0.1` by default

## Validation

```sh
python3 scripts/validate_repo.py
docker compose -f deploy/fullstack-compose.yml config
docker compose -f deploy/fullstack-compose.yml ps
```

## Known remaining hardening item

The current Rust gateway binary is still the repository scaffold entrypoint. The deployment layer is now present, but the gateway process should be upgraded to a persistent HTTP service before exposing port 8080 to untrusted networks.
