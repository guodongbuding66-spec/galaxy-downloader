from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import external_ytdlp
from managed_tool_registry import (
    DEFAULT_MANAGED_TOOL_SPECS,
    ManagedToolObservation,
    evaluate_tool_health,
    registry_summary,
)

TOOL_STATUS_TTL_SECONDS = 30.0
YTDLP_UPDATE_CHANNELS = {"stable", "nightly"}
_TOOL_CACHE_LOCK = threading.RLock()
_TOOL_CACHE: dict[int, tuple[float, dict[str, Any]]] = {}


@dataclass(frozen=True)
class ToolUpdateResult:
    ok: bool
    changed: bool
    version: str | None
    source: str
    message: str


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def _managed_ytdlp_candidates(engine_module) -> tuple[Path, ...]:
    tools = Path(engine_module.tools_dir())
    if os.name == "nt":
        names = ("yt-dlp.exe",)
    else:
        names = ("yt-dlp", "yt-dlp.exe")
    directories = (
        tools / "yt-dlp",
        tools / "bin",
        tools,
    )
    return tuple(directory / name for directory in directories for name in names)


def managed_ytdlp_path(engine_module) -> Path:
    preferred = _managed_ytdlp_candidates(engine_module)[0]
    preferred.parent.mkdir(parents=True, exist_ok=True)
    return preferred


def existing_managed_ytdlp(engine_module) -> Path | None:
    for candidate in _managed_ytdlp_candidates(engine_module):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def bundled_ytdlp_path(
    engine_module,
    *,
    bundled_resolver: Callable[[Path], Path | None] = external_ytdlp.external_ytdlp_path,
) -> Path | None:
    candidate = bundled_resolver(Path(engine_module.app_dir()))
    if candidate is None:
        return None
    path = Path(candidate)
    return path if path.is_file() else None


def resolve_ytdlp(
    engine_module,
    *,
    bundled_resolver: Callable[[Path], Path | None] = external_ytdlp.external_ytdlp_path,
) -> tuple[Path | None, str]:
    """Resolve yt-dlp without changing the historical default unexpectedly.

    A managed executable only exists after an explicit user/tool-management
    action, so it can safely take precedence once present. Otherwise the exact
    bundled executable used by all previous Galaxy releases remains first-class.
    """
    managed = existing_managed_ytdlp(engine_module)
    if managed is not None:
        return managed, "managed"
    bundled = bundled_ytdlp_path(engine_module, bundled_resolver=bundled_resolver)
    if bundled is not None:
        return bundled, "bundled"
    return None, "unavailable"


def _ffmpeg_info(engine_module) -> tuple[Path | None, str]:
    directory = engine_module.ffmpeg_dir()
    if directory is None:
        return None, "unavailable"
    path = Path(directory)
    source = "managed" if _is_relative_to(path, Path(engine_module.tools_dir())) else "bundled"
    return path, source


def _ffmpeg_version(directory: Path | None) -> str | None:
    if directory is None:
        return None
    executable_names = ("ffmpeg.exe", "ffmpeg") if os.name == "nt" else ("ffmpeg", "ffmpeg.exe")
    executable = next((directory / name for name in executable_names if (directory / name).is_file()), None)
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception:
        return None
    line = (result.stdout or result.stderr or "").splitlines()
    return line[0].strip()[:160] if line else None


def invalidate_tool_inventory(engine_module) -> None:
    with _TOOL_CACHE_LOCK:
        _TOOL_CACHE.pop(id(engine_module), None)


def _managed_registry_payload(
    *,
    executable: Path | None,
    ytdlp_source: str,
    ytdlp_version: str | None,
    managed_ytdlp: Path | None,
    ffmpeg_directory: Path | None,
    ffmpeg_source: str,
    ffmpeg_version: str | None,
) -> dict[str, object]:
    specs = {item.tool: item for item in DEFAULT_MANAGED_TOOL_SPECS}
    ytdlp_root = managed_ytdlp.parent if managed_ytdlp is not None else None
    ffmpeg_root = ffmpeg_directory.parent if ffmpeg_source == "managed" and ffmpeg_directory is not None else None
    statuses = (
        evaluate_tool_health(
            specs["yt-dlp"],
            ManagedToolObservation(
                ready=executable is not None,
                source=ytdlp_source,
                version=ytdlp_version,
                managed_root=ytdlp_root,
            ),
        ),
        evaluate_tool_health(
            specs["ffmpeg"],
            ManagedToolObservation(
                ready=ffmpeg_directory is not None,
                source=ffmpeg_source,
                version=ffmpeg_version,
                managed_root=ffmpeg_root,
            ),
        ),
    )
    return registry_summary(statuses)


