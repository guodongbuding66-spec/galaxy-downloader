from __future__ import annotations

import importlib.util
import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "local-engine" / "prepare-unix-bundle.py"
spec = importlib.util.spec_from_file_location("prepare_unix_bundle", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("could not load prepare-unix-bundle.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class UnixBundleTests(unittest.TestCase):
    def test_all_release_targets_are_pinned_and_arch_specific(self) -> None:
        targets = {
            ("linux", "x86_64"): "ffmpeg-linux-amd64.tar.gz",
            ("linux", "aarch64"): "ffmpeg-linux-arm64.tar.gz",
            ("darwin", "x86_64"): "ffmpeg-darwin-amd64.tar.gz",
            ("darwin", "arm64"): "ffmpeg-darwin-arm64.tar.gz",
        }
        for (os_name, machine), ffmpeg_name in targets.items():
            plan = module.bundle_plan(os_name, machine)
            self.assertEqual(plan.ffmpeg.name, ffmpeg_name)
            self.assertIn(module.FFMPEG_VERSION, plan.ffmpeg.url)
            self.assertIn(module.YTDLP_VERSION, plan.yt_dlp.url)
            self.assertNotIn("/latest/", plan.ffmpeg.url)
            self.assertNotIn("/latest/", plan.yt_dlp.url)
            self.assertRegex(plan.ffmpeg.sha256, r"^[0-9a-f]{64}$")
            self.assertRegex(plan.yt_dlp.sha256, r"^[0-9a-f]{64}$")

    def test_macos_uses_verified_official_ytdlp_binary(self) -> None:
        intel = module.bundle_plan("macos", "amd64")
        arm = module.bundle_plan("darwin", "arm64")
        self.assertEqual(intel.yt_dlp.name, "yt-dlp_macos")
        self.assertEqual(arm.yt_dlp.name, "yt-dlp_macos")
        self.assertEqual(intel.yt_dlp.sha256, arm.yt_dlp.sha256)

    def test_unsupported_targets_fail_closed(self) -> None:
        for os_name, arch in (("windows", "amd64"), ("linux", "i686"), ("freebsd", "amd64")):
            with self.assertRaises(ValueError):
                module.bundle_plan(os_name, arch)

    def test_archive_extraction_requires_exact_regular_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            archive = root / "tools.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                for name, payload in (("bundle/ffmpeg", b"ffmpeg"), ("bundle/ffprobe", b"ffprobe")):
                    info = tarfile.TarInfo(name)
                    info.mode = 0o755
                    info.size = len(payload)
                    bundle.addfile(info, io.BytesIO(payload))
            ffmpeg, ffprobe = module._safe_extract_ffmpeg(archive, root / "extract")
            self.assertEqual(ffmpeg.read_bytes(), b"ffmpeg")
            self.assertEqual(ffprobe.read_bytes(), b"ffprobe")

    def test_archive_traversal_and_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            traversal = root / "traversal.tar.gz"
            with tarfile.open(traversal, "w:gz") as bundle:
                info = tarfile.TarInfo("../ffmpeg")
                payload = b"bad"
                info.size = len(payload)
                bundle.addfile(info, io.BytesIO(payload))
            with self.assertRaises(RuntimeError):
                module._safe_extract_ffmpeg(traversal, root / "a")

            symlink = root / "symlink.tar.gz"
            with tarfile.open(symlink, "w:gz") as bundle:
                link = tarfile.TarInfo("ffmpeg")
                link.type = tarfile.SYMTYPE
                link.linkname = "/tmp/ffmpeg"
                bundle.addfile(link)
                probe = tarfile.TarInfo("ffprobe")
                payload = b"probe"
                probe.size = len(payload)
                bundle.addfile(probe, io.BytesIO(payload))
            with self.assertRaises(RuntimeError):
                module._safe_extract_ffmpeg(symlink, root / "b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
