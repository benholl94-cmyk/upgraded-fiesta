# UniqueClaw Production Build

## Immediate failure fixed

The failed job reported that `cargo check --workspace` could not run because the workspace member `crates/hm-sdk` had no Rust target file or explicit target declaration.

This branch adds:

- `crates/hm-sdk/src/lib.rs`
- `scripts/uniqueclaw_workspace_preflight.py`

The new preflight validates all workspace members before `cargo check --workspace`.

## Validation order

```sh
python3 scripts/uniqueclaw_workspace_preflight.py
cargo check --workspace
cargo test --workspace
```

## UniqueClaw operating model

- iPhone/a-Shell remains the local control plane.
- Rust/Cargo builds run in Codex, GitHub Actions, or another Linux execution plane.
- No local iPhone Docker assumption.
- No local IP hardcoding in committed files.

## Next build gate

After this fix, the next failure, if any, is expected to be a real Rust dependency/API error rather than a workspace topology error.
