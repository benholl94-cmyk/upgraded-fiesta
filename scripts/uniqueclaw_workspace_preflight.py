#!/usr/bin/env python3
from __future__ import annotations
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "Cargo.toml"
MEMBER_RE = re.compile(r'members\s*=\s*\[(.*?)\]', re.S)
STRING_RE = re.compile(r'"([^"]+)"')


def workspace_members() -> list[Path]:
    text = MANIFEST.read_text(encoding="utf-8")
    match = MEMBER_RE.search(text)
    if not match:
        raise SystemExit("ERROR: no workspace members found")
    return [ROOT / item for item in STRING_RE.findall(match.group(1))]


def has_explicit_target(cargo_toml: Path) -> bool:
    text = cargo_toml.read_text(encoding="utf-8")
    return any(marker in text for marker in ("[[bin]]", "[lib]", "[[example]]", "[[test]]", "[[bench]]"))


def has_implicit_target(crate: Path) -> bool:
    return (crate / "src" / "lib.rs").exists() or (crate / "src" / "main.rs").exists()


def main() -> int:
    failures = []
    for member in workspace_members():
        cargo = member / "Cargo.toml"
        if not cargo.exists():
            failures.append(f"{member.relative_to(ROOT)}: missing Cargo.toml")
            continue
        if not has_implicit_target(member) and not has_explicit_target(cargo):
            failures.append(f"{member.relative_to(ROOT)}: no Rust target")
    if failures:
        print("UNIQUECLAW_PREFLIGHT_FAILED")
        for failure in failures:
            print("- " + failure)
        return 2
    print("UNIQUECLAW_PREFLIGHT_OK")
    cargo_bin = shutil.which("cargo")
    if cargo_bin:
        return subprocess.call([cargo_bin, "check", "--workspace"], cwd=str(ROOT))
    print("cargo not found; structural validation only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
