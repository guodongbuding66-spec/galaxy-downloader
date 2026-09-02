from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from ffmpeg_manager import (
    FfmpegActionResult,
    bundled_ffmpeg_directory,
    existing_managed_ffmpeg,
    ffmpeg_version,
)
from tool_artifacts import ToolArtifactError, download_verified_artifact
from tool_install_layout import archive_root_from_asset_name, install_rooted_verified_artifact
from tool_sources import ResolvedToolSource, resolve_btbn_ffmpeg_source


def _binary_name(name: str, platform_name: str) -> str:
    return f"{name}.exe" if platform_name == "windows" else name


def _read_binary_version(executable: Path, *, expected_name: str, timeout: float = 8.0) -> str | None:
    if not executable.is_file() or executable.is_symlink():
        return None
    try:
        result = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout)),
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    line = next(iter((result.stdout or result.stderr or "").splitlines()), "").strip()
    if expected_name.lower() not in line.lower():
        return None
    return line[:200] if line else None


def validate_ffmpeg_payload(payload_root: Path, *, platform_name: str, timeout: float = 8.0) -> bool:
    """Execute both FFmpeg binaries before a downloaded payload can become active."""
    bin_dir = Path(payload_root) / "bin"
    ffmpeg = bin_dir / _binary_name("ffmpeg", platform_name)
    ffprobe = bin_dir / _binary_name("ffprobe", platform_name)
    return bool(
        _read_binary_version(ffmpeg, expected_name="ffmpeg", timeout=timeout)
        and _read_binary_version(ffprobe, expected_name="ffprobe", timeout=timeout)
    )


def _active_fallback(engine_module) -> tuple[str, str | None]:
    managed = existing_managed_ffmpeg(engine_module)
    if managed is not None:
        return "managed", ffmpeg_version(managed)
    bundled = bundled_ffmpeg_directory(engine_module)
    if bundled is not None:
        return "bundled", ffmpeg_version(bundled)
    return "unavailable", None


def install_managed_ffmpeg_online(
    engine_module,
    *,
    resolver: Callable[[], ResolvedToolSource] = resolve_btbn_ffmpeg_source,
    downloader: Callable[..., Path] = download_verified_artifact,
    rooted_installer: Callable[..., Path] = install_rooted_verified_artifact,
    payload_validator: Callable[..., bool] = validate_ffmpeg_payload,
    version_reader: Callable[[Path | None], str | None] = ffmpeg_version,
    workspace_root: Path | None = None,
) -> FfmpegActionResult:
    """Install/update Managed FFmpeg from the pinned trusted provider.

    Network access occurs only when this function is explicitly invoked. Provider
    metadata resolution, artifact SHA-256 verification, safe extraction, content
    root normalization, binary execution validation and version capture all have
    to succeed before runtime/tools/ffmpeg changes.
    """
    current_source, current_version = _active_fallback(engine_module)
    tools_root = Path(engine_module.tools_dir())
    tools_root.mkdir(parents=True, exist_ok=True)
    parent = Path(workspace_root) if workspace_root is not None else tools_root
    parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=".ffmpeg-online-", dir=str(parent)))

    try:
        resolved = resolver()
        artifact = resolved.artifact
        if artifact.tool != "ffmpeg":
            raise ToolArtifactError(f"trusted provider returned unexpected tool: {artifact.tool}")

        content_root = archive_root_from_asset_name(resolved.asset_name, artifact.archive)
        archive_path = workspace / resolved.asset_name
        downloader(artifact, archive_path)

        ffmpeg_name = _binary_name("ffmpeg", artifact.platform)
        ffprobe_name = _binary_name("ffprobe", artifact.platform)
        target = tools_root / "ffmpeg"
        validated_version: str | None = None

        def validate_before_promotion(payload: Path) -> bool:
            nonlocal validated_version
            if not payload_validator(payload, platform_name=artifact.platform):
                return False
            validated_version = version_reader(Path(payload) / "bin")
            return bool(validated_version)

        rooted_installer(
            artifact,
            archive_path,
            target,
            content_root=content_root,
            required_files=(f"bin/{ffmpeg_name}", f"bin/{ffprobe_name}"),
            validator=validate_before_promotion,
        )
        if not validated_version:
            raise AssertionError("validated FFmpeg version was not captured before promotion")

        invalidate = getattr(engine_module, "invalidate_tool_inventory", None)
        if callable(invalidate):
            invalidate()
        return FfmpegActionResult(
            True,
            True,
            validated_version,
            "managed",
            (
                f"Managed FFmpeg was installed from {resolved.provider_id} "
                f"({resolved.release_tag}, {artifact.version}) after SHA-256 and executable validation."
            ),
        )
    except Exception as exc:
        source, version = _active_fallback(engine_module)
        if source == "unavailable" and current_source != "unavailable":
            source, version = current_source, current_version
        return FfmpegActionResult(
            False,
            False,
            version,
            source,
            f"Could not install Managed FFmpeg from the trusted online source: {exc}",
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def run_ffmpeg_online_installer_self_test() -> None:
    import hashlib
    import zipfile

    from tool_artifacts import ToolArtifact, runtime_arch, runtime_platform
    from tool_sources import ResolvedToolSource

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        tools = root / "tools"
        platform_name = runtime_platform()
        arch = runtime_arch()
        binary_suffix = ".exe" if platform_name == "windows" else ""
        asset_name = "ffmpeg-N-126313-g1ae4048218-test-gpl.zip"
        build_root = asset_name.removesuffix(".zip")
        archive_path = root / asset_name
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(f"{build_root}/bin/ffmpeg{binary_suffix}", b"ffmpeg")
            archive.writestr(f"{build_root}/bin/ffprobe{binary_suffix}", b"ffprobe")
        payload = archive_path.read_bytes()
        artifact = ToolArtifact(
            tool="ffmpeg",
            version="N-126313-g1ae4048218",
            platform=platform_name,
            arch=arch,
            url=f"https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-test/{asset_name}",
            sha256=hashlib.sha256(payload).hexdigest(),
            archive="zip",
        )
        resolved = ResolvedToolSource(
            provider_id="btbn-ffmpeg-builds",
            artifact=artifact,
            release_tag="autobuild-test",
            published_at="2026-09-01T00:00:00Z",
            release_url="https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-test",
            asset_name=asset_name,
            provenance_url="https://ffmpeg.org/download.html",
        )

        class Engine:
            @staticmethod
            def tools_dir() -> Path:
                return tools

        def fake_download(_artifact, destination: Path) -> Path:
            target = Path(destination)
            target.write_bytes(payload)
            return target

        result = install_managed_ffmpeg_online(
            Engine,
            resolver=lambda: resolved,
            downloader=fake_download,
            payload_validator=lambda payload_root, **_kwargs: (payload_root / "bin" / f"ffmpeg{binary_suffix}").is_file(),
            version_reader=lambda _directory: "ffmpeg version test-online",
            workspace_root=root / "workspace",
        )
        assert result.ok is True
        assert result.source == "managed"
        assert (tools / "ffmpeg" / "bin" / f"ffmpeg{binary_suffix}").is_file()
        assert not any((root / "workspace").glob(".ffmpeg-online-*"))
