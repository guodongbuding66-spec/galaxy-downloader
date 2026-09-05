from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import macos_release  # noqa: E402


class MacOSReleaseContractTest(unittest.TestCase):
    def _app(self, root: Path, *, installed: bool = True) -> Path:
        app = root / macos_release.APP_BUNDLE_NAME
        contents = app / "Contents"
        runtime = contents / "MacOS"
        runtime.mkdir(parents=True)
        (contents / "Info.plist").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict></dict></plist>\n',
            encoding="utf-8",
        )
        executable = runtime / macos_release.APP_EXECUTABLE
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        if installed:
            (runtime / macos_release.INSTALLED_MARKER).write_text("1\n", encoding="utf-8")
        return app

    def test_architecture_aliases_and_artifact_names(self) -> None:
        self.assertEqual(macos_release.normalize_architecture("amd64"), "x64")
        self.assertEqual(macos_release.normalize_architecture("x86_64"), "x64")
        self.assertEqual(macos_release.normalize_architecture("aarch64"), "arm64")
        with self.assertRaises(macos_release.MacOSReleaseError):
            macos_release.normalize_architecture("i386")
        self.assertEqual(
            macos_release.artifact_path(Path("dist"), "amd64").name,
            "GalaxyLocalEngine-macOS-x64.dmg",
        )
        self.assertEqual(
            macos_release.artifact_path(Path("dist"), "arm64").name,
            "GalaxyLocalEngine-macOS-arm64.dmg",
        )

    def test_app_bundle_requires_installed_runtime_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            app = self._app(tmp, installed=False)
            with self.assertRaisesRegex(macos_release.MacOSReleaseError, "installed runtime marker"):
                macos_release.validate_app_bundle(app)
            (macos_release.app_runtime_dir(app) / macos_release.INSTALLED_MARKER).write_text(
                "1\n", encoding="utf-8"
            )
            self.assertEqual(macos_release.validate_app_bundle(app), app.resolve())

    def test_app_bundle_requires_executable_bit(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX executable-bit contract")
        with tempfile.TemporaryDirectory() as tmp_name:
            app = self._app(Path(tmp_name))
            executable = macos_release.app_executable(app)
            executable.chmod(0o644)
            with self.assertRaisesRegex(macos_release.MacOSReleaseError, "not executable"):
                macos_release.validate_app_bundle(app)

    @unittest.skipUnless(sys.platform == "darwin", "ditto staging contract is macOS-native")
    def test_staging_contains_app_and_applications_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            app = self._app(tmp / "source")
            staging = macos_release.prepare_dmg_staging(app, tmp / "staging")
            staged_app = staging / macos_release.APP_BUNDLE_NAME
            self.assertEqual(macos_release.validate_app_bundle(staged_app), staged_app.resolve())
            applications = staging / "Applications"
            self.assertTrue(applications.is_symlink())
            self.assertEqual(os.readlink(applications), "/Applications")


if __name__ == "__main__":
    unittest.main()
