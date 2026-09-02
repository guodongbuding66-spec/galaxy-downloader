from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from platform_paths import (  # noqa: E402
    APP_DIR_NAME,
    LINUX_APP_DIR_NAME,
    PlatformPathError,
    normalize_platform,
    program_directory,
    resolve_platform_paths,
    run_platform_paths_self_test,
)


class PlatformPathsTests(unittest.TestCase):
    def test_platform_names_are_normalized(self) -> None:
        self.assertEqual(normalize_platform("win32"), "windows")
        self.assertEqual(normalize_platform("darwin"), "macos")
        self.assertEqual(normalize_platform("linux"), "linux")
        self.assertEqual(normalize_platform("freebsd"), "other")

    def test_program_directory_uses_executable_when_frozen(self) -> None:
        target = program_directory(frozen=True, executable=Path("/tmp/GalaxyLocalEngine.exe"))
        self.assertEqual(target.name, "tmp")
        source = program_directory(frozen=False, source_file=Path("/tmp/source/engine.py"))
        self.assertEqual(source, Path("/tmp/source").resolve())

    def test_default_mode_preserves_existing_portable_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = resolve_platform_paths(
                program_dir=root,
                platform="win32",
                environ={"USERPROFILE": str(root / "user")},
            )
            self.assertTrue(paths.portable)
            self.assertEqual(paths.data_dir, root)
            self.assertEqual(paths.state_dir, root / "state")
            self.assertEqual(paths.downloads_dir, root / "downloads")
            self.assertEqual(paths.tools_dir, root)

    def test_explicit_installed_windows_layout_uses_per_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = resolve_platform_paths(
                program_dir=root / "program",
                platform="windows",
                environ={
                    "GALAXY_PORTABLE": "0",
                    "LOCALAPPDATA": str(root / "local"),
                    "USERPROFILE": str(root / "user"),
                },
            )
            self.assertFalse(paths.portable)
            self.assertEqual(paths.data_dir, root / "local" / APP_DIR_NAME)
            self.assertEqual(paths.state_dir, root / "local" / APP_DIR_NAME / "state")
            self.assertEqual(paths.downloads_dir, root / "user" / "Downloads" / "Galaxy")
            self.assertEqual(paths.tools_dir, root / "local" / APP_DIR_NAME / "tools")

    def test_installed_macos_and_linux_layouts_follow_platform_conventions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            mac = resolve_platform_paths(
                program_dir=root / "program",
                platform="darwin",
                environ={"GALAXY_PORTABLE": "off", "HOME": str(root / "mac")},
            )
            self.assertEqual(mac.data_dir, root / "mac" / "Library" / "Application Support" / APP_DIR_NAME)
            self.assertEqual(mac.cache_dir, root / "mac" / "Library" / "Caches" / APP_DIR_NAME)

            linux = resolve_platform_paths(
                program_dir=root / "program",
                platform="linux",
                environ={
                    "GALAXY_PORTABLE": "installed",
                    "HOME": str(root / "linux"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_CACHE_HOME": str(root / "cache"),
                },
            )
            self.assertEqual(linux.data_dir, root / "data" / LINUX_APP_DIR_NAME)
            self.assertEqual(linux.cache_dir, root / "cache" / LINUX_APP_DIR_NAME)

    def test_galaxy_home_override_keeps_installed_runtime_self_contained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = resolve_platform_paths(
                program_dir=root / "program",
                platform="linux",
                environ={
                    "GALAXY_PORTABLE": "0",
                    "GALAXY_HOME": str(root / "custom-home"),
                    "HOME": str(root / "user"),
                },
            )
            self.assertEqual(paths.data_dir, root / "custom-home")
            self.assertEqual(paths.cache_dir, root / "custom-home" / "cache")
            self.assertEqual(paths.downloads_dir, root / "custom-home" / "downloads")

    def test_invalid_mode_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PlatformPathError):
                resolve_platform_paths(
                    program_dir=Path(directory),
                    environ={"GALAXY_PORTABLE": "maybe"},
                )

    def test_ensure_runtime_dirs_creates_only_runtime_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = resolve_platform_paths(
                program_dir=root / "program",
                platform="linux",
                environ={
                    "GALAXY_PORTABLE": "0",
                    "GALAXY_HOME": str(root / "data"),
                    "HOME": str(root / "user"),
                },
            ).ensure_runtime_dirs()
            self.assertTrue(paths.data_dir.is_dir())
            self.assertTrue(paths.state_dir.is_dir())
            self.assertTrue(paths.downloads_dir.is_dir())
            self.assertTrue(paths.cache_dir.is_dir())
            self.assertFalse(paths.tools_dir.exists())

    def test_embedded_self_test(self) -> None:
        run_platform_paths_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
