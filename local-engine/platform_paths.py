from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

APP_DIR_NAME = "GalaxyLocalEngine"
LINUX_APP_DIR_NAME = "galaxy-local-engine"
PORTABLE_MARKER = "portable.flag"
PORTABLE_ENV = "GALAXY_PORTABLE"
HOME_ENV = "GALAXY_HOME"

_TRUE_VALUES = {"1", "true", "yes", "on", "portable"}
_FALSE_VALUES = {"0", "false", "no", "off", "installed"}


class PlatformPathError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlatformPaths:
    platform: str
    portable: bool
    program_dir: Path
    data_dir: Path
    state_dir: Path
    downloads_dir: Path
    tools_dir: Path
    cache_dir: Path

    @property
    def mode(self) -> str:
        return "portable" if self.portable else "installed"

    def ensure_runtime_dirs(self) -> "PlatformPaths":
        for path in (self.data_dir, self.state_dir, self.downloads_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)
        return self


def normalize_platform(value: str | None = None) -> str:
    raw = (value or sys.platform).lower().strip()
    if raw.startswith("win"):
        return "windows"
    if raw == "darwin" or raw.startswith("mac"):
        return "macos"
    if raw.startswith("linux"):
        return "linux"
    return "other"


def program_directory(
    *,
    frozen: bool | None = None,
    executable: str | Path | None = None,
    source_file: str | Path | None = None,
) -> Path:
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    if is_frozen:
        target = Path(executable or sys.executable)
        return target.expanduser().resolve().parent
    target = Path(source_file or __file__)
    return target.expanduser().resolve().parent


def _parse_portable_env(value: str | None) -> bool | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise PlatformPathError(
        f"{PORTABLE_ENV} must be one of: 1/0, true/false, yes/no, on/off, portable/installed"
    )


def portable_mode(
    program_dir: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> bool:
    env = os.environ if environ is None else environ
    explicit = _parse_portable_env(env.get(PORTABLE_ENV))
    if explicit is not None:
        return explicit
    if (program_dir / PORTABLE_MARKER).is_file():
        return True
    # Preserve the established Local Engine behavior: extracted/release folders
    # keep their state and downloads beside the executable unless the caller
    # explicitly opts into installed per-user paths.
    return True


def _home_directory(environ: Mapping[str, str], home: Path | None) -> Path:
    if home is not None:
        return home.expanduser().resolve()
    override = environ.get("HOME") or environ.get("USERPROFILE")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home().expanduser().resolve()


def _installed_roots(
    platform: str,
    *,
    environ: Mapping[str, str],
    home: Path,
) -> tuple[Path, Path, Path]:
    explicit_home = environ.get(HOME_ENV)
    if explicit_home:
        root = Path(explicit_home).expanduser().resolve()
        return root, root / "cache", root / "downloads"

    if platform == "windows":
        data_base = Path(environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
        data = data_base / APP_DIR_NAME
        downloads = home / "Downloads" / "Galaxy"
        return data, data / "cache", downloads

    if platform == "macos":
        data = home / "Library" / "Application Support" / APP_DIR_NAME
        cache = home / "Library" / "Caches" / APP_DIR_NAME
        downloads = home / "Downloads" / "Galaxy"
        return data, cache, downloads

    data_base = Path(environ.get("XDG_DATA_HOME") or (home / ".local" / "share"))
    cache_base = Path(environ.get("XDG_CACHE_HOME") or (home / ".cache"))
    data = data_base / LINUX_APP_DIR_NAME
    cache = cache_base / LINUX_APP_DIR_NAME
    downloads = home / "Downloads" / "Galaxy"
    return data, cache, downloads


def resolve_platform_paths(
    *,
    program_dir: Path | None = None,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    frozen: bool | None = None,
    executable: str | Path | None = None,
    source_file: str | Path | None = None,
) -> PlatformPaths:
    env = dict(os.environ if environ is None else environ)
    runtime_platform = normalize_platform(platform)
    program = (
        program_dir.expanduser().resolve()
        if program_dir is not None
        else program_directory(frozen=frozen, executable=executable, source_file=source_file)
    )
    portable = portable_mode(program, environ=env)

    if portable:
        data = program
        state = program / "state"
        downloads = program / "downloads"
        tools = program
        cache = program / "cache"
    else:
        resolved_home = _home_directory(env, home)
        data, cache, downloads = _installed_roots(
            runtime_platform,
            environ=env,
            home=resolved_home,
        )
        state = data / "state"
        tools = data / "tools"

    return PlatformPaths(
        platform=runtime_platform,
        portable=portable,
        program_dir=program,
        data_dir=data,
        state_dir=state,
        downloads_dir=downloads,
        tools_dir=tools,
        cache_dir=cache,
    )


def run_platform_paths_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        portable = resolve_platform_paths(
            program_dir=root / "app",
            platform="win32",
            environ={"GALAXY_PORTABLE": "1", "USERPROFILE": str(root / "user")},
        )
        assert portable.mode == "portable"
        assert portable.program_dir == root / "app"
        assert portable.state_dir == root / "app" / "state"
        assert portable.downloads_dir == root / "app" / "downloads"
        assert portable.tools_dir == root / "app"

        installed_windows = resolve_platform_paths(
            program_dir=root / "app",
            platform="win32",
            environ={
                "GALAXY_PORTABLE": "0",
                "LOCALAPPDATA": str(root / "local"),
                "USERPROFILE": str(root / "user"),
            },
        )
        assert installed_windows.mode == "installed"
        assert installed_windows.data_dir == root / "local" / APP_DIR_NAME
        assert installed_windows.downloads_dir == root / "user" / "Downloads" / "Galaxy"

        installed_macos = resolve_platform_paths(
            program_dir=root / "app",
            platform="darwin",
            environ={"GALAXY_PORTABLE": "false", "HOME": str(root / "mac-user")},
        )
        assert installed_macos.data_dir == root / "mac-user" / "Library" / "Application Support" / APP_DIR_NAME

        installed_linux = resolve_platform_paths(
            program_dir=root / "app",
            platform="linux",
            environ={
                "GALAXY_PORTABLE": "installed",
                "HOME": str(root / "linux-user"),
                "XDG_DATA_HOME": str(root / "xdg-data"),
                "XDG_CACHE_HOME": str(root / "xdg-cache"),
            },
        )
        assert installed_linux.data_dir == root / "xdg-data" / LINUX_APP_DIR_NAME
        assert installed_linux.cache_dir == root / "xdg-cache" / LINUX_APP_DIR_NAME

        try:
            resolve_platform_paths(
                program_dir=root,
                environ={"GALAXY_PORTABLE": "maybe"},
            )
        except PlatformPathError:
            pass
        else:
            raise AssertionError("invalid GALAXY_PORTABLE value was accepted")
