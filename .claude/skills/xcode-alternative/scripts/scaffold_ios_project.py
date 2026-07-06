#!/usr/bin/env python3
"""Scaffold a standalone, Xcode.app-free iOS project skeleton.

Generates two things, both using only open, documented formats -- no
proprietary Apple IDE data is read, copied, or reverse-engineered:

1. A SwiftPM `Package.swift` manifest + `Sources/<Name>/` layout. This is
   Apple's own open, documented, non-GUI build-system format -- the real
   "standalone alternative" to a `.xcodeproj`, usable from the command
   line or CI with no Xcode.app involved, and directly openable by Xcode
   later if the user ever has access to a Mac.
2. A minimal `.xcodeproj/project.pbxproj` + `Info.plist`, for the (less
   preferred) case where a literal Xcode project file is required. The
   `Info.plist` is generated with Python's stdlib `plistlib` (the real
   Apple-documented Property List format). `project.pbxproj` uses the
   OpenStep-plist-style structure that every open-source Xcode-project
   generator (XcodeGen, Tuist, the `pbxproj` PyPI package, etc.) already
   reimplements from the format's own text structure -- not from any
   copied Apple source. This part cannot be validated against real Xcode
   from a non-macOS environment; validate it by opening in Xcode (or
   `xcodebuild -list -project`) before trusting it.

Stdlib only, no external dependencies.
"""

from __future__ import annotations

import argparse
import plistlib
import uuid
from pathlib import Path


def _uuid24() -> str:
    """Xcode object IDs are 24 uppercase hex characters."""
    return uuid.uuid4().hex[:24].upper()


def write_package_swift(root: Path, name: str, bundle_id: str) -> None:
    """Writes the SwiftPM manifest + a minimal SwiftUI app entry point."""
    package_swift = f'''// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "{name}",
    platforms: [.iOS(.v16)],
    products: [
        .executable(name: "{name}", targets: ["{name}"])
    ],
    targets: [
        .executableTarget(name: "{name}", path: "Sources/{name}")
    ]
)
'''
    (root / "Package.swift").write_text(package_swift, encoding="utf-8")

    sources = root / "Sources" / name
    sources.mkdir(parents=True, exist_ok=True)
    app_entry = f'''import SwiftUI

@main
struct {name}App: App {{
    var body: some Scene {{
        WindowGroup {{
            ContentView()
        }}
    }}
}}

struct ContentView: View {{
    var body: some View {{
        Text("{name}, no Xcode.app required to get this far.")
            .padding()
    }}
}}
'''
    (sources / f"{name}App.swift").write_text(app_entry, encoding="utf-8")


def write_info_plist(root: Path, name: str, bundle_id: str) -> Path:
    """Real Info.plist via plistlib -- the actual, documented Apple format."""
    path = root / f"{name}" / "Info.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "CFBundleName": name,
        "CFBundleIdentifier": bundle_id,
        "CFBundleVersion": "1",
        "CFBundleShortVersionString": "1.0",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": name,
        "LSRequiresIPhoneOS": True,
        "UILaunchScreen": {},
        "UISupportedInterfaceOrientations": [
            "UIInterfaceOrientationPortrait",
            "UIInterfaceOrientationLandscapeLeft",
            "UIInterfaceOrientationLandscapeRight",
        ],
    }
    with path.open("wb") as handle:
        plistlib.dump(data, handle)
    return path


