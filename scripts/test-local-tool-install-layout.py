from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from tool_artifacts import ToolArtifact, ToolArtifactError, runtime_arch, runtime_platform  # noqa: E402
from tool_install_layout import (  # noqa: E402
    archive_root_from_asset_name,
    install_rooted_verified_artifact,
    run_tool_install_layout_self_test,
)


class ToolInstallLayoutTests(unittest.TestCase):
    def build_archive(self, root: Path, *, build_name: str = "ffmpeg-N-126313-g1ae4048218-win64-gpl"):
        binary = "ffmpeg.exe" if runtime_platform() == "windows" else "ffmpeg"
        archive_path = root / f"{build_name}.zip"
        with zipfile.ZipFile(archive_path, "w") as archive_file:
            archive_file.writestr(f"{build_name}/bin/{binary}", b"new")
            archive_file.writestr(f"{build_name}/LICENSE.txt", b"license")
        artifact = ToolArtifact(
            tool="ffmpeg",
            version="N-126313-g1ae4048218",
            platform=runtime_platform(),
            arch=runtime_arch(),
            url=f"https://downloads.example.com/{archive_path.name}",
            sha256=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            archive="zip",
        )
        return archive_path, artifact, build_name, binary

    def test_asset_name_derives_single_safe_content_root(self) -> None:
        self.assertEqual(
            archive_root_from_asset_name("ffmpeg-N-126313-g1ae4048218-win64-gpl.zip", "zip"),
            "ffmpeg-N-126313-g1ae4048218-win64-gpl",
        )
        self.assertEqual(
            archive_root_from_asset_name("ffmpeg-N-126313-g1ae4048218-linux64-gpl.tar.xz", "tar.xz"),
            "ffmpeg-N-126313-g1ae4048218-linux64-gpl",
        )
        for asset, archive in (("../bad.zip", "zip"), ("bad.zip", "tar.xz"), ("bad", "zip")):
            with self.subTest(asset=asset, archive=archive):
                with self.assertRaises(ToolArtifactError):
                    archive_root_from_asset_name(asset, archive)

    def test_rooted_install_promotes_payload_without_build_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path, artifact, build_name, binary = self.build_archive(root)
            target = root / "tools" / "ffmpeg"
            installed = install_rooted_verified_artifact(
                artifact,
                archive_path,
                target,
                content_root=build_name,
                required_files=(f"bin/{binary}", "LICENSE.txt"),
            )
            self.assertEqual((installed / "bin" / binary).read_bytes(), b"new")
            self.assertFalse((installed / build_name).exists())

    def test_validation_failure_preserves_previous_managed_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path, artifact, build_name, binary = self.build_archive(root)
            target = root / "tools" / "ffmpeg"
            (target / "bin").mkdir(parents=True)
            (target / "bin" / binary).write_bytes(b"old")
            with self.assertRaises(ToolArtifactError):
                install_rooted_verified_artifact(
                    artifact,
                    archive_path,
                    target,
                    content_root=build_name,
                    required_files=(f"bin/{binary}",),
                    validator=lambda _payload: False,
                )
            self.assertEqual((target / "bin" / binary).read_bytes(), b"old")

    def test_wrong_or_unsafe_content_root_never_replaces_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path, artifact, _build_name, binary = self.build_archive(root)
            target = root / "tools" / "ffmpeg"
            (target / "bin").mkdir(parents=True)
            (target / "bin" / binary).write_bytes(b"old")
            for content_root in ("missing-build", "../escape", "nested/root"):
                with self.subTest(content_root=content_root):
                    with self.assertRaises(ToolArtifactError):
                        install_rooted_verified_artifact(
                            artifact,
                            archive_path,
                            target,
                            content_root=content_root,
                            required_files=(f"bin/{binary}",),
                        )
                    self.assertEqual((target / "bin" / binary).read_bytes(), b"old")

    def test_embedded_self_test(self) -> None:
        run_tool_install_layout_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
