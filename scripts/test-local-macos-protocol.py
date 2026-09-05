from __future__ import annotations

import plistlib
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import generate_macos_icon  # noqa: E402
import macos_bundle  # noqa: E402
import macos_protocol  # noqa: E402


class FakeWindow:
    def __init__(self) -> None:
        self.presented = 0
        self.status: tuple[str, str] | None = None

    def deiconify(self) -> None:
        self.presented += 1

    def lift(self) -> None:
        self.presented += 1

    def focus_force(self) -> None:
        self.presented += 1

    def set_status(self, title: str, detail: str) -> None:
        self.status = (title, detail)

    def after(self, _delay: int, callback) -> None:
        callback()


class FakeEngine:
    PROTOCOL = "galaxy-downloader"

    def __init__(self) -> None:
        self.handoff = threading.Event()
        self.payload: dict[str, object] | None = None

    def parse_job(self, raw_url: str) -> dict[str, object]:
        if "url=" not in raw_url:
            raise ValueError("missing media URL")
        return {"raw": raw_url}

    def job_to_payload(self, job: dict[str, object]) -> dict[str, object]:
        return {"job": job}

    def post_job_to_running_engine(self, payload: dict[str, object]) -> bool:
        self.payload = payload
        self.handoff.set()
        return True


class MacOSProtocolContractTest(unittest.TestCase):
    def _app(self, root: Path) -> Path:
        app = root / macos_bundle.APP_BUNDLE_NAME
        contents = app / "Contents"
        runtime = contents / "MacOS"
        resources = contents / "Resources"
        runtime.mkdir(parents=True)
        resources.mkdir(parents=True)
        executable = runtime / macos_bundle.APP_EXECUTABLE
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        (resources / "GalaxyLocalEngine.icns").write_bytes(b"icns-test")
        with (contents / "Info.plist").open("wb") as handle:
            plistlib.dump(
                {
                    "CFBundleExecutable": macos_bundle.APP_EXECUTABLE,
                    "CFBundleIconFile": "GalaxyLocalEngine.icns",
                    "CFBundlePackageType": "APPL",
                },
                handle,
            )
        return app

    def test_bundle_metadata_registers_protocol_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            app = self._app(Path(tmp_name))
            payload = macos_bundle.configure_bundle(app)
            self.assertEqual(payload["CFBundleIdentifier"], macos_bundle.BUNDLE_IDENTIFIER)
            self.assertEqual(payload["CFBundleDisplayName"], macos_bundle.APP_DISPLAY_NAME)
            self.assertEqual(payload["CFBundleShortVersionString"], macos_bundle.read_version())
            self.assertEqual(
                payload["CFBundleURLTypes"][0]["CFBundleURLSchemes"],
                [macos_bundle.PROTOCOL_SCHEME],
            )
            macos_bundle.validate_bundle(app)

    def test_iconset_contains_native_retina_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            iconset = generate_macos_icon.generate_iconset(Path(tmp_name) / "GalaxyLocalEngine.iconset")
            self.assertEqual(set(path.name for path in iconset.iterdir()), set(generate_macos_icon.ICONSET_FILES))
            for filename, expected_size in generate_macos_icon.ICONSET_FILES.items():
                with Image.open(iconset / filename) as image:
                    self.assertEqual(image.size, (expected_size, expected_size))

    def test_open_protocol_only_presents_resident_window(self) -> None:
        engine = FakeEngine()
        window = FakeWindow()
        self.assertTrue(macos_protocol.handle_macos_url(engine, window, "galaxy-downloader://open"))
        self.assertGreaterEqual(window.presented, 1)
        self.assertFalse(engine.handoff.is_set())

    def test_download_protocol_reuses_resident_bridge(self) -> None:
        engine = FakeEngine()
        window = FakeWindow()
        url = "galaxy-downloader://download?url=https%3A%2F%2Fexample.com%2Fdemo.mp4"
        self.assertTrue(macos_protocol.handle_macos_url(engine, window, url))
        self.assertTrue(engine.handoff.wait(timeout=2.0))
        self.assertIsNotNone(engine.payload)

    def test_foreign_scheme_is_rejected(self) -> None:
        engine = FakeEngine()
        window = FakeWindow()
        self.assertFalse(macos_protocol.handle_macos_url(engine, window, "https://example.com"))
        self.assertEqual(window.status[0], "Protocol request rejected")
        self.assertFalse(engine.handoff.is_set())

    @unittest.skipUnless(sys.platform == "darwin", "TkAqua LaunchURL is macOS-native")
    def test_tkaqua_launchurl_command_is_live(self) -> None:
        import tkinter as tk

        engine = FakeEngine()
        root = tk.Tk()
        root.withdraw()
        status: list[tuple[str, str]] = []
        root.set_status = lambda title, detail: status.append((title, detail))  # type: ignore[attr-defined]
        try:
            self.assertTrue(macos_protocol.register_macos_url_handler(engine, root))
            command = root.tk.call("info", "commands", macos_protocol.MACOS_URL_COMMAND)
            self.assertTrue(command)
            root.tk.call(macos_protocol.MACOS_URL_COMMAND, "galaxy-downloader://open")
            root.update_idletasks()
            self.assertNotEqual(root.state(), "withdrawn")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
