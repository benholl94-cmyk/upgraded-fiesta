#!/usr/bin/env python3
from __future__ import annotations
import json, tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXPECTED=['Cargo.toml','README.md','Dockerfile','docker-compose.yml','Makefile','config/heavy-metal.json','config/heavy-metal.toml','scripts/init-db.sql','ui/package.json']
def main():
    missing=[p for p in EXPECTED if not (ROOT/p).is_file()]
    empty=[p for p in EXPECTED if (ROOT/p).is_file() and (ROOT/p).stat().st_size==0]
    cargo=tomllib.loads((ROOT/'Cargo.toml').read_text())
    members=cargo['workspace']['members']
    member_missing=[m for m in members if not (ROOT/m/'Cargo.toml').is_file()]
    src_missing=[]
    for m in members:
        if not ((ROOT/m/'src/lib.rs').is_file() or (ROOT/m/'src/main.rs').is_file()): src_missing.append(m)
    json.loads((ROOT/'config/heavy-metal.json').read_text())
    json.loads((ROOT/'ui/package.json').read_text())
    ok=not missing and not empty and not member_missing and not src_missing
    print(json.dumps({'ok':ok,'missing':missing,'empty':empty,'workspace_members':len(members),'member_missing':member_missing,'src_missing':src_missing},indent=2,sort_keys=True))
    return 0 if ok else 1
if __name__=='__main__': raise SystemExit(main())
