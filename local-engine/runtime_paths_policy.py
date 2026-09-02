from __future__ import annotations

from pathlib import Path
from typing import Any

from platform_paths import PlatformPaths, resolve_platform_paths


def _runtime_paths(engine_module, *, refresh: bool = False) -> PlatformPaths:
    if not refresh:
        cached = getattr(engine_module, "_galaxy_platform_paths", None)
        if isinstance(cached, PlatformPaths):
            return cached
    paths = resolve_platform_paths(program_dir=engine_module.app_dir())
    engine_module._galaxy_platform_paths = paths
    return paths


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _managed_ffmpeg_directory(paths: PlatformPaths) -> Path | None:
    candidates = (
        paths.tools_dir / "ffmpeg" / "bin",
        paths.tools_dir / "bin",
        paths.tools_dir,
    )
    for candidate in candidates:
        if (candidate / "ffmpeg.exe").is_file() or (candidate / "ffmpeg").is_file():
            return candidate
    return None


def install_runtime_paths_policy(engine_module):
    """Expose cross-platform runtime roots while preserving the portable default.

    `app_dir()` intentionally remains the immutable program/bundle directory so
    packaged resources and existing bundled tools keep working. Mutable runtime
    storage is routed through the new state/download/cache/data/tool accessors.
    """
    if getattr(engine_module, "_galaxy_runtime_paths_policy_installed", False):
        return engine_module

    original_default_download_dir = engine_module.default_download_dir
    original_ffmpeg_dir = engine_module.ffmpeg_dir

    def runtime_paths(*, refresh: bool = False) -> PlatformPaths:
        return _runtime_paths(engine_module, refresh=refresh)

    def data_dir() -> Path:
        return _ensure(runtime_paths().data_dir)

    def state_dir() -> Path:
        return _ensure(runtime_paths().state_dir)

    def cache_dir() -> Path:
        return _ensure(runtime_paths().cache_dir)

    def tools_dir() -> Path:
        return runtime_paths().tools_dir

    def default_download_dir() -> Path:
        return _ensure(runtime_paths().downloads_dir)

    def bundled_ffmpeg_dir() -> Path | None:
        return original_ffmpeg_dir()

    def ffmpeg_dir() -> Path | None:
        # A managed copy only appears after an explicit Tool Manager action, so
        # it can safely take precedence without changing historical defaults.
        managed = _managed_ffmpeg_directory(runtime_paths())
        if managed is not None:
            return managed
        return original_ffmpeg_dir()

    engine_module.runtime_paths = runtime_paths
    engine_module.data_dir = data_dir
    engine_module.state_dir = state_dir
    engine_module.cache_dir = cache_dir
    engine_module.tools_dir = tools_dir
    engine_module.default_download_dir = default_download_dir
    engine_module.bundled_ffmpeg_dir = bundled_ffmpeg_dir
    engine_module.ffmpeg_dir = ffmpeg_dir

    window_cls = engine_module.EngineWindow
    original_bridge_status = window_cls.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        paths = runtime_paths()
        payload["runtimeMode"] = paths.mode
        payload["runtimePlatform"] = paths.platform
        return payload

    window_cls.bridge_status = bridge_status
    engine_module._galaxy_runtime_paths_policy_installed = True
    window_cls._galaxy_runtime_paths_policy_installed = True
    return engine_module


def run_runtime_paths_policy_self_test() -> None:
    import os
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()

        class FakeWindow:
            def bridge_status(self) -> dict[str, Any]:
                return {"state": "ready"}

        class FakeEngine:
            EngineWindow = FakeWindow

            @staticmethod
            def app_dir() -> Path:
                return root / "program"

            @staticmethod
            def default_download_dir() -> Path:
                return root / "program" / "downloads"

            @staticmethod
            def ffmpeg_dir() -> Path | None:
                return None

        with patch.dict(
            os.environ,
            {
                "GALAXY_PORTABLE": "0",
                "GALAXY_HOME": str(root / "runtime"),
            },
            clear=False,
        ):
            install_runtime_paths_policy(FakeEngine)
            paths = FakeEngine.runtime_paths(refresh=True)
            assert paths.mode == "installed"
            assert FakeEngine.data_dir() == root / "runtime"
            assert FakeEngine.state_dir() == root / "runtime" / "state"
            assert FakeEngine.default_download_dir() == root / "runtime" / "downloads"
            assert FakeEngine.cache_dir() == root / "runtime" / "cache"
            assert FakeEngine.tools_dir() == root / "runtime" / "tools"
            assert FakeEngine.bundled_ffmpeg_dir() is None
            managed_bin = FakeEngine.tools_dir() / "ffmpeg" / "bin"
            managed_bin.mkdir(parents=True, exist_ok=True)
            (managed_bin / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")).write_text("test", encoding="utf-8")
            assert FakeEngine.ffmpeg_dir() == managed_bin
            status = FakeWindow().bridge_status()
            assert status["runtimeMode"] == "installed"
            assert status["runtimePlatform"] in {"windows", "macos", "linux", "other"}

        # Default behavior remains portable and app-local when no explicit mode
        # is requested, matching every released Local Engine build so far.
        class PortableWindow:
            def bridge_status(self) -> dict[str, Any]:
                return {}

        class PortableEngine:
            EngineWindow = PortableWindow

            @staticmethod
            def app_dir() -> Path:
                return root / "portable"

            @staticmethod
            def default_download_dir() -> Path:
                return root / "portable" / "downloads"

            @staticmethod
            def ffmpeg_dir() -> Path | None:
                return None

        environment = dict(os.environ)
        environment.pop("GALAXY_PORTABLE", None)
        environment.pop("GALAXY_HOME", None)
        with patch.dict(os.environ, environment, clear=True):
            install_runtime_paths_policy(PortableEngine)
            portable = PortableEngine.runtime_paths(refresh=True)
            assert portable.mode == "portable"
            assert PortableEngine.default_download_dir() == root / "portable" / "downloads"
