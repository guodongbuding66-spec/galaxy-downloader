from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class FfmpegActionResult:
    ok: bool
    changed: bool
    version: str | None
    source: str
    message: str


def _binary_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def managed_ffmpeg_directory(engine_module) -> Path:
    return Path(engine_module.tools_dir()) / "ffmpeg" / "bin"


def existing_managed_ffmpeg(engine_module) -> Path | None:
    directory = managed_ffmpeg_directory(engine_module)
    ffmpeg = directory / _binary_name("ffmpeg")
    if ffmpeg.is_file() and not ffmpeg.is_symlink():
        return directory
    return None


def bundled_ffmpeg_directory(engine_module) -> Path | None:
    resolver = getattr(engine_module, "bundled_ffmpeg_dir", None)
    if not callable(resolver):
        return None
    directory = resolver()
    if directory is None:
        return None
    path = Path(directory)
    ffmpeg = path / _binary_name("ffmpeg")
    return path if ffmpeg.is_file() else None


def ffmpeg_version(directory: Path | None, *, timeout: float = 8.0) -> str | None:
    if directory is None:
        return None
    executable = Path(directory) / _binary_name("ffmpeg")
    if not executable.is_file():
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
    lines = (result.stdout or result.stderr or "").splitlines()
    return lines[0].strip()[:160] if lines else None


def _copy_binary(source: Path, target: Path) -> bool:
    if not source.is_file() or source.is_symlink():
        return False
    shutil.copy2(source, target)
    if os.name != "nt":
        target.chmod(target.stat().st_mode | 0o111)
    return True


def seed_managed_ffmpeg(
    engine_module,
    *,
    version_reader: Callable[[Path | None], str | None] = ffmpeg_version,
) -> FfmpegActionResult:
    """Create a user-owned FFmpeg toolset from the verified bundled baseline.

    No network access is performed here. The bundled release files are copied,
    never modified. A staging directory is validated before it replaces the
    managed directory so a failed bootstrap cannot leave a half-installed tool.
    """
    current = existing_managed_ffmpeg(engine_module)
    if current is not None:
        return FfmpegActionResult(
            True,
            False,
            version_reader(current),
            "managed",
            "Managed FFmpeg is already available.",
        )

    bundled = bundled_ffmpeg_directory(engine_module)
    if bundled is None:
        return FfmpegActionResult(
            False,
            False,
            None,
            "unavailable",
            "Bundled FFmpeg is not available to seed a managed copy.",
        )

    target = managed_ffmpeg_directory(engine_module)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".ffmpeg-staging-{uuid.uuid4().hex}"
    backup = parent / f".ffmpeg-backup-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)

    try:
        copied_ffmpeg = _copy_binary(bundled / _binary_name("ffmpeg"), staging / _binary_name("ffmpeg"))
        _copy_binary(bundled / _binary_name("ffprobe"), staging / _binary_name("ffprobe"))
        if not copied_ffmpeg:
            raise OSError("bundled ffmpeg executable is missing")

        version = version_reader(staging)
        if not version:
            raise OSError("managed FFmpeg validation failed")

        if target.exists():
            target.replace(backup)
        staging.replace(target)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not target.exists():
            try:
                backup.replace(target)
            except OSError:
                pass
        return FfmpegActionResult(
            False,
            False,
            ffmpeg_version(bundled),
            "bundled",
            f"Could not create managed FFmpeg: {exc}",
        )

    invalidate = getattr(engine_module, "invalidate_tool_inventory", None)
    if callable(invalidate):
        invalidate()
    return FfmpegActionResult(
        True,
        True,
        version_reader(target),
        "managed",
        "Managed FFmpeg was created from the verified bundled toolset.",
    )


def reset_managed_ffmpeg(engine_module) -> FfmpegActionResult:
    target = existing_managed_ffmpeg(engine_module)
    if target is None:
        bundled = bundled_ffmpeg_directory(engine_module)
        return FfmpegActionResult(
            True,
            False,
            ffmpeg_version(bundled),
            "bundled" if bundled is not None else "unavailable",
            "Galaxy is already using the bundled FFmpeg fallback.",
        )
    try:
        shutil.rmtree(target.parent)
    except OSError as exc:
        return FfmpegActionResult(
            False,
            False,
            ffmpeg_version(target),
            "managed",
            f"Could not remove managed FFmpeg: {exc}",
        )

    invalidate = getattr(engine_module, "invalidate_tool_inventory", None)
    if callable(invalidate):
        invalidate()
    bundled = bundled_ffmpeg_directory(engine_module)
    return FfmpegActionResult(
        True,
        True,
        ffmpeg_version(bundled),
        "bundled" if bundled is not None else "unavailable",
        "Managed FFmpeg was removed; Galaxy will use the bundled fallback.",
    )


def run_ffmpeg_manager_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        program = root / "program"
        bundled = program / "ffmpeg"
        tools = root / "runtime" / "tools"
        bundled.mkdir(parents=True)
        (bundled / _binary_name("ffmpeg")).write_text("ffmpeg", encoding="utf-8")
        (bundled / _binary_name("ffprobe")).write_text("ffprobe", encoding="utf-8")

        class FakeEngine:
            @staticmethod
            def tools_dir() -> Path:
                return tools

            @staticmethod
            def bundled_ffmpeg_dir() -> Path:
                return bundled

        fake_version = lambda _directory: "ffmpeg version test"
        seeded = seed_managed_ffmpeg(FakeEngine, version_reader=fake_version)
        assert seeded.ok is True
        assert seeded.changed is True
        assert seeded.source == "managed"
        managed = existing_managed_ffmpeg(FakeEngine)
        assert managed is not None
        assert (managed / _binary_name("ffmpeg")).read_text(encoding="utf-8") == "ffmpeg"
        assert (managed / _binary_name("ffprobe")).read_text(encoding="utf-8") == "ffprobe"

        again = seed_managed_ffmpeg(FakeEngine, version_reader=fake_version)
        assert again.ok is True
        assert again.changed is False

        reset = reset_managed_ffmpeg(FakeEngine)
        assert reset.ok is True
        assert reset.changed is True
        assert existing_managed_ffmpeg(FakeEngine) is None
