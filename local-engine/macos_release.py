#!/usr/bin/env python3
"""Build a deterministic macOS DMG from an assembled GalaxyLocalEngine.app.

Signing and notarization are intentionally out of scope here. The input app must
already be a runnable release bundle and carry installed.flag so it uses writable
per-user runtime paths even when launched directly from the read-only DMG.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VERSION_FILE = ROOT / "VERSION"
APP_BUNDLE_NAME = "GalaxyLocalEngine.app"
APP_EXECUTABLE = "GalaxyLocalEngine"
VOLUME_NAME = "Galaxy Local Engine"
INSTALLED_MARKER = "installed.flag"


class MacOSReleaseError(RuntimeError):
    pass


def read_version(path: Path = VERSION_FILE) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise MacOSReleaseError(f"cannot read version file: {path}") from exc
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise MacOSReleaseError(f"invalid Local Engine release version: {value or '<empty>'}")
    return value


def normalize_architecture(value: str) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "amd64": "x64",
        "x86_64": "x64",
        "x64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    try:
        return aliases[raw]
    except KeyError as exc:
        raise MacOSReleaseError(f"unsupported macOS architecture: {raw or '<empty>'}") from exc


def artifact_path(output_dir: Path, architecture: str) -> Path:
    label = normalize_architecture(architecture)
    return output_dir / f"GalaxyLocalEngine-macOS-{label}.dmg"


def app_executable(app_path: Path) -> Path:
    return app_path / "Contents" / "MacOS" / APP_EXECUTABLE


def app_runtime_dir(app_path: Path) -> Path:
    return app_path / "Contents" / "MacOS"


def validate_app_bundle(app_path: Path) -> Path:
    app = app_path.expanduser().resolve()
    if app_path.is_symlink() or not app.is_dir():
        raise MacOSReleaseError(f"macOS app bundle is invalid: {app_path}")
    info_plist = app / "Contents" / "Info.plist"
    executable = app_executable(app)
    runtime_dir = app_runtime_dir(app)
    version_file = runtime_dir / "VERSION"
    marker = runtime_dir / INSTALLED_MARKER
    for path, label in (
        (info_plist, "Info.plist"),
        (executable, "app executable"),
        (version_file, "bundled VERSION"),
        (marker, "installed runtime marker"),
    ):
        if path.is_symlink() or not path.is_file():
            raise MacOSReleaseError(f"macOS app is missing {label}: {path}")
    if not os.access(executable, os.X_OK):
        raise MacOSReleaseError(f"macOS app executable is not executable: {executable}")
    bundled_version = version_file.read_text(encoding="utf-8").strip()
    if bundled_version != read_version():
        raise MacOSReleaseError(
            f"bundled VERSION {bundled_version!r} does not match Local Engine VERSION {read_version()!r}"
        )
    return app


def _run(command: list[str], *, timeout: int = 300) -> str:
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        output = completed.stdout[-4000:] if completed.stdout else ""
        raise MacOSReleaseError(
            f"command failed with exit code {completed.returncode}: {command[0]}\n{output}"
        )
    return completed.stdout or ""


def prepare_dmg_staging(app_path: Path, staging_dir: Path) -> Path:
    app = validate_app_bundle(app_path)
    ditto = shutil.which("ditto")
    if not ditto:
        raise MacOSReleaseError("ditto is unavailable; macOS DMG staging requires Apple ditto")
    staging = staging_dir.expanduser().resolve()
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    staged_app = staging / APP_BUNDLE_NAME
    _run([ditto, str(app), str(staged_app)])
    applications = staging / "Applications"
    applications.symlink_to("/Applications", target_is_directory=True)
    validate_app_bundle(staged_app)
    if not applications.is_symlink() or os.readlink(applications) != "/Applications":
        raise MacOSReleaseError("DMG staging Applications link is invalid")
    return staging


def build_dmg(app_path: Path, output_dir: Path, architecture: str) -> Path:
    if sys.platform != "darwin":
        raise MacOSReleaseError("macOS DMG creation must run on macOS")
    hdiutil = shutil.which("hdiutil")
    if not hdiutil:
        raise MacOSReleaseError("hdiutil is unavailable")
    output_root = output_dir.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output = artifact_path(output_root, architecture)
    with tempfile.TemporaryDirectory(prefix="galaxy-macos-dmg-") as temp_name:
        staging = prepare_dmg_staging(app_path, Path(temp_name) / "staging")
        _run(
            [
                hdiutil,
                "create",
                "-volname",
                VOLUME_NAME,
                "-srcfolder",
                str(staging),
                "-format",
                "UDZO",
                "-ov",
                str(output),
            ]
        )
    if output.is_symlink() or not output.is_file() or output.stat().st_size <= 0:
        raise MacOSReleaseError(f"DMG output is invalid: {output}")
    return output


def print_plan(architecture: str, output_dir: Path) -> None:
    payload = {
        "architecture": normalize_architecture(architecture),
        "artifact": artifact_path(output_dir, architecture).name,
        "volumeName": VOLUME_NAME,
        "appBundle": APP_BUNDLE_NAME,
        "applicationsLink": "/Applications",
        "format": "UDZO",
        "version": read_version(),
    }
    print(json.dumps(payload, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Galaxy Local Engine macOS DMG.")
    parser.add_argument("--app")
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--print-plan", action="store_true")
    args = parser.parse_args()

    if args.print_plan:
        print_plan(args.architecture, Path(args.output_dir))
        return 0
    if not args.app:
        parser.error("--app is required unless --print-plan is used")
    output = build_dmg(Path(args.app), Path(args.output_dir), args.architecture)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
