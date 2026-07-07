#!/usr/bin/env python3
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
    "scripts/ashell_fullstack_up.py",
    "scripts/ashell_fullstack_up.sh",
]

for rel in FILES:
    target = Path(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(urlopen(BASE + rel, timeout=30).read())
    print("synced", rel)
print("done")
