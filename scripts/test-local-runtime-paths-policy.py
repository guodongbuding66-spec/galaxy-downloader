from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from runtime_paths_policy import (  # noqa: E402
    install_runtime_paths_policy,
    run_runtime_paths_policy_self_test,
)


class RuntimePathsPolicyTests(unittest.TestCase):
    def _engine(self, root: Path, bundled_ffmpeg: Path | None = None):
        class Window:
            def bridge_status(self) -> dict[str, Any]:
                return {"state": "ready"}

        class Engine:
            EngineWindow = Window

            @staticmethod
            def app_dir() -> Path:
                return root / "program"

            @staticmethod
            def default_download_dir() -> Path:
                target = root / "program" / "downloads"
                target.mkdir(parents=True, exist_ok=True)
                return target

            @staticmethod
            def ffmpeg_dir() -> Path | None:
                return bundled_ffmpeg

        return Engine

    def test_installed_mode_routes_mutable_roots_outside_program_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            engine = self._engine(root)
            with patch.dict(
                os.environ,
                {"GALAXY_PORTABLE": "0", "GALAXY_HOME": str(root / "user-data")},
                clear=False,
            ):
                install_runtime_paths_policy(engine)
                paths = engine.runtime_paths(refresh=True)
                self.assertEqual(paths.mode, "installed")
                self.assertEqual(engine.app_dir(), root / "program")
                self.assertEqual(engine.data_dir(), root / "user-data")
                self.assertEqual(engine.state_dir(), root / "user-data" / "state")
                self.assertEqual(engine.default_download_dir(), root / "user-data" / "downloads")
                self.assertEqual(engine.cache_dir(), root / "user-data" / "cache")
                self.assertEqual(engine.tools_dir(), root / "user-data" / "tools")
                self.assertTrue(engine.default_download_dir().is_dir())
                self.assertTrue(engine.state_dir().is_dir())

    def test_portable_mode_preserves_release_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            engine = self._engine(root)
            environment = dict(os.environ)
            environment.pop("GALAXY_PORTABLE", None)
            environment.pop("GALAXY_HOME", None)
            with patch.dict(os.environ, environment, clear=True):
                install_runtime_paths_policy(engine)
                paths = engine.runtime_paths(refresh=True)
                self.assertEqual(paths.mode, "portable")
                self.assertEqual(engine.default_download_dir(), root / "program" / "downloads")
                self.assertEqual(engine.state_dir(), root / "program" / "state")
                self.assertEqual(engine.tools_dir(), root / "program")

    def test_bundled_ffmpeg_keeps_priority_over_managed_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            bundled = root / "program" / "ffmpeg" / "bin"
            bundled.mkdir(parents=True)
            engine = self._engine(root, bundled)
            with patch.dict(
                os.environ,
                {"GALAXY_PORTABLE": "0", "GALAXY_HOME": str(root / "runtime")},
                clear=False,
            ):
                install_runtime_paths_policy(engine)
                engine.runtime_paths(refresh=True)
                managed = root / "runtime" / "tools" / "ffmpeg" / "bin"
                managed.mkdir(parents=True)
                (managed / "ffmpeg").write_bytes(b"tool")
                self.assertEqual(engine.ffmpeg_dir(), bundled)

    def test_managed_ffmpeg_is_discovered_when_bundle_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            engine = self._engine(root)
            with patch.dict(
                os.environ,
                {"GALAXY_PORTABLE": "0", "GALAXY_HOME": str(root / "runtime")},
                clear=False,
            ):
                install_runtime_paths_policy(engine)
                engine.runtime_paths(refresh=True)
                managed = root / "runtime" / "tools" / "ffmpeg" / "bin"
                managed.mkdir(parents=True)
                binary = managed / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
                binary.write_bytes(b"tool")
                self.assertEqual(engine.ffmpeg_dir(), managed)

    def test_bridge_status_exposes_mode_not_private_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            engine = self._engine(root)
            with patch.dict(
                os.environ,
                {"GALAXY_PORTABLE": "0", "GALAXY_HOME": str(root / "secret-runtime")},
                clear=False,
            ):
                install_runtime_paths_policy(engine)
                engine.runtime_paths(refresh=True)
                payload = engine.EngineWindow().bridge_status()
                self.assertEqual(payload["runtimeMode"], "installed")
                self.assertIn(payload["runtimePlatform"], {"windows", "macos", "linux", "other"})
                rendered = repr(payload)
                self.assertNotIn(str(root / "secret-runtime"), rendered)

    def test_install_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = self._engine(Path(directory).resolve())
            first = install_runtime_paths_policy(engine)
            bridge_method = engine.EngineWindow.bridge_status
            second = install_runtime_paths_policy(engine)
            self.assertIs(first, second)
            self.assertIs(engine.EngineWindow.bridge_status, bridge_method)

    def test_embedded_self_test(self) -> None:
        run_runtime_paths_policy_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
