#!/usr/bin/env python3
"""Prepare verified portable yt-dlp + FFmpeg tools for macOS/Linux packages.

The release inputs are intentionally pinned. Updating a third-party binary must
be an explicit source change that updates both the version and expected digest;
normal release jobs never trust a mutable `latest` URL or an unchecked archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

YTDLP_VERSION = "2026.08.19"
YTDLP_BASE_URL = f"https://github.com/yt-dlp/yt-dlp/releases/download/{YTDLP_VERSION}"
FFMPEG_VERSION = "v9.0.1"
FFMPEG_BASE_URL = f"https://github.com/binmgr/ffmpeg/releases/download/{FFMPEG_VERSION}"
USER_AGENT = "GalaxyLocalEngineReleaseBuilder/1.0"
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class AssetSpec:
    name: str
    url: str
    sha256: str


@dataclass(frozen=True)
class BundlePlan:
    os_name: str
    architecture: str
    yt_dlp: AssetSpec
    ffmpeg: AssetSpec


_YTDLP_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("linux", "amd64"): (
        "yt-dlp_linux",
        "58162f9bfdc27458ea47bfcb311cf47028f17d8154a8bf7d689861d46399230a",
    ),
    ("linux", "arm64"): (
        "yt-dlp_linux_aarch64",
        "b16e4dab368a816cd05d477d698a605a6ae87ccee1c8ffd38fa21d7254141fcc",
    ),
    ("darwin", "amd64"): (
        "yt-dlp_macos",
        "0f192b7ec147ab6288885d6351d9ab67367640029b4377576ef46dd79cf7b202",
    ),
    ("darwin", "arm64"): (
        "yt-dlp_macos",
        "0f192b7ec147ab6288885d6351d9ab67367640029b4377576ef46dd79cf7b202",
    ),
}

_FFMPEG_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("linux", "amd64"): (
        "ffmpeg-linux-amd64.tar.gz",
        "981493cde0bd9303129e6a7bef1a22bb65089bd8e04fd96622878a865761d706",
    ),
    ("linux", "arm64"): (
        "ffmpeg-linux-arm64.tar.gz",
        "4fdc66bd708aef86f4e431f52f72bb26ce49eb9e12d34ff92c069e04dabc2df5",
    ),
    ("darwin", "amd64"): (
        "ffmpeg-darwin-amd64.tar.gz",
        "a58d579615e8bfd54cb063e208d9c6c33b6ed81a8030885347167ff86ba43148",
    ),
    ("darwin", "arm64"): (
        "ffmpeg-darwin-arm64.tar.gz",
        "5e28fe92746c35be5a5c0c7bffe8397c36e9bf75867eb28992c69fcfb69be155",
    ),
}


def normalize_os(value: str | None = None) -> str:
    raw = str(value or platform.system()).strip().lower()
    aliases = {"macos": "darwin", "mac": "darwin", "osx": "darwin"}
    result = aliases.get(raw, raw)
    if result not in {"linux", "darwin"}:
        raise ValueError(f"unsupported portable bundle OS: {raw or '<empty>'}")
    return result


def normalize_architecture(value: str | None = None) -> str:
    raw = str(value or platform.machine()).strip().lower()
    aliases = {
        "x86_64": "amd64",
        "x64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    result = aliases.get(raw)
    if result is None:
        raise ValueError(f"unsupported portable bundle architecture: {raw or '<empty>'}")
    return result


def bundle_plan(os_name: str | None = None, architecture: str | None = None) -> BundlePlan:
    system = normalize_os(os_name)
    machine = normalize_architecture(architecture)
    key = (system, machine)
    try:
        yt_name, yt_hash = _YTDLP_ASSETS[key]
        ff_name, ff_hash = _FFMPEG_ASSETS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported portable bundle target: {system}/{machine}") from exc
    return BundlePlan(
        os_name=system,
        architecture=machine,
        yt_dlp=AssetSpec(yt_name, f"{YTDLP_BASE_URL}/{yt_name}", yt_hash),
        ffmpeg=AssetSpec(ff_name, f"{FFMPEG_BASE_URL}/{ff_name}", ff_hash),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(spec: AssetSpec, target: Path, *, timeout_seconds: float = 120.0) -> None:
    request = urllib.request.Request(spec.url, headers={"User-Agent": USER_AGENT})
    written = 0
    digest = hashlib.sha256()
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=max(10.0, float(timeout_seconds))) as response:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_DOWNLOAD_BYTES:
                raise RuntimeError(f"download is unexpectedly large: {declared} bytes")
            with temporary.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError("download exceeded the release safety limit")
                    digest.update(chunk)
                    output.write(chunk)
        actual = digest.hexdigest()
        if actual.lower() != spec.sha256.lower():
            raise RuntimeError(
                f"SHA-256 mismatch for {spec.name}: expected {spec.sha256}, got {actual}"
            )
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _safe_extract_ffmpeg(archive: Path, destination: Path) -> tuple[Path, Path]:
    extract_root = destination / "_extract"
    shutil.rmtree(extract_root, ignore_errors=True)
    extract_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if not members:
            raise RuntimeError("FFmpeg archive is empty")
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"unsafe FFmpeg archive member: {member.name}")
            if member.issym() or member.islnk():
                raise RuntimeError(f"symlinks are not accepted in FFmpeg archive: {member.name}")
        bundle.extractall(extract_root, filter="data")

    def unique_binary(name: str) -> Path:
        candidates = [
            path
            for path in extract_root.rglob(name)
            if path.is_file() and not path.is_symlink()
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                f"FFmpeg archive must contain exactly one {name} binary; found {len(candidates)}"
            )
        return candidates[0]

    return unique_binary("ffmpeg"), unique_binary("ffprobe")


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _version_line(executable: Path, *args: str) -> str:
    completed = subprocess.run(
        [str(executable), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{executable.name} version probe failed with {completed.returncode}")
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"{executable.name} did not report a version")
    return lines[0][:300]


def prepare_bundle(package_dir: Path, *, os_name: str | None = None, architecture: str | None = None) -> dict[str, object]:
    plan = bundle_plan(os_name, architecture)
    package = package_dir.resolve()
    package.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = package / "ffmpeg" / "bin"
    ffmpeg_bin.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="galaxy-unix-bundle-") as temp_name:
        temp = Path(temp_name)
        yt_download = temp / plan.yt_dlp.name
        ff_download = temp / plan.ffmpeg.name
        _download(plan.yt_dlp, yt_download)
        _download(plan.ffmpeg, ff_download)

        yt_target = package / "yt-dlp"
        shutil.copy2(yt_download, yt_target)
        ffmpeg_source, ffprobe_source = _safe_extract_ffmpeg(ff_download, temp)
        ffmpeg_target = ffmpeg_bin / "ffmpeg"
        ffprobe_target = ffmpeg_bin / "ffprobe"
        shutil.copy2(ffmpeg_source, ffmpeg_target)
        shutil.copy2(ffprobe_source, ffprobe_target)

    for executable in (yt_target, ffmpeg_target, ffprobe_target):
        _make_executable(executable)

    versions = {
        "ytDlp": _version_line(yt_target, "--version"),
        "ffmpeg": _version_line(ffmpeg_target, "-version"),
        "ffprobe": _version_line(ffprobe_target, "-version"),
    }
    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "target": {"os": plan.os_name, "architecture": plan.architecture},
        "sources": {
            "ytDlp": {**asdict(plan.yt_dlp), "release": YTDLP_VERSION},
            "ffmpeg": {**asdict(plan.ffmpeg), "release": FFMPEG_VERSION},
        },
        "installed": {
            "yt-dlp": {"sha256": sha256_file(yt_target), "version": versions["ytDlp"]},
            "ffmpeg": {"sha256": sha256_file(ffmpeg_target), "version": versions["ffmpeg"]},
            "ffprobe": {"sha256": sha256_file(ffprobe_target), "version": versions["ffprobe"]},
        },
    }
    (package / "BUNDLE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-dir", required=True)
    parser.add_argument("--os")
    parser.add_argument("--architecture")
    parser.add_argument("--print-plan", action="store_true")
    args = parser.parse_args()
    plan = bundle_plan(args.os, args.architecture)
    if args.print_plan:
        print(json.dumps(asdict(plan), indent=2))
        return 0
    manifest = prepare_bundle(
        Path(args.package_dir),
        os_name=args.os,
        architecture=args.architecture,
    )
    target = manifest["target"]
    print(f"Prepared verified Unix bundle for {target['os']}/{target['architecture']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
