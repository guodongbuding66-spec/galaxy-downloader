#!/usr/bin/env python3
"""Build verified Linux desktop packages from a prepared Local Engine payload.

The input directory must already have been produced by prepare-unix-bundle.py.
This module never redownloads yt-dlp or FFmpeg. It only adds Linux desktop
metadata and invokes pinned, checksum-verified packaging tools.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
VERSION_FILE = ROOT / "VERSION"
PACKAGE_NAME = "galaxy-local-engine"
APP_NAME = "Galaxy Local Engine"
APP_ID = "galaxy-local-engine"
HOMEPAGE = "https://galaxy-downloader.guodongbuding66.workers.dev/zh"
INSTALL_ROOT = Path("/opt/galaxy-local-engine")
LAUNCHER_PATH = Path("/usr/bin/galaxy-local-engine")
DESKTOP_PATH = Path("/usr/share/applications/galaxy-local-engine.desktop")
ICON_PATH = Path("/usr/share/icons/hicolor/scalable/apps/galaxy-local-engine.svg")
MAX_TOOL_BYTES = 64 * 1024 * 1024
USER_AGENT = "GalaxyLocalEngineLinuxRelease/1.0"

REQUIRED_PAYLOAD = (
    "GalaxyLocalEngine",
    "yt-dlp",
    "ffmpeg/bin/ffmpeg",
    "ffmpeg/bin/ffprobe",
    "VERSION",
    "BUNDLE_MANIFEST.json",
)


class LinuxReleaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    repository: str
    asset_id: int
    sha256: str

    @property
    def url(self) -> str:
        if self.asset_id <= 0:
            raise LinuxReleaseError(f"invalid asset id for {self.repository}")
        return f"https://api.github.com/repos/{self.repository}/releases/assets/{self.asset_id}"


@dataclass(frozen=True)
class LinuxToolPlan:
    architecture: str
    appimage_arch: str
    artifact_label: str
    appimagetool: ToolSpec
    runtime: ToolSpec
    nfpm: ToolSpec


_TOOL_PLANS: dict[str, LinuxToolPlan] = {
    "amd64": LinuxToolPlan(
        architecture="amd64",
        appimage_arch="x86_64",
        artifact_label="x64",
        appimagetool=ToolSpec(
            "AppImage/appimagetool",
            324406882,
            "a6d71e2b6cd66f8e8d16c37ad164658985e0cf5fcaa950c90a482890cb9d13e0",
        ),
        runtime=ToolSpec(
            "AppImage/type2-runtime",
            456065460,
            "1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf",
        ),
        nfpm=ToolSpec(
            "goreleaser/nfpm",
            453316748,
            "0660ca602b2d2d2ae4781a06c692b3eeb9d437ffea05b831d76e41f4a3188783",
        ),
    ),
    "arm64": LinuxToolPlan(
        architecture="arm64",
        appimage_arch="aarch64",
        artifact_label="arm64",
        appimagetool=ToolSpec(
            "AppImage/appimagetool",
            324406837,
            "1b00524ba8c6b678dc15ef88a5c25ec24def36cdfc7e3abb32ddcd068e8007fe",
        ),
        runtime=ToolSpec(
            "AppImage/type2-runtime",
            456064894,
            "7d5d772b7c32f0c84caf0a452a3072a5709027d7eac5856feb89a7a7a8881372",
        ),
        nfpm=ToolSpec(
            "goreleaser/nfpm",
            453316744,
            "1c0f5f2999b9a974bfb04fdb0cc3306096de530ac5dbb25d739cc5f5219c919c",
        ),
    ),
}


def normalize_architecture(value: str) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "amd64": "amd64",
        "x86_64": "amd64",
        "x64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    try:
        return aliases[raw]
    except KeyError as exc:
        raise LinuxReleaseError(
            f"unsupported Linux release architecture: {raw or '<empty>'}"
        ) from exc


def tool_plan(architecture: str) -> LinuxToolPlan:
    return _TOOL_PLANS[normalize_architecture(architecture)]


def read_version(path: Path = VERSION_FILE) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise LinuxReleaseError(f"cannot read version file: {path}") from exc
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise LinuxReleaseError(
            f"invalid Local Engine release version: {value or '<empty>'}"
        )
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise LinuxReleaseError(f"{label} must be a regular file: {path}")


def validate_payload(package_dir: Path) -> list[Path]:
    root = package_dir.resolve()
    if not root.is_dir() or root.is_symlink():
        raise LinuxReleaseError(f"portable payload directory is invalid: {package_dir}")

    for relative in REQUIRED_PAYLOAD:
        _assert_regular_file(root / relative, f"required payload {relative}")

    payload_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    source_version = read_version()
    if payload_version != source_version:
        raise LinuxReleaseError(
            f"payload VERSION {payload_version!r} does not match Local Engine VERSION {source_version!r}"
        )

    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise LinuxReleaseError(
                f"payload symlinks are not accepted: {path.relative_to(root)}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise LinuxReleaseError(
                f"payload contains a non-regular entry: {path.relative_to(root)}"
            )
        files.append(path)

    if not files:
        raise LinuxReleaseError("portable payload is empty")
    return files


def desktop_entry(exec_value: str) -> str:
    executable = str(exec_value).strip()
    if not executable or any(char in executable for char in "\r\n"):
        raise LinuxReleaseError("desktop Exec value is invalid")
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Local media download, library and AI workstation\n"
        f"Exec={executable} %u\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=Network;Utility;\n"
        "MimeType=x-scheme-handler/galaxy-downloader;\n"
        "StartupNotify=true\n"
    )


def icon_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <rect x="8" y="8" width="112" height="112" rx="28" fill="#0f172a"/>
  <path d="M64 25a39 39 0 1 0 31.5 62H66a23 23 0 1 1 18.5-36.7l11.8-10.8A39 39 0 0 0 64 25Z" fill="#e2e8f0"/>
  <path d="M66 54h38v36H66z" fill="#0ea5e9"/>
  <path d="m78 62 18 10-18 10Z" fill="#fff"/>
</svg>
"""


