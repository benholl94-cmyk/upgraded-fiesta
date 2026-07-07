# Signal Gateway Provider Matrix

## Decision rule

The Signal gateway needs a long-running Docker process, persistent local filesystem state, predictable outbound networking, SSH-level diagnostics, and a safe way to keep port `9922` private.

## Ranked options

### 1. netcup VPS x86

Best niche EU alternative after Hetzner.

Reasons:

- German/EU provider profile.
- x86 VPS avoids ARM-specific native-image uncertainty.
- NVMe storage, snapshots, remote console, DDoS protection, and API are available in the VPS product line.
- Good fit for Docker + SSH tunnel deployment.

Recommended mode:

- Ubuntu or Debian VPS.
- Run `deploy/universal/signal-gateway-bootstrap.sh` over SSH as root.
- Keep `127.0.0.1:9922` private.
- Connect iPhone/a-Shell through `ssh -L 9922:127.0.0.1:9922 root@SERVER_IP`.

### 2. DigitalOcean Droplet

Best non-niche fallback when cloud-init automation is preferred.

Reasons:

- Droplets support user-data/cloud-init during creation.
- Good docs and predictable SSH workflow.
- More expensive than some EU niche VPS options but operationally simple.

Recommended mode:

- Ubuntu LTS Droplet.
- Paste `deploy/hetzner/signal-gateway-cloud-init.yml` as user-data after replacing provider naming mentally; the cloud-init content is generic Ubuntu/Docker compatible.

### 3. Oracle Cloud Always Free Ampere A1

Best cost-experiment option, not best reliability option.

Reasons:

- Can be free if capacity/account approval works.
- ARM64 may require avoiding native-specific assumptions; prefer JVM/json-rpc mode if native mode fails.
- Account and capacity friction make it unsuitable as first production recommendation.

Recommended mode:

- Set `SIGNAL_CLI_MODE=json-rpc` if `json-rpc-native` fails.
- Keep SSH tunnel model.

### 4. Vultr / OVH / IONOS / Scaleway VPS

Good generic VPS class.

Reasons:

- Suitable when they provide Ubuntu/Debian, public IPv4, SSH, Docker support, and persistent disk.
- Less optimal only because the current project has stronger Germany/EU and iPhone/a-Shell assumptions already satisfied by Hetzner/netcup.

Recommended mode:

- Use universal SSH bootstrap.

### 5. Fly.io Machines with Volume

Technically possible but not the primary production choice.

Reasons:

- Persistent volumes exist.
- Good for container-native deployments.
- Less transparent than a VPS for Signal account state, manual registration/linking, filesystem recovery, and emergency debugging.

Recommended mode:

- Only use if VPS is not acceptable.
- Keep state on a single volume.
- Do not scale horizontally.

### 6. Railway / Render with persistent storage

Fallback only.

Reasons:

- They support persistent storage concepts.
- Their platform constraints make them weaker for a private Signal transport daemon than a VPS.
- Use only if a web-app platform is mandatory.

## Final recommendation

Use this priority order:

1. netcup VPS x86
2. Hetzner Cloud VPS
3. DigitalOcean Droplet
4. Oracle Always Free Ampere A1 only for cost testing
5. Generic Ubuntu/Debian VPS
6. Fly.io/Railway/Render only as fallback

## Operational invariant

The real gateway port must remain private:

```text
signal-cli-rest-api container -> 127.0.0.1:9922 on server -> SSH tunnel/private VPN -> iPhone a-Shell client
```

Do not expose `9922` directly to the public internet.
