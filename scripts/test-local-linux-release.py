from __future__ import annotations

import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import linux_release  # noqa: E402


class LinuxReleaseContractTest(unittest.TestCase):
    def _payload(self, root: Path) -> Path:
        package = root / "package"
        files = {
            "GalaxyLocalEngine": b"engine",
            "yt-dlp": b"yt-dlp",
            "ffmpeg/bin/ffmpeg": b"ffmpeg",
            "ffmpeg/bin/ffprobe": b"ffprobe",
            "VERSION": (linux_release.read_version() + "\n").encode(),
            "BUNDLE_MANIFEST.json": b"{}\n",
            "README.md": b"readme\n",
        }
        for relative, content in files.items():
            path = package / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(0o755 if relative in {
                "GalaxyLocalEngine",
                "yt-dlp",
                "ffmpeg/bin/ffmpeg",
                "ffmpeg/bin/ffprobe",
            } else 0o644)
        return package

    def test_tool_plans_are_fixed_asset_ids_with_sha256(self) -> None:
        for arch in ("amd64", "arm64"):
            plan = linux_release.tool_plan(arch)
            self.assertIn(plan.appimage_arch, {"x86_64", "aarch64"})
            for spec in (plan.appimagetool, plan.runtime, plan.nfpm):
                self.assertGreater(spec.asset_id, 0)
                self.assertRegex(spec.sha256, r"^[0-9a-f]{64}$")
                self.assertIn(f"/releases/assets/{spec.asset_id}", spec.url)
                self.assertNotIn("/latest", spec.url)
                self.assertNotIn("continuous", spec.url)

    def test_architecture_aliases_and_artifact_names(self) -> None:
        self.assertEqual(linux_release.normalize_architecture("x86_64"), "amd64")
        self.assertEqual(linux_release.normalize_architecture("aarch64"), "arm64")
        with self.assertRaises(linux_release.LinuxReleaseError):
            linux_release.normalize_architecture("i386")
        self.assertEqual(
            linux_release.artifact_paths(Path("dist"), "amd64")["appimage"].name,
            "GalaxyLocalEngine-Linux-x64.AppImage",
        )
        self.assertEqual(
            linux_release.artifact_paths(Path("dist"), "arm64")["rpm"].name,
            "GalaxyLocalEngine-Linux-arm64.rpm",
        )

    def test_desktop_entry_registers_protocol_and_real_launcher(self) -> None:
        entry = linux_release.desktop_entry(str(linux_release.LAUNCHER_PATH))
        self.assertIn("Type=Application", entry)
        self.assertIn("Exec=/usr/bin/galaxy-local-engine %u", entry)
        self.assertIn("Icon=galaxy-local-engine", entry)
        self.assertIn("MimeType=x-scheme-handler/galaxy-downloader;", entry)
        self.assertIn("Terminal=false", entry)

    def test_packaged_launchers_default_to_installed_mode(self) -> None:
        for script in (linux_release.launcher_script(), linux_release.apprun_script()):
            self.assertIn('if [ -z "${GALAXY_PORTABLE:-}" ]; then', script)
            self.assertIn("GALAXY_PORTABLE=0", script)
            self.assertIn("export GALAXY_PORTABLE", script)
            # The guard preserves an explicit GALAXY_PORTABLE=1/portable override.
            self.assertNotIn("export GALAXY_PORTABLE=0", script)

    def test_appdir_contains_forwarding_entrypoint_and_protocol_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            package = self._payload(tmp)
            appdir = linux_release.prepare_appdir(package, tmp / "AppDir")
            self.assertTrue((appdir / "AppRun").is_file())
            self.assertTrue(os.access(appdir / "AppRun", os.X_OK))
            self.assertIn("GALAXY_PORTABLE=0", (appdir / "AppRun").read_text())
            self.assertTrue((appdir / "GalaxyLocalEngine").is_symlink())
            self.assertEqual(
                os.readlink(appdir / "GalaxyLocalEngine"),
                "opt/galaxy-local-engine/GalaxyLocalEngine",
            )
            self.assertEqual(
                (appdir / "opt/galaxy-local-engine/VERSION").read_text().strip(),
                linux_release.read_version(),
            )
            desktop = (appdir / "galaxy-local-engine.desktop").read_text()
            self.assertIn("Exec=GalaxyLocalEngine %u", desktop)
            self.assertIn("x-scheme-handler/galaxy-downloader", desktop)

    def test_nfpm_config_maps_payload_and_desktop_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            package = self._payload(tmp)
            config_path = linux_release.prepare_nfpm_staging(
                package,
                tmp / "nfpm",
                "amd64",
            )
            config = json.loads(config_path.read_text())
            self.assertEqual(config["name"], "galaxy-local-engine")
            self.assertEqual(config["arch"], "amd64")
            self.assertEqual(config["version"], linux_release.read_version())
            destinations = {item["dst"]: item for item in config["contents"]}
            self.assertIn("/opt/galaxy-local-engine/GalaxyLocalEngine", destinations)
            self.assertIn("/usr/bin/galaxy-local-engine", destinations)
            self.assertIn(
                "/usr/share/applications/galaxy-local-engine.desktop",
                destinations,
            )
            self.assertIn(
                "/usr/share/icons/hicolor/scalable/apps/galaxy-local-engine.svg",
                destinations,
            )
            self.assertEqual(
                destinations["/usr/bin/galaxy-local-engine"]["file_info"]["mode"],
                0o755,
            )
            launcher_source = Path(destinations["/usr/bin/galaxy-local-engine"]["src"])
            self.assertIn("GALAXY_PORTABLE=0", launcher_source.read_text())
            desktop_source = Path(
                destinations["/usr/share/applications/galaxy-local-engine.desktop"]["src"]
            )
            self.assertIn(
                "MimeType=x-scheme-handler/galaxy-downloader;",
                desktop_source.read_text(),
            )

    def test_payload_rejects_symlinks(self) -> None:
        if os.name == "nt":
            self.skipTest("symlink contract is validated on Linux release runners")
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            package = self._payload(tmp)
            (package / "alias").symlink_to("VERSION")
            with self.assertRaisesRegex(linux_release.LinuxReleaseError, "symlinks"):
                linux_release.validate_payload(package)

    def test_nfpm_extractor_rejects_archive_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            archive = tmp / "nfpm.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                info = tarfile.TarInfo("nfpm-link")
                info.type = tarfile.SYMTYPE
                info.linkname = "/tmp/outside"
                bundle.addfile(info)
            with self.assertRaisesRegex(linux_release.LinuxReleaseError, "links"):
                linux_release._extract_nfpm(archive, tmp / "extract")

    def test_nfpm_extractor_accepts_one_regular_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            archive = tmp / "nfpm.tar.gz"
            body = b"fake nfpm"
            with tarfile.open(archive, "w:gz") as bundle:
                info = tarfile.TarInfo("nfpm")
                info.size = len(body)
                info.mode = 0o755
                bundle.addfile(info, io.BytesIO(body))
            binary = linux_release._extract_nfpm(archive, tmp / "extract")
            self.assertEqual(binary.read_bytes(), body)
            self.assertTrue(os.access(binary, os.X_OK))


if __name__ == "__main__":
    unittest.main()
