from __future__ import annotations

import pathlib
import plistlib
import subprocess
import sys

SCRIPT = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "xcode-alternative"
    / "scripts"
    / "scaffold_ios_project.py"
)


def test_scaffold_writes_package_swift_and_valid_plist(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "DemoApp"
    proc = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--name", "DemoApp",
            "--bundle-id", "com.example.demoapp",
            "--out", str(out),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.returncode == 0, proc.stderr

    package_swift = (out / "Package.swift").read_text()
    assert "com.example.demoapp" not in package_swift  # bundle id isn't a Package.swift concern
    assert 'name: "DemoApp"' in package_swift

    app_entry = (out / "Sources" / "DemoApp" / "DemoAppApp.swift").read_text()
    assert "@main" in app_entry
    assert "struct DemoAppApp: App" in app_entry

    plist_path = out / "DemoApp" / "Info.plist"
    with plist_path.open("rb") as handle:
        data = plistlib.load(handle)
    assert data["CFBundleIdentifier"] == "com.example.demoapp"
    assert data["CFBundleName"] == "DemoApp"
    assert data["LSRequiresIPhoneOS"] is True


def test_scaffold_with_xcodeproj_generates_balanced_pbxproj(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "DemoApp"
    proc = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--name", "DemoApp",
            "--bundle-id", "com.example.demoapp",
            "--out", str(out),
            "--with-xcodeproj",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.returncode == 0, proc.stderr

    pbxproj_path = out / "DemoApp.xcodeproj" / "project.pbxproj"
    text = pbxproj_path.read_text()

    # This is the extent of what's checkable without real Xcode/macOS: the
    # generated OpenStep-plist-style text is at least structurally sound.
    depth = 0
    for char in text:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        assert depth >= 0, "unbalanced braces in generated project.pbxproj"
    assert depth == 0

    paren_depth = 0
    for char in text:
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
    assert paren_depth == 0

    assert "com.example.demoapp" in text
    assert text.startswith("// !$*UTF8*$!")


def test_scaffold_without_xcodeproj_flag_skips_it(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "DemoApp"
    subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--name", "DemoApp",
            "--bundle-id", "com.example.demoapp",
            "--out", str(out),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert not (out / "DemoApp.xcodeproj").exists()
