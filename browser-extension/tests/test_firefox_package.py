from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


EXTENSION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXTENSION_ROOT))

import build_firefox  # noqa: E402


class FirefoxPackageTest(unittest.TestCase):
    def test_builds_minimal_firefox_xpi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "GalaxyMediaCapture-Firefox.xpi"
            built = build_firefox.build(target)
            self.assertEqual(built, target.resolve())
            self.assertTrue(target.is_file())

            with zipfile.ZipFile(target, "r") as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"manifest.json", *build_firefox.RUNTIME_FILES},
                )
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                self.assertEqual(manifest["manifest_version"], 3)
                self.assertEqual(manifest["background"], {"scripts": ["background.js"], "type": "module"})
                self.assertNotIn("service_worker", manifest["background"])

                gecko = manifest["browser_specific_settings"]["gecko"]
                self.assertEqual(gecko["id"], "galaxy-media-capture@galaxy-downloader")
                self.assertGreaterEqual(build_firefox._version_tuple(gecko["strict_min_version"]), (128, 0))
                self.assertEqual(gecko["data_collection_permissions"]["required"], ["none"])

                for name in build_firefox.RUNTIME_FILES:
                    source = archive.read(name).decode("utf-8")
                    self.assertNotIn("chrome.", source, name)

                content = archive.read("content.js").decode("utf-8")
                self.assertIn("browser.runtime.sendMessage", content)
                self.assertIn("chrome-extension", content)

    def test_build_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.xpi"
            second = Path(tmp) / "second.xpi"
            build_firefox.build(first)
            build_firefox.build(second)
            self.assertEqual(
                hashlib.sha256(first.read_bytes()).digest(),
                hashlib.sha256(second.read_bytes()).digest(),
            )

    def test_manifest_validation_rejects_shared_field_drift(self) -> None:
        chrome = build_firefox._load_json(build_firefox.CHROME_MANIFEST)
        firefox = build_firefox._load_json(build_firefox.FIREFOX_MANIFEST)
        firefox["version"] = "999.0.0"
        with self.assertRaisesRegex(build_firefox.FirefoxPackageError, "drifted"):
            build_firefox.validate_manifests(chrome, firefox)

    def test_manifest_validation_rejects_service_worker(self) -> None:
        chrome = build_firefox._load_json(build_firefox.CHROME_MANIFEST)
        firefox = build_firefox._load_json(build_firefox.FIREFOX_MANIFEST)
        firefox["background"]["service_worker"] = "background.js"
        with self.assertRaisesRegex(build_firefox.FirefoxPackageError, "must not declare"):
            build_firefox.validate_manifests(chrome, firefox)


if __name__ == "__main__":
    unittest.main()
