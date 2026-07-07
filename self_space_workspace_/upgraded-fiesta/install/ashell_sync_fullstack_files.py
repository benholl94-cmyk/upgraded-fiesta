#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

BASE = "https://raw.githubusercontent.com/benholl94-cmyk/upgraded-fiesta/main/"
FILES = [
    ".env.production.example",
    "deploy/fullstack-compose.yml",
    "deploy/gateway_service.py",
    "scripts/fullstack_up.sh",
    "scripts/fullstack_down.sh",
    "scripts/fullstack_status.sh",
    "scripts/remote_fullstack_up.sh",
    "scripts/ashell_prepare_fullstack.sh",
]


def main() -> int:
    root = Path.cwd()
    for rel in FILES:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        data = urlopen(BASE + rel, timeout=30).read()
        target.write_bytes(data)
        print(f"synced {rel}")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
