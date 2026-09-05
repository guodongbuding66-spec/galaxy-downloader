from __future__ import annotations

import argparse
import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION_FILE = ROOT / "VERSION"
APP_BUNDLE_NAME = "GalaxyLocalEngine.app"
APP_EXECUTABLE = "GalaxyLocalEngine"
APP_DISPLAY_NAME = "Galaxy Local Engine"
APP_ICON_FILE = "GalaxyLocalEngine.icns"
BUNDLE_IDENTIFIER = "com.guodongbuding66.galaxy-local-engine"
PROTOCOL_SCHEME = "galaxy-downloader"
PROTOCOL_NAME = f"{BUNDLE_IDENTIFIER}.protocol"
APP_CATEGORY = "public.app-category.utilities"


class MacOSBundleError(RuntimeError):
    pass


def read_version(path: Path = VERSION_FILE) -> str:
    try:
        version = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise MacOSBundleError(f"cannot read Local Engine VERSION: {path}") from exc
    parts = version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise MacOSBundleError(f"invalid Local Engine VERSION: {version or '<empty>'}")
    return version


def info_plist_path(app_path: Path) -> Path:
    return app_path / "Contents" / "Info.plist"


def executable_path(app_path: Path) -> Path:
    return app_path / "Contents" / "MacOS" / APP_EXECUTABLE


def resources_dir(app_path: Path) -> Path:
    return app_path / "Contents" / "Resources"


def _load_plist(app_path: Path) -> tuple[Path, dict[str, object]]:
    app = app_path.expanduser().resolve()
    if app_path.is_symlink() or not app.is_dir():
        raise MacOSBundleError(f"invalid macOS app bundle: {app_path}")
    plist_path = info_plist_path(app)
    executable = executable_path(app)
    if plist_path.is_symlink() or not plist_path.is_file():
        raise MacOSBundleError(f"missing Info.plist: {plist_path}")
    if executable.is_symlink() or not executable.is_file():
        raise MacOSBundleError(f"missing app executable: {executable}")
    try:
        with plist_path.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise MacOSBundleError(f"invalid Info.plist: {plist_path}") from exc
    if not isinstance(payload, dict):
        raise MacOSBundleError("Info.plist root must be a dictionary")
    return plist_path, payload


def configure_bundle(app_path: Path) -> dict[str, object]:
    plist_path, payload = _load_plist(app_path)
    version = read_version()
    payload.update(
        {
            "CFBundleIdentifier": BUNDLE_IDENTIFIER,
            "CFBundleName": "GalaxyLocalEngine",
            "CFBundleDisplayName": APP_DISPLAY_NAME,
            "CFBundleIconFile": APP_ICON_FILE,
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "LSApplicationCategoryType": APP_CATEGORY,
            "NSHighResolutionCapable": True,
            "CFBundleURLTypes": [
                {
                    "CFBundleURLName": PROTOCOL_NAME,
                    "CFBundleTypeRole": "Viewer",
                    "CFBundleURLSchemes": [PROTOCOL_SCHEME],
                }
            ],
        }
    )
    temporary = plist_path.with_suffix(".plist.tmp")
    with temporary.open("wb") as handle:
        plistlib.dump(payload, handle, fmt=plistlib.FMT_BINARY, sort_keys=True)
    temporary.replace(plist_path)
    validate_bundle(app_path)
    return payload


def _validate_icon(app_path: Path, payload: dict[str, object]) -> None:
    raw = str(payload.get("CFBundleIconFile") or "").strip()
    if raw != APP_ICON_FILE:
        raise MacOSBundleError(f"Info.plist CFBundleIconFile mismatch: {raw!r}")
    icon_path = resources_dir(app_path) / APP_ICON_FILE
    if icon_path.is_symlink() or not icon_path.is_file() or icon_path.stat().st_size <= 0:
        raise MacOSBundleError(f"bundle icon is missing: {icon_path}")


def validate_bundle(app_path: Path) -> dict[str, object]:
    _, payload = _load_plist(app_path)
    version = read_version()
    expected = {
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleDisplayName": APP_DISPLAY_NAME,
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSApplicationCategoryType": APP_CATEGORY,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise MacOSBundleError(f"Info.plist {key} mismatch: {payload.get(key)!r}")

    url_types = payload.get("CFBundleURLTypes")
    if not isinstance(url_types, list) or len(url_types) != 1:
        raise MacOSBundleError("Info.plist must contain exactly one CFBundleURLTypes entry")
    entry = url_types[0]
    if not isinstance(entry, dict):
        raise MacOSBundleError("CFBundleURLTypes entry must be a dictionary")
    if entry.get("CFBundleURLName") != PROTOCOL_NAME:
        raise MacOSBundleError("custom URL name mismatch")
    if entry.get("CFBundleTypeRole") != "Viewer":
        raise MacOSBundleError("custom URL role mismatch")
    if entry.get("CFBundleURLSchemes") != [PROTOCOL_SCHEME]:
        raise MacOSBundleError("custom URL scheme mismatch")

    _validate_icon(app_path.expanduser().resolve(), payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure and validate Galaxy Local Engine macOS bundle metadata.")
    parser.add_argument("--app", required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    app = Path(args.app)
    if args.validate_only:
        validate_bundle(app)
        print(f"Validated macOS bundle metadata: {app}")
    else:
        configure_bundle(app)
        print(f"Configured macOS bundle metadata: {app}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
