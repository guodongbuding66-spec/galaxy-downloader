#!/usr/bin/env python3
"""Finalize Galaxy Local Engine macOS release artifacts from one app bundle.

Developer ID signing and notarization are intentionally out of scope here. The
finalization step installs the branded icon, writes stable bundle/protocol
metadata, and applies a verified ad-hoc signature after all bundled tools and
runtime markers are present. The companion ZIP is then rebuilt and verified from
that exact finalized app before the DMG is created, preventing distribution
formats from drifting apart.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import generate_macos_icon
import macos_bundle


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


def companion_zip_path(output_dir: Path, architecture: str) -> Path:
    label = normalize_architecture(architecture)
    return output_dir / f"GalaxyLocalEngine-macOS-{label}.zip"


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
    marker = app_runtime_dir(app) / INSTALLED_MARKER
    for path, label in (
        (info_plist, "Info.plist"),
        (executable, "app executable"),
        (marker, "installed runtime marker"),
    ):
        if path.is_symlink() or not path.is_file():
            raise MacOSReleaseError(f"macOS app is missing {label}: {path}")
    if not os.access(executable, os.X_OK):
        raise MacOSReleaseError(f"macOS app executable is not executable: {executable}")
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


def _codesign_path() -> str:
    codesign = shutil.which("codesign")
    if not codesign:
        raise MacOSReleaseError("codesign is unavailable")
    return codesign


def _ditto_path() -> str:
    ditto = shutil.which("ditto")
    if not ditto:
        raise MacOSReleaseError("ditto is unavailable")
    return ditto


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_sha256_sidecar(path: Path) -> Path:
    sidecar = Path(str(path) + ".sha256")
    sidecar.write_text(f"{_sha256(path)}  {path.name}\n", encoding="utf-8")
    return sidecar


def validate_distribution_app(app_path: Path) -> Path:
    """Validate finalized bundle identity, icon, protocol metadata and signature."""
    if sys.platform != "darwin":
        raise MacOSReleaseError("macOS distribution validation must run on macOS")
    app = validate_app_bundle(app_path)
    macos_bundle.validate_bundle(app)
    _run([_codesign_path(), "--verify", "--deep", "--strict", "--verbose=2", str(app)])
    return app


def prepare_distribution_app(app_path: Path) -> Path:
    """Brand, configure and ad-hoc sign the fully assembled application bundle."""
    if sys.platform != "darwin":
        raise MacOSReleaseError("macOS distribution preparation must run on macOS")
    app = validate_app_bundle(app_path)
    iconutil = shutil.which("iconutil")
    if not iconutil:
        raise MacOSReleaseError("iconutil is unavailable")
    codesign = _codesign_path()

    resources = macos_bundle.resources_dir(app)
    resources.mkdir(parents=True, exist_ok=True)
    icon_path = resources / macos_bundle.APP_ICON_FILE
    with tempfile.TemporaryDirectory(prefix="galaxy-macos-icon-") as temp_name:
        iconset = generate_macos_icon.generate_iconset(Path(temp_name) / "GalaxyLocalEngine.iconset")
        _run([iconutil, "--convert", "icns", "--output", str(icon_path), str(iconset)])

    macos_bundle.configure_bundle(app)
    _run(
        [
            codesign,
            "--force",
            "--deep",
            "--sign",
            "-",
            "--timestamp=none",
            str(app),
        ]
    )
    return validate_distribution_app(app)


def validate_companion_zip(zip_path: Path, package_name: str) -> Path:
    """Extract a release ZIP and verify its embedded finalized application."""
    if sys.platform != "darwin":
        raise MacOSReleaseError("macOS ZIP validation must run on macOS")
    archive = zip_path.expanduser().resolve()
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size <= 0:
        raise MacOSReleaseError(f"macOS ZIP is invalid: {zip_path}")
    with tempfile.TemporaryDirectory(prefix="galaxy-macos-zip-check-") as temp_name:
        destination = Path(temp_name)
        _run([_ditto_path(), "-x", "-k", str(archive), str(destination)])
        extracted_app = destination / package_name / APP_BUNDLE_NAME
        validate_distribution_app(extracted_app)
    return archive


def refresh_companion_zip(app_path: Path, output_dir: Path, architecture: str) -> Path:
    """Rebuild the architecture ZIP from the same finalized app used by the DMG."""
    app = validate_distribution_app(app_path)
    package_root = app.parent
    if package_root.is_symlink() or not package_root.is_dir():
        raise MacOSReleaseError(f"macOS package root is invalid: {package_root}")
    output_root = output_dir.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    archive = companion_zip_path(output_root, architecture)
    archive.unlink(missing_ok=True)
    _run(
        [
            _ditto_path(),
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(package_root),
            str(archive),
        ]
    )
    validate_companion_zip(archive, package_root.name)
    _write_sha256_sidecar(archive)
    return archive


def prepare_dmg_staging(app_path: Path, staging_dir: Path) -> Path:
    app = validate_distribution_app(app_path)
    staging = staging_dir.expanduser().resolve()
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    staged_app = staging / APP_BUNDLE_NAME
    _run([_ditto_path(), str(app), str(staged_app)])
    applications = staging / "Applications"
    applications.symlink_to("/Applications", target_is_directory=True)
    validate_distribution_app(staged_app)
    if not applications.is_symlink() or os.readlink(applications) != "/Applications":
        raise MacOSReleaseError("DMG staging Applications link is invalid")
    return staging


def build_dmg(
    app_path: Path,
    output_dir: Path,
    architecture: str,
    *,
    prepared_app: bool = False,
) -> Path:
    if sys.platform != "darwin":
        raise MacOSReleaseError("macOS DMG creation must run on macOS")
    hdiutil = shutil.which("hdiutil")
    if not hdiutil:
        raise MacOSReleaseError("hdiutil is unavailable")
    app = validate_distribution_app(app_path) if prepared_app else prepare_distribution_app(app_path)
    output_root = output_dir.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    # The workflow may have produced an interim ZIP before distribution metadata
    # and signing were added. Always replace it from this exact finalized app so
    # ZIP and DMG expose the same identity, icon, protocol and signature contract.
    refresh_companion_zip(app, output_root, architecture)

    output = artifact_path(output_root, architecture)
    with tempfile.TemporaryDirectory(prefix="galaxy-macos-dmg-") as temp_name:
        staging = prepare_dmg_staging(app, Path(temp_name) / "staging")
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
        "companionZip": companion_zip_path(output_dir, architecture).name,
        "volumeName": VOLUME_NAME,
        "appBundle": APP_BUNDLE_NAME,
        "applicationsLink": "/Applications",
        "format": "UDZO",
        "version": read_version(),
        "bundleIdentifier": macos_bundle.BUNDLE_IDENTIFIER,
        "protocolScheme": macos_bundle.PROTOCOL_SCHEME,
        "bundleIcon": macos_bundle.APP_ICON_FILE,
        "signing": "ad-hoc verified",
        "packagingModel": "one finalized app for ZIP and DMG",
    }
    print(json.dumps(payload, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize Galaxy Local Engine macOS apps and build DMGs.")
    parser.add_argument("--app")
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("--architecture")
    parser.add_argument("--print-plan", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--prepared-app",
        action="store_true",
        help="Build DMG from an already finalized app; validate it without mutating/re-signing.",
    )
    args = parser.parse_args()

    if args.print_plan:
        if not args.architecture:
            parser.error("--architecture is required with --print-plan")
        print_plan(args.architecture, Path(args.output_dir))
        return 0

    if not args.app:
        parser.error("--app is required")
    app = Path(args.app)

    if args.prepare_only:
        if args.prepared_app:
            parser.error("--prepare-only and --prepared-app cannot be combined")
        prepared = prepare_distribution_app(app)
        print(prepared)
        return 0

    if not args.architecture:
        parser.error("--architecture is required when building a DMG")
    output = build_dmg(
        app,
        Path(args.output_dir),
        args.architecture,
        prepared_app=bool(args.prepared_app),
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
