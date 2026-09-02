from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from ffmpeg_online_installer import (  # noqa: E402
    install_managed_ffmpeg_online,
    run_ffmpeg_online_installer_self_test,
    validate_ffmpeg_payload,
)
from managed_tool_metadata import (  # noqa: E402
    MANAGED_TOOL_METADATA_SCHEMA,
    ManagedToolMetadata,
    read_managed_tool_metadata,
    write_managed_tool_metadata,
)
from tool_artifacts import ToolArtifact, runtime_arch, runtime_platform  # noqa: E402
from tool_sources import ResolvedToolSource  # noqa: E402


class FfmpegOnlineInstallerTests(unittest.TestCase):
    def fixture(
        self,
        root: Path,
        *,
        tool: str = "ffmpeg",
        include_forged_metadata: bool = False,
    ) -> tuple[ResolvedToolSource, bytes, str, str]:
        platform_name = runtime_platform()
        suffix = ".exe" if platform_name == "windows" else ""
        asset_name = "ffmpeg-N-126313-g1ae4048218-test-gpl.zip"
        build_root = asset_name.removesuffix(".zip")
        archive_path = root / asset_name
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(f"{build_root}/bin/ffmpeg{suffix}", b"new-ffmpeg")
            archive.writestr(f"{build_root}/bin/ffprobe{suffix}", b"new-ffprobe")
            if include_forged_metadata:
                archive.writestr(f"{build_root}/.galaxy-tool.json", b"{}")
        payload = archive_path.read_bytes()
        artifact = ToolArtifact(
            tool=tool,
            version="N-126313-g1ae4048218",
            platform=platform_name,
            arch=runtime_arch(),
            url=f"https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-test/{asset_name}",
            sha256=hashlib.sha256(payload).hexdigest(),
            archive="zip",
        )
        return (
            ResolvedToolSource(
                provider_id="btbn-ffmpeg-builds",
                artifact=artifact,
                release_tag="autobuild-test",
                published_at="2026-09-01T00:00:00Z",
                release_url="https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-test",
                asset_name=asset_name,
                provenance_url="https://ffmpeg.org/download.html",
            ),
            payload,
            suffix,
            build_root,
        )

    def engine(self, tools: Path, bundled: Path | None = None):
        class Engine:
            invalidations = 0

            @staticmethod
            def tools_dir() -> Path:
                return tools

            @staticmethod
            def bundled_ffmpeg_dir() -> Path | None:
                return bundled

            @classmethod
            def invalidate_tool_inventory(cls) -> None:
                cls.invalidations += 1

        return Engine

    @staticmethod
    def downloader(payload: bytes):
        def download(_artifact, destination: Path) -> Path:
            target = Path(destination)
            target.write_bytes(payload)
            return target

        return download

    def old_metadata(self, *, suffix: str) -> ManagedToolMetadata:
        return ManagedToolMetadata(
            schemaVersion=MANAGED_TOOL_METADATA_SCHEMA,
            tool="ffmpeg",
            source="online",
            platform=runtime_platform(),
            arch=runtime_arch(),
            binaryVersion="ffmpeg version old",
            installedAt="2026-08-31T00:00:00Z",
            providerId="btbn-ffmpeg-builds",
            artifactVersion="N-126000-gold",
            releaseTag="autobuild-old",
            publishedAt="2026-08-31T00:00:00Z",
            sha256="a" * 64,
            assetName=f"ffmpeg-N-126000-gold-test-gpl.zip",
            releaseUrl="https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-old",
            provenanceUrl="https://ffmpeg.org/download.html",
        )

    def test_success_installs_flat_layout_provenance_and_cleans_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            workspace = root / "workspace"
            resolved, payload, suffix, build_root = self.fixture(root)
            engine = self.engine(tools)

            result = install_managed_ffmpeg_online(
                engine,
                resolver=lambda: resolved,
                downloader=self.downloader(payload),
                payload_validator=lambda payload_root, **_kwargs: (
                    (payload_root / "bin" / f"ffmpeg{suffix}").read_bytes() == b"new-ffmpeg"
                    and (payload_root / "bin" / f"ffprobe{suffix}").read_bytes() == b"new-ffprobe"
                ),
                version_reader=lambda _directory: "ffmpeg version online-test",
                installed_at_factory=lambda: "2026-09-02T00:00:00Z",
                workspace_root=workspace,
            )

            self.assertTrue(result.ok)
            self.assertTrue(result.changed)
            self.assertEqual(result.source, "managed")
            self.assertEqual(result.version, "ffmpeg version online-test")
            self.assertIn("btbn-ffmpeg-builds", result.message)
            self.assertEqual((tools / "ffmpeg" / "bin" / f"ffmpeg{suffix}").read_bytes(), b"new-ffmpeg")
            self.assertEqual((tools / "ffmpeg" / "bin" / f"ffprobe{suffix}").read_bytes(), b"new-ffprobe")
            metadata = read_managed_tool_metadata(tools / "ffmpeg", expected_tool="ffmpeg")
            self.assertIsNotNone(metadata)
            self.assertEqual(metadata.releaseTag, resolved.release_tag)
            self.assertEqual(metadata.artifactVersion, resolved.artifact.version)
            self.assertEqual(metadata.sha256, resolved.artifact.sha256)
            self.assertEqual(metadata.binaryVersion, "ffmpeg version online-test")
            self.assertFalse((tools / "ffmpeg" / build_root).exists())
            self.assertFalse(any(workspace.glob(".ffmpeg-online-*")))
            self.assertEqual(engine.invalidations, 1)

    def test_validation_failure_preserves_previous_managed_ffmpeg_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            resolved, payload, suffix, _build_root = self.fixture(root)
            old_root = tools / "ffmpeg"
            old_bin = old_root / "bin"
            old_bin.mkdir(parents=True)
            (old_bin / f"ffmpeg{suffix}").write_bytes(b"old-ffmpeg")
            (old_bin / f"ffprobe{suffix}").write_bytes(b"old-ffprobe")
            previous_metadata = self.old_metadata(suffix=suffix)
            write_managed_tool_metadata(old_root, previous_metadata)
            engine = self.engine(tools)

            result = install_managed_ffmpeg_online(
                engine,
                resolver=lambda: resolved,
                downloader=self.downloader(payload),
                payload_validator=lambda *_args, **_kwargs: False,
                version_reader=lambda _directory: "should-not-matter",
                workspace_root=root / "workspace",
            )

            self.assertFalse(result.ok)
            self.assertFalse(result.changed)
            self.assertEqual(result.source, "managed")
            self.assertEqual((old_bin / f"ffmpeg{suffix}").read_bytes(), b"old-ffmpeg")
            self.assertEqual((old_bin / f"ffprobe{suffix}").read_bytes(), b"old-ffprobe")
            self.assertEqual(read_managed_tool_metadata(old_root, expected_tool="ffmpeg"), previous_metadata)
            self.assertEqual(engine.invalidations, 0)

    def test_version_or_metadata_failure_happens_before_atomic_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            resolved, payload, suffix, _build_root = self.fixture(root)
            old_bin = tools / "ffmpeg" / "bin"
            old_bin.mkdir(parents=True)
            (old_bin / f"ffmpeg{suffix}").write_bytes(b"old-ffmpeg")
            (old_bin / f"ffprobe{suffix}").write_bytes(b"old-ffprobe")
            engine = self.engine(tools)

            result = install_managed_ffmpeg_online(
                engine,
                resolver=lambda: resolved,
                downloader=self.downloader(payload),
                payload_validator=lambda *_args, **_kwargs: True,
                version_reader=lambda _directory: None,
                workspace_root=root / "workspace",
            )
            self.assertFalse(result.ok)
            self.assertEqual((old_bin / f"ffmpeg{suffix}").read_bytes(), b"old-ffmpeg")

            forged, forged_payload, _suffix, _root = self.fixture(root, include_forged_metadata=True)
            result = install_managed_ffmpeg_online(
                engine,
                resolver=lambda: forged,
                downloader=self.downloader(forged_payload),
                payload_validator=lambda *_args, **_kwargs: True,
                version_reader=lambda _directory: "ffmpeg version new",
                workspace_root=root / "workspace-2",
            )
            self.assertFalse(result.ok)
            self.assertEqual((old_bin / f"ffmpeg{suffix}").read_bytes(), b"old-ffmpeg")

    def test_download_or_source_failure_never_changes_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            resolved, _payload, suffix, _build_root = self.fixture(root)
            old_bin = tools / "ffmpeg" / "bin"
            old_bin.mkdir(parents=True)
            (old_bin / f"ffmpeg{suffix}").write_bytes(b"old")
            engine = self.engine(tools)

            def fail_download(*_args, **_kwargs):
                raise OSError("network unavailable")

            result = install_managed_ffmpeg_online(
                engine,
                resolver=lambda: resolved,
                downloader=fail_download,
                workspace_root=root / "workspace",
            )
            self.assertFalse(result.ok)
            self.assertEqual((old_bin / f"ffmpeg{suffix}").read_bytes(), b"old")
            self.assertFalse(any((root / "workspace").glob(".ffmpeg-online-*")))

            wrong_source, payload, _suffix, _root = self.fixture(root, tool="not-ffmpeg")
            result = install_managed_ffmpeg_online(
                engine,
                resolver=lambda: wrong_source,
                downloader=self.downloader(payload),
                workspace_root=root / "workspace-2",
            )
            self.assertFalse(result.ok)
            self.assertEqual((old_bin / f"ffmpeg{suffix}").read_bytes(), b"old")

    def test_payload_validator_requires_both_executables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            suffix = ".exe" if runtime_platform() == "windows" else ""
            (bin_dir / f"ffmpeg{suffix}").write_bytes(b"x")
            (bin_dir / f"ffprobe{suffix}").write_bytes(b"x")
            with patch("ffmpeg_online_installer._read_binary_version", side_effect=["ffmpeg version test", "ffprobe version test"]):
                self.assertTrue(validate_ffmpeg_payload(root, platform_name=runtime_platform()))
            with patch("ffmpeg_online_installer._read_binary_version", side_effect=["ffmpeg version test", None]):
                self.assertFalse(validate_ffmpeg_payload(root, platform_name=runtime_platform()))

    def test_embedded_self_test(self) -> None:
        run_ffmpeg_online_installer_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
