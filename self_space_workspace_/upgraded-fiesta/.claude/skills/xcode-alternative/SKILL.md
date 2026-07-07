---
name: xcode-alternative
description: Use when the user wants to write, build, sign, or run an iOS/Swift app without Xcode.app's GUI -- e.g. "scaffold an iOS project", "build my Swift app from the CLI", "run this in the simulator without opening Xcode", "sign an .ipa from a script", or anything about developing iOS apps from the mobile-first / remote-host workflow this repo already uses. Also use when asked to generate .xcodeproj/project.pbxproj/Info.plist files directly.
license: Original content. No proprietary Apple IDE code, binaries, or internal data are included or reproduced anywhere in this skill -- see "What this is (and isn't)" below.
---

# Xcode Alternative: standalone iOS project + build/sign/simulate workflow

## What this is (and isn't)

This is a **workflow alternative to Xcode.app's GUI**, not a clone of Xcode itself.
Xcode and Apple's iOS SDK/frameworks (UIKit, Foundation-for-iOS, etc.) are Apple's
proprietary software -- nothing here reproduces, reverse-engineers, or redistributes
any of that. What *is* fully open and legitimately reproducible:

- **Swift Package Manager** (`Package.swift`) -- Apple's own open, documented,
  non-GUI build-system format. This is the real "standalone alternative" to a
  `.xcodeproj`: a project defined entirely in plain-text Swift, buildable from
  the command line, understood by CI, and directly openable by Xcode later if
  you ever have access to a Mac.
- **Property Lists** (`Info.plist`) -- a publicly documented Apple format;
  generated here with Python's stdlib `plistlib`, not reverse-engineered.
- **`.xcodeproj`/`project.pbxproj`** -- an old-style (OpenStep) plist whose
  *file format* (not content) has long been reimplemented by open-source tools
  (XcodeGen, Tuist, the `pbxproj` PyPI package, CocoaPods). This skill can
  generate a minimal one the same way, but **cannot validate it against real
  Xcode from a non-macOS environment** -- always open it in actual Xcode (or
  run `xcodebuild -list -project X.xcodeproj`) on a Mac before trusting it.

**Hard requirement you cannot route around**: compiling and running a *real* iOS
app (one that links UIKit/SwiftUI-for-iOS, runs in the Simulator, or gets
code-signed for a device) requires Apple's Command Line Tools / iOS SDK, which
only run on macOS and are Apple's free-but-proprietary download. This skill
removes the Xcode.app *GUI* dependency, not the macOS/Apple-SDK dependency for
real device/simulator builds. Pure Swift business logic with no UIKit/SwiftUI
import can be written and unit-tested on Linux with the open-source
[swift.org](https://swift.org) toolchain -- genuinely Xcode-free *and*
Apple-free -- but it won't produce a runnable `.app`/`.ipa` on its own.

This matches the mobile-first / remote-host model already documented in this
repo (`AGENTS.md`, `iphone-dev-platform/`): drive a Mac host (your own, a CI
runner, or a cloud Mac) from the command line instead of assuming a local
Xcode GUI session.

## Part 1: Project scaffolding

`scripts/scaffold_ios_project.py` (stdlib-only Python) generates a project
skeleton without touching Xcode at all:

```sh
python3 scripts/scaffold_ios_project.py --name MyApp --bundle-id com.example.myapp --out ./MyApp
# add --with-xcodeproj only if you specifically need a literal .xcodeproj
```

This writes:
- `Package.swift` + `Sources/MyApp/MyAppApp.swift` -- a minimal SwiftUI `App`
  entry point. Prefer this path: it's the fully-open, fully-documented one.
- `MyApp/Info.plist` -- a real, valid plist (verify any edits with
  `python3 -c "import plistlib,sys; plistlib.load(open(sys.argv[1],'rb'))" Info.plist`,
  which fails loudly on malformed plists).
- `MyApp.xcodeproj/project.pbxproj` (only with `--with-xcodeproj`) -- minimal
  single-target project. **Validate on real Xcode before trusting it.**

Prefer the `Package.swift` path whenever the target doesn't strictly require a
`.xcodeproj` (test suites, libraries, command-line tools, and even many app
targets in modern Xcode can be driven straight from a Swift package).

## Part 2: Build / sign / simulate from the CLI

All of the following run on macOS with Xcode's Command Line Tools installed
(`xcode-select --install`) -- no Xcode.app window ever needs to open. If your
primary device is an iPhone with no local Mac (the operating model this repo
assumes), run these over SSH against a remote/CI Mac host.

### Build

```sh
# SwiftPM project (no .xcodeproj):
swift build -c release

# .xcodeproj-based project:
xcodebuild -project MyApp.xcodeproj -scheme MyApp \
  -destination 'generic/platform=iOS Simulator' build
```

### List available simulators and boot one

```sh
xcrun simctl list devices available
xcrun simctl boot "iPhone 15"
open -a Simulator   # only needed to *see* it; simctl itself is headless
```

### Install and launch on the simulator

```sh
xcrun simctl install booted path/to/MyApp.app
xcrun simctl launch booted com.example.myapp
```

### Run tests headlessly (no simulator GUI needed)

```sh
xcodebuild test -project MyApp.xcodeproj -scheme MyApp \
  -destination 'platform=iOS Simulator,name=iPhone 15'
```

### Code signing (device builds / real distribution)

```sh
# List available signing identities:
security find-identity -v -p codesigning

# Sign an .app bundle directly (bypassing Xcode's signing UI):
codesign --force --sign "Apple Development: you@example.com (TEAMID)" \
  --entitlements MyApp/MyApp.entitlements path/to/MyApp.app

# Verify:
codesign --verify --deep --strict --verbose=2 path/to/MyApp.app
```

Automatic signing still requires a real Apple Developer account and
provisioning profile -- that account/credential step is Apple's, not
something any tooling (open-source or not) can replace. `codesign`/
`xcodebuild -allowProvisioningUpdates` just remove the *GUI* step, matching
this skill's actual scope.

### Package for distribution

```sh
xcodebuild -exportArchive -archivePath MyApp.xcarchive \
  -exportPath ./export -exportOptionsPlist ExportOptions.plist
```

## Honesty check for this skill

Everything in "Part 1" was executed and verified in a live, non-macOS
environment: the scaffolder script ran for real, and the generated
`Info.plist` was round-tripped through Python's `plistlib` to confirm it's a
genuinely valid plist. The generated `project.pbxproj` was only checked for
balanced braces/parens -- **it has not been opened in real Xcode**, and
nothing in "Part 2" has been run, since this environment has no macOS host,
Xcode Command Line Tools, simulator, or code-signing identity available. Tell
the user this plainly if asked to "verify" the build/sign/simulate steps
directly; they need a real Mac (local or remote) for that.