def tool_inventory(engine_module, *, refresh: bool = False) -> dict[str, Any]:
    key = id(engine_module)
    now = time.monotonic()
    with _TOOL_CACHE_LOCK:
        cached = _TOOL_CACHE.get(key)
        if not refresh and cached is not None and now - cached[0] < TOOL_STATUS_TTL_SECONDS:
            return dict(cached[1])

    executable, ytdlp_source = resolve_ytdlp(engine_module)
    ffmpeg_directory, ffmpeg_source = _ffmpeg_info(engine_module)
    managed = existing_managed_ytdlp(engine_module)
    ytdlp_version = external_ytdlp.external_version(executable) if executable is not None else None
    ffmpeg_version = _ffmpeg_version(ffmpeg_directory)
    payload = {
        "ytDlpReady": executable is not None,
        "ytDlpSource": ytdlp_source,
        "ytDlpVersion": ytdlp_version,
        "managedYtDlpReady": managed is not None,
        "ffmpegReady": ffmpeg_directory is not None,
        "ffmpegSource": ffmpeg_source,
        "ffmpegVersion": ffmpeg_version,
    }
    payload.update(
        _managed_registry_payload(
            executable=executable,
            ytdlp_source=ytdlp_source,
            ytdlp_version=ytdlp_version,
            managed_ytdlp=managed,
            ffmpeg_directory=ffmpeg_directory,
            ffmpeg_source=ffmpeg_source,
            ffmpeg_version=ffmpeg_version,
        )
    )
    with _TOOL_CACHE_LOCK:
        _TOOL_CACHE[key] = (now, dict(payload))
    return payload


def seed_managed_ytdlp(engine_module) -> ToolUpdateResult:
    """Create an updatable user-owned yt-dlp copy from the verified bundle."""
    current = existing_managed_ytdlp(engine_module)
    if current is not None:
        version = external_ytdlp.external_version(current)
        return ToolUpdateResult(True, False, version, "managed", "Managed yt-dlp is already available.")

    bundled = bundled_ytdlp_path(engine_module)
    if bundled is None:
        return ToolUpdateResult(False, False, None, "unavailable", "Bundled yt-dlp is not available to seed a managed copy.")

    target = managed_ytdlp_path(engine_module)
    temporary = target.with_name(target.name + ".tmp")
    try:
        shutil.copy2(bundled, temporary)
        if os.name != "nt":
            temporary.chmod(temporary.stat().st_mode | 0o111)
        temporary.replace(target)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        return ToolUpdateResult(False, False, None, "bundled", f"Could not create managed yt-dlp: {exc}")

    invalidate_tool_inventory(engine_module)
    return ToolUpdateResult(
        True,
        True,
        external_ytdlp.external_version(target),
        "managed",
        "Managed yt-dlp was created from the verified bundled executable.",
    )


def update_managed_ytdlp(engine_module, *, channel: str = "stable", timeout: float = 75.0) -> ToolUpdateResult:
    """Update only the user-owned yt-dlp copy, never the bundled release file.

    This function performs network access only when explicitly called by the UI
    or another user action. Normal startup and downloads remain offline-safe.
    """
    selected = str(channel or "stable").strip().lower()
    if selected not in YTDLP_UPDATE_CHANNELS:
        return ToolUpdateResult(False, False, None, "managed", f"Unsupported yt-dlp update channel: {selected}")

    seeded = seed_managed_ytdlp(engine_module)
    if not seeded.ok:
        return seeded
    executable = existing_managed_ytdlp(engine_module)
    if executable is None:
        return ToolUpdateResult(False, False, None, "unavailable", "Managed yt-dlp could not be resolved after setup.")

    before = external_ytdlp.external_version(executable)
    try:
        result = subprocess.run(
            [str(executable), "--update-to", selected],
            capture_output=True,
            text=True,
            timeout=max(5.0, float(timeout)),
            check=False,
        )
    except Exception as exc:
        invalidate_tool_inventory(engine_module)
        return ToolUpdateResult(False, False, before, "managed", f"yt-dlp update failed: {exc}")

    after = external_ytdlp.external_version(executable)
    invalidate_tool_inventory(engine_module)
    detail = "\n".join(line.strip() for line in (result.stdout or result.stderr or "").splitlines() if line.strip())
    if result.returncode != 0:
        return ToolUpdateResult(
            False,
            False,
            after or before,
            "managed",
            (detail or f"yt-dlp updater exited with code {result.returncode}")[:600],
        )
    changed = bool(after and before and after != before) or seeded.changed
    return ToolUpdateResult(
        True,
        changed,
        after or before,
        "managed",
        (detail or "Managed yt-dlp is up to date.")[:600],
    )


