from __future__ import annotations

import argparse
import plistlib
from pathlib import Path

BUNDLE_ID = "com.galaxydownloader.localengine"
URL_TYPE_NAME = "com.galaxydownloader.localengine.protocol"
URL_SCHEME = "galaxy-downloader"
URL_ROLE = "Viewer"


def _info_plist(app_path: Path) -> Path:
    return app_path / "Contents" / "Info.plist"


def _clean_url_types(raw_types) -> list[dict]:
    cleaned: list[dict] = []
    for value in raw_types if isinstance(raw_types, list) else []:
        if not isinstance(value, dict):
            continue
        entry = dict(value)
        schemes = entry.get("CFBundleURLSchemes")
        if isinstance(schemes, list):
            remaining = [str(scheme) for scheme in schemes if str(scheme).lower() != URL_SCHEME]
            if remaining:
                entry["CFBundleURLSchemes"] = remaining
            else:
                entry.pop("CFBundleURLSchemes", None)
        if entry.get("CFBundleURLName") == URL_TYPE_NAME:
            # The Galaxy-owned entry is replaced below with the canonical
            # definition; unrelated URL types are preserved.
            continue
        if entry.get("CFBundleURLSchemes"):
            cleaned.append(entry)
    return cleaned


def configure_app(app_path: Path) -> Path:
    plist_path = _info_plist(app_path)
    if not plist_path.is_file():
        raise FileNotFoundError(f"macOS Info.plist not found: {plist_path}")
    with plist_path.open("rb") as handle:
        data = plistlib.load(handle)
    if not isinstance(data, dict):
        raise ValueError("macOS Info.plist root must be a dictionary")

    data["CFBundleIdentifier"] = BUNDLE_ID
    url_types = _clean_url_types(data.get("CFBundleURLTypes"))
    url_types.append(
        {
            "CFBundleTypeRole": URL_ROLE,
            "CFBundleURLName": URL_TYPE_NAME,
            "CFBundleURLSchemes": [URL_SCHEME],
        }
    )
    data["CFBundleURLTypes"] = url_types

    with plist_path.open("wb") as handle:
        plistlib.dump(data, handle, sort_keys=False)
    verify_app(app_path)
    return plist_path


def verify_app(app_path: Path) -> Path:
    plist_path = _info_plist(app_path)
    if not plist_path.is_file():
        raise FileNotFoundError(f"macOS Info.plist not found: {plist_path}")
    with plist_path.open("rb") as handle:
        data = plistlib.load(handle)
    if data.get("CFBundleIdentifier") != BUNDLE_ID:
        raise ValueError("Galaxy macOS bundle identifier is missing or incorrect")

    matching = []
    for entry in data.get("CFBundleURLTypes") or []:
        if not isinstance(entry, dict):
            continue
        schemes = [str(value).lower() for value in entry.get("CFBundleURLSchemes") or []]
        if URL_SCHEME in schemes:
            matching.append(entry)
    if len(matching) != 1:
        raise ValueError(f"Expected exactly one {URL_SCHEME} URL registration, found {len(matching)}")
    entry = matching[0]
    if entry.get("CFBundleURLName") != URL_TYPE_NAME:
        raise ValueError("Galaxy URL registration name is incorrect")
    if entry.get("CFBundleTypeRole") != URL_ROLE:
        raise ValueError("Galaxy URL registration role is incorrect")
    if [str(value).lower() for value in entry.get("CFBundleURLSchemes") or []] != [URL_SCHEME]:
        raise ValueError("Galaxy URL registration contains unexpected schemes")
    return plist_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the Galaxy Local Engine macOS app bundle.")
    parser.add_argument("--app", required=True, type=Path, help="Path to GalaxyLocalEngine.app")
    parser.add_argument("--verify", action="store_true", help="Verify only; do not modify Info.plist")
    args = parser.parse_args()

    plist_path = verify_app(args.app) if args.verify else configure_app(args.app)
    print(f"Galaxy macOS protocol metadata ready: {plist_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