def launcher_script() -> str:
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        f'exec "{INSTALL_ROOT / "GalaxyLocalEngine"}" "$@"\n'
    )


def apprun_script() -> str:
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        'HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\n'
        'exec "$HERE/opt/galaxy-local-engine/GalaxyLocalEngine" "$@"\n'
    )


def _write_text(path: Path, content: str, mode: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(mode)
    return path


def prepare_appdir(package_dir: Path, appdir: Path) -> Path:
    files = validate_payload(package_dir)
    root = package_dir.resolve()
    if appdir.exists():
        shutil.rmtree(appdir)
    payload_target = appdir / "opt" / "galaxy-local-engine"
    payload_target.mkdir(parents=True, exist_ok=True)

    for source in files:
        relative = source.relative_to(root)
        target = payload_target / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    _write_text(appdir / "AppRun", apprun_script(), 0o755)
    _write_text(
        appdir / f"{APP_ID}.desktop",
        desktop_entry("GalaxyLocalEngine"),
        0o644,
    )
    _write_text(appdir / f"{APP_ID}.svg", icon_svg(), 0o644)

    app_binary = appdir / "GalaxyLocalEngine"
    app_binary.symlink_to("opt/galaxy-local-engine/GalaxyLocalEngine")
    return appdir


def prepare_nfpm_staging(
    package_dir: Path,
    staging: Path,
    architecture: str,
) -> Path:
    files = validate_payload(package_dir)
    root = package_dir.resolve()
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    launcher = _write_text(staging / "galaxy-local-engine", launcher_script(), 0o755)
    desktop = _write_text(
        staging / f"{APP_ID}.desktop",
        desktop_entry(str(LAUNCHER_PATH)),
        0o644,
    )
    icon = _write_text(staging / f"{APP_ID}.svg", icon_svg(), 0o644)

    contents: list[dict[str, object]] = []
    for source in files:
        relative = source.relative_to(root).as_posix()
        contents.append(
            {
                "src": str(source),
                "dst": str(INSTALL_ROOT / relative),
                "file_info": {"mode": stat.S_IMODE(source.stat().st_mode)},
            }
        )
    contents.extend(
        [
            {
                "src": str(launcher),
                "dst": str(LAUNCHER_PATH),
                "file_info": {"mode": 0o755},
            },
            {
                "src": str(desktop),
                "dst": str(DESKTOP_PATH),
                "file_info": {"mode": 0o644},
            },
            {
                "src": str(icon),
                "dst": str(ICON_PATH),
                "file_info": {"mode": 0o644},
            },
        ]
    )

    config = {
        "name": PACKAGE_NAME,
        "arch": normalize_architecture(architecture),
        "platform": "linux",
        "version": read_version(),
        "section": "utils",
        "priority": "optional",
        "maintainer": "Galaxy Downloader",
        "vendor": "Galaxy Downloader",
        "homepage": HOMEPAGE,
        "description": "Local media download, library, transcript and AI workstation.",
        "contents": contents,
    }
    config_path = staging / "nfpm.yaml"
    # JSON is valid YAML and keeps the release script dependency-free.
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config_path


def _download_verified(spec: ToolSpec, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    headers = {
        "Accept": "application/octet-stream",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(spec.url, headers=headers)
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    written = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_TOOL_BYTES:
                raise LinuxReleaseError(f"{spec.repository} asset exceeds size policy")
            with temporary.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_TOOL_BYTES:
                        raise LinuxReleaseError(
                            f"{spec.repository} asset exceeds size policy"
                        )
                    digest.update(chunk)
                    output.write(chunk)
        actual = digest.hexdigest()
        if actual.lower() != spec.sha256.lower():
            raise LinuxReleaseError(
                f"SHA-256 mismatch for {spec.repository}: expected {spec.sha256}, got {actual}"
            )
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _extract_nfpm(archive: Path, destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if not members:
            raise LinuxReleaseError("nFPM archive is empty")
        for member in members:
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise LinuxReleaseError(f"unsafe nFPM archive member: {member.name}")
            if member.issym() or member.islnk():
                raise LinuxReleaseError(
                    f"nFPM archive links are not accepted: {member.name}"
                )
        bundle.extractall(destination, filter="data")

    candidates = [
        path
        for path in destination.rglob("nfpm")
        if path.is_file() and not path.is_symlink()
    ]
    if len(candidates) != 1:
        raise LinuxReleaseError(
            f"nFPM archive must contain exactly one nfpm binary; found {len(candidates)}"
        )
    candidates[0].chmod(candidates[0].stat().st_mode | 0o111)
    return candidates[0]


def prepare_tools(
    plan: LinuxToolPlan,
    directory: Path,
) -> tuple[Path, Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    appimagetool = _download_verified(
        plan.appimagetool,
        directory / "appimagetool.AppImage",
    )
    runtime = _download_verified(plan.runtime, directory / "runtime")
    nfpm_archive = _download_verified(plan.nfpm, directory / "nfpm.tar.gz")
    appimagetool.chmod(appimagetool.stat().st_mode | 0o111)
    runtime.chmod(runtime.stat().st_mode | 0o111)
    nfpm = _extract_nfpm(nfpm_archive, directory / "nfpm-extracted")
    return appimagetool, runtime, nfpm


def _run(
    command: Iterable[str | os.PathLike[str]],
    *,
    env: dict[str, str] | None = None,
) -> None:
    argv = [str(item) for item in command]
    completed = subprocess.run(
        argv,
        env=env,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        output = completed.stdout[-4000:] if completed.stdout else ""
        raise LinuxReleaseError(
            f"command failed with exit code {completed.returncode}: {argv[0]}\n{output}"
        )


def artifact_paths(output_dir: Path, architecture: str) -> dict[str, Path]:
    plan = tool_plan(architecture)
    prefix = output_dir / f"GalaxyLocalEngine-Linux-{plan.artifact_label}"
    return {
        "appimage": prefix.with_suffix(".AppImage"),
        "deb": prefix.with_suffix(".deb"),
        "rpm": prefix.with_suffix(".rpm"),
    }


def build_packages(
    package_dir: Path,
    output_dir: Path,
    architecture: str,
) -> dict[str, Path]:
    plan = tool_plan(architecture)
    validate_payload(package_dir)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = artifact_paths(output_dir, architecture)

    with tempfile.TemporaryDirectory(prefix="galaxy-linux-release-") as temp_name:
        temp = Path(temp_name)
        appdir = prepare_appdir(package_dir, temp / "GalaxyLocalEngine.AppDir")
        config_path = prepare_nfpm_staging(
            package_dir,
            temp / "nfpm-staging",
            architecture,
        )
        appimagetool, runtime, nfpm = prepare_tools(plan, temp / "tools")

        env = os.environ.copy()
        env.update(
            {
                "APPIMAGE_EXTRACT_AND_RUN": "1",
                "ARCH": plan.appimage_arch,
                "VERSION": read_version(),
            }
        )
        _run(
            [
                appimagetool,
                "--runtime-file",
                runtime,
                "--no-appstream",
                appdir,
                outputs["appimage"],
            ],
            env=env,
        )
        _run(
            [nfpm, "package", "-f", config_path, "-p", "deb", "-t", outputs["deb"]]
        )
        _run(
            [nfpm, "package", "-f", config_path, "-p", "rpm", "-t", outputs["rpm"]]
        )

    for name, output in outputs.items():
        _assert_regular_file(output, f"{name} output")
        if output.stat().st_size <= 0:
            raise LinuxReleaseError(f"{name} output is empty")
        if name == "appimage":
            output.chmod(output.stat().st_mode | 0o111)
    return outputs


def print_plan(architecture: str) -> None:
    plan = tool_plan(architecture)
    payload = {
        "architecture": plan.architecture,
        "appimageArchitecture": plan.appimage_arch,
        "artifactLabel": plan.artifact_label,
        "version": read_version(),
        "tools": {
            "appimagetool": {
                "assetId": plan.appimagetool.asset_id,
                "sha256": plan.appimagetool.sha256,
            },
            "runtime": {
                "assetId": plan.runtime.asset_id,
                "sha256": plan.runtime.sha256,
            },
            "nfpm": {
                "assetId": plan.nfpm.asset_id,
                "sha256": plan.nfpm.sha256,
            },
        },
    }
    print(json.dumps(payload, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build AppImage, DEB and RPM from a prepared Galaxy Local Engine Linux payload."
    )
    parser.add_argument("--package-dir", required=True)
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--print-plan", action="store_true")
    args = parser.parse_args()

    if args.print_plan:
        print_plan(args.architecture)
        return 0

    outputs = build_packages(
        Path(args.package_dir),
        Path(args.output_dir),
        args.architecture,
    )
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