def reset_managed_ytdlp(engine_module) -> ToolUpdateResult:
    candidate = existing_managed_ytdlp(engine_module)
    if candidate is None:
        executable, source = resolve_ytdlp(engine_module)
        version = external_ytdlp.external_version(executable) if executable else None
        return ToolUpdateResult(True, False, version, source, "Galaxy is already using the bundled yt-dlp fallback.")
    try:
        candidate.unlink()
    except OSError as exc:
        return ToolUpdateResult(False, False, external_ytdlp.external_version(candidate), "managed", f"Could not remove managed yt-dlp: {exc}")
    invalidate_tool_inventory(engine_module)
    executable, source = resolve_ytdlp(engine_module)
    version = external_ytdlp.external_version(executable) if executable else None
    return ToolUpdateResult(True, True, version, source, "Managed yt-dlp was removed; Galaxy will use the bundled fallback.")


def install_tool_manager(engine_module):
    """Make managed tools discoverable without weakening portable defaults."""
    window_cls = engine_module.EngineWindow
    if getattr(engine_module, "_galaxy_tool_manager_installed", False):
        return engine_module

    bundled_resolver = engine_module.external_ytdlp_path

    def ytdlp_executable(_app_dir: Path | None = None) -> Path | None:
        executable, _source = resolve_ytdlp(engine_module, bundled_resolver=bundled_resolver)
        return executable

    engine_module.external_ytdlp_path = ytdlp_executable
    engine_module.tool_inventory = lambda refresh=False: tool_inventory(engine_module, refresh=bool(refresh))
    engine_module.update_managed_ytdlp = lambda channel="stable": update_managed_ytdlp(engine_module, channel=channel)
    engine_module.reset_managed_ytdlp = lambda: reset_managed_ytdlp(engine_module)

    original_bridge_status = window_cls.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        payload.update(tool_inventory(engine_module))
        payload["toolManagerReady"] = True
        return payload

    window_cls.bridge_status = bridge_status
    engine_module._galaxy_tool_manager_installed = True
    window_cls._galaxy_tool_manager_installed = True
    return engine_module


def run_tool_manager_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        program = root / "program"
        tools = root / "runtime" / "tools"
        program.mkdir(parents=True)
        bundled = program / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
        bundled.write_text("bundled", encoding="utf-8")
        if os.name != "nt":
            bundled.chmod(0o755)

        class FakeWindow:
            def bridge_status(self) -> dict[str, Any]:
                return {"state": "ready"}

        class FakeEngine:
            EngineWindow = FakeWindow
            external_ytdlp_path = staticmethod(lambda _path: bundled)

            @staticmethod
            def app_dir() -> Path:
                return program

            @staticmethod
            def tools_dir() -> Path:
                return tools

            @staticmethod
            def ffmpeg_dir() -> Path | None:
                return None

        executable, source = resolve_ytdlp(FakeEngine, bundled_resolver=FakeEngine.external_ytdlp_path)
        assert executable == bundled
        assert source == "bundled"

        with patch.object(external_ytdlp, "external_version", return_value="2026.08.19"):
            seeded = seed_managed_ytdlp(FakeEngine)
            assert seeded.ok is True
            assert seeded.changed is True
            managed = existing_managed_ytdlp(FakeEngine)
            assert managed is not None and managed.read_text(encoding="utf-8") == "bundled"
            executable, source = resolve_ytdlp(FakeEngine, bundled_resolver=FakeEngine.external_ytdlp_path)
            assert executable == managed
            assert source == "managed"

            install_tool_manager(FakeEngine)
            status = FakeWindow().bridge_status()
            assert status["toolManagerReady"] is True
            assert status["ytDlpSource"] == "managed"
            assert status["ytDlpVersion"] == "2026.08.19"
            assert status["ffmpegSource"] == "unavailable"
            assert status["dependenciesReady"] is False
            assert status["dependencyWarningCount"] >= 1
            assert status["dependencyErrorCount"] == 1
            assert len(status["managedToolRegistry"]) == 2
            ytdlp_status = next(item for item in status["managedToolRegistry"] if item["tool"] == "yt-dlp")
            ffmpeg_status = next(item for item in status["managedToolRegistry"] if item["tool"] == "ffmpeg")
            assert ytdlp_status["state"] == "managed-untracked"
            assert ytdlp_status["ready"] is True
            assert ffmpeg_status["state"] == "missing"
            assert ffmpeg_status["ready"] is False
            assert all("path" not in " ".join(item.keys()).lower() for item in status["managedToolRegistry"])
            assert "path" not in " ".join(status.keys()).lower()

            reset = reset_managed_ytdlp(FakeEngine)
            assert reset.ok is True
            assert reset.changed is True
            assert existing_managed_ytdlp(FakeEngine) is None