def write_minimal_xcodeproj(root: Path, name: str, bundle_id: str) -> None:
    """A minimal single-target project.pbxproj. Validate on real Xcode/macOS
    before trusting it -- see the docstring above."""
    proj_dir = root / f"{name}.xcodeproj"
    proj_dir.mkdir(parents=True, exist_ok=True)

    root_id = _uuid24()
    main_group_id = _uuid24()
    products_group_id = _uuid24()
    app_ref_id = _uuid24()
    target_id = _uuid24()
    build_config_list_project_id = _uuid24()
    build_config_list_target_id = _uuid24()
    debug_config_project_id = _uuid24()
    release_config_project_id = _uuid24()
    debug_config_target_id = _uuid24()
    release_config_target_id = _uuid24()
    sources_phase_id = _uuid24()
    frameworks_phase_id = _uuid24()
    resources_phase_id = _uuid24()

    pbxproj = f'''// !$*UTF8*$!
{{
	archiveVersion = 1;
	classes = {{
	}};
	objectVersion = 56;
	objects = {{
		{root_id} = {{
			isa = PBXProject;
			buildConfigurationList = {build_config_list_project_id};
			compatibilityVersion = "Xcode 14.0";
			developmentRegion = en;
			hasScannedForEncodings = 0;
			knownRegions = (en, Base);
			mainGroup = {main_group_id};
			productRefGroup = {products_group_id};
			projectDirPath = "";
			projectRoot = "";
			targets = ({target_id});
		}};
		{main_group_id} = {{
			isa = PBXGroup;
			children = ({products_group_id});
			sourceTree = "<group>";
		}};
		{products_group_id} = {{
			isa = PBXGroup;
			children = ({app_ref_id});
			name = Products;
			sourceTree = "<group>";
		}};
		{app_ref_id} = {{
			isa = PBXFileReference;
			explicitFileType = wrapper.application;
			includeInIndex = 0;
			path = "{name}.app";
			sourceTree = BUILT_PRODUCTS_DIR;
		}};
		{target_id} = {{
			isa = PBXNativeTarget;
			buildConfigurationList = {build_config_list_target_id};
			buildPhases = ({sources_phase_id}, {frameworks_phase_id}, {resources_phase_id});
			buildRules = ();
			dependencies = ();
			name = "{name}";
			productName = "{name}";
			productReference = {app_ref_id};
			productType = "com.apple.product-type.application";
		}};
		{sources_phase_id} = {{ isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};
		{frameworks_phase_id} = {{ isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};
		{resources_phase_id} = {{ isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};
		{debug_config_project_id} = {{
			isa = XCBuildConfiguration;
			buildSettings = {{ SWIFT_VERSION = 5.0; IPHONEOS_DEPLOYMENT_TARGET = 16.0; ONLY_ACTIVE_ARCH = YES; }};
			name = Debug;
		}};
		{release_config_project_id} = {{
			isa = XCBuildConfiguration;
			buildSettings = {{ SWIFT_VERSION = 5.0; IPHONEOS_DEPLOYMENT_TARGET = 16.0; }};
			name = Release;
		}};
		{build_config_list_project_id} = {{
			isa = XCConfigurationList;
			buildConfigurations = ({debug_config_project_id}, {release_config_project_id});
			defaultConfigurationName = Release;
		}};
		{debug_config_target_id} = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				PRODUCT_BUNDLE_IDENTIFIER = "{bundle_id}";
				PRODUCT_NAME = "$(TARGET_NAME)";
				INFOPLIST_FILE = "{name}/Info.plist";
				CODE_SIGN_STYLE = Automatic;
			}};
			name = Debug;
		}};
		{release_config_target_id} = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				PRODUCT_BUNDLE_IDENTIFIER = "{bundle_id}";
				PRODUCT_NAME = "$(TARGET_NAME)";
				INFOPLIST_FILE = "{name}/Info.plist";
				CODE_SIGN_STYLE = Automatic;
			}};
			name = Release;
		}};
		{build_config_list_target_id} = {{
			isa = XCConfigurationList;
			buildConfigurations = ({debug_config_target_id}, {release_config_target_id});
			defaultConfigurationName = Release;
		}};
	}};
	rootObject = {root_id};
}}
'''
    (proj_dir / "project.pbxproj").write_text(pbxproj, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="App/target name, e.g. MyApp")
    parser.add_argument("--bundle-id", required=True, help="e.g. com.example.myapp")
    parser.add_argument("--out", required=True, help="Output directory (created if missing)")
    parser.add_argument(
        "--with-xcodeproj",
        action="store_true",
        help="Also generate a minimal .xcodeproj/project.pbxproj (validate on real Xcode before trusting it)",
    )
    args = parser.parse_args()

    root = Path(args.out).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    write_package_swift(root, args.name, args.bundle_id)
    plist_path = write_info_plist(root, args.name, args.bundle_id)
    print(f"wrote {root / 'Package.swift'}")
    print(f"wrote {plist_path}")

    if args.with_xcodeproj:
        write_minimal_xcodeproj(root, args.name, args.bundle_id)
        print(f"wrote {root / (args.name + '.xcodeproj') / 'project.pbxproj'}")
        print("NOTE: validate the generated .xcodeproj by opening it in real Xcode "
              "(or `xcodebuild -list -project`) before trusting it -- this could not "
              "be verified against real Xcode from this environment.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
