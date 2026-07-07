# Generated Heavy Metal Workspace Deploy

This deploy adds the Python module expected by the mobile command:

```sh
python3 -m ghm_core.cli serve --workspace "$HOME/Documents/Developer/generated_heavy_metal" --host 127.0.0.1 --port 18789
```

## iPhone / a-Shell deployment

From the repository root:

```sh
sh install/ashell_deploy_generated_heavy_metal.sh "$HOME/Documents/Developer/generated_heavy_metal"
```

Then start the local control plane:

```sh
python3 -m ghm_core.cli serve --workspace "$HOME/Documents/Developer/generated_heavy_metal" --host 127.0.0.1 --port 18789
```

Open locally:

```text
http://127.0.0.1:18789/health
http://127.0.0.1:18789/state
http://127.0.0.1:18789/manifest
```

## Endpoints

- `GET /health` returns process health.
- `GET /state` returns workspace state, recent events and paths.
- `GET /manifest` returns `.ghm_workspace.json`.
- `POST /chat` accepts JSON `{ "message": "..." }` and records a local event.

## Validation

```sh
python3 -m ghm_core.cli doctor --workspace "$HOME/Documents/Developer/generated_heavy_metal" --host 127.0.0.1 --port 18789
```

Expected: JSON with `"ok": true`.
