#!/bin/sh
WORKSPACE="${1:-$HOME/Documents/Developer/generated_heavy_metal}"
python3 -m ghm_core.cli init-workspace --workspace "$WORKSPACE" --host 127.0.0.1 --port 18789
