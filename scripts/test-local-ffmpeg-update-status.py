from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from ffmpeg_update_status import check_ffmpeg_update, run_ffmpeg_update_status_self_test  # noqa: E402
from managed_tool_metadata import (  # noqa: E402
    MANAGED_TOOL_METADATA_SCHEMA,
    ManagedToolMetadata,
    write_managed_tool_metadata,
)
from tool_artifacts import ToolArtifact, runtime_arch, runtime_platform  # noqa: E402
from tool_sources import ResolvedToolSource  # noqa: E402


class FfmpegUpdateStatusTests(unittest.TestCase):
    def engine(self, tools: Path):
        class Engine:
            @staticmethod
            def tools_dir() -> Path:
                return tools

        return Engine

    def make_managed(self, tools: Path) -> Path:
        suffix = ".exe" if runtime_platform() == "windows" else ""
        root = tools / "ffmpeg"
        (root / "bin").mkdir(parents=True, exist_ok=True)
        (root / "bin" / f"ffmpeg{suffix}").write_bytes(b"ffmpeg")
        return root

    def resolved(
        self,
        *,
        tag: str = "autobuild-2026-09-02-12-00",
        published: str = "2026-09-02T12:05:00Z",
        digest: str = "b" * 64,
        version: str = "N-126400-gbbbbbbbbbb",
    ) -> ResolvedToolSource:
        platform_name = runtime_platform()
        arch = runtime_arch()
        target = "win64" if platform_name == "windows" else "linux64"
        archive = "zip" if platform_name == "windows" else "tar.xz"
        asset = f"ffmpeg-{version}-{target}-gpl.{archive}"
        artifact = ToolArtifact(
            tool="ffmpeg",
            version=version,
            platform=platform_name,
            arch=arch,
            url=f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{tag}/{asset}",
            sha256=digest,
            archive=archive,
        )
        return ResolvedToolSource(
            provider_id="btbn-ffmpeg-builds",
            artifact=artifact,
            release_tag=tag,
            published_at=published,
            release_url=f"https://github.com/BtbN/FFmpeg-Builds/releases/tag/{tag}",
            asset_name=asset,
            provenance_url="https://ffmpeg.org/download.html",
        )

    def installed_metadata(
        self,
        resolved: ResolvedToolSource,
        *,
        tag: str = "autobuild-2026-09-01-12-00",
        published: str = "2026-09-01T12:05:00Z",
        digest: str = "a" * 64,
        version: str = "N-126300-gaaaaaaaaaa",
        asset_name: str | None = None,
    ) -> ManagedToolMetadata:
        platform_name = runtime_platform()
        arch = runtime_arch()
        target = "win64" if platform_name == "windows" else "linux64"
        archive = "zip" if platform_name == "windows" else "tar.xz"
        name = asset_name or f"ffmpeg-{version}-{target}-gpl.{archive}"
        return ManagedToolMetadata(
            schemaVersion=MANAGED_TOOL_METADATA_SCHEMA,
            tool="ffmpeg",
            source="online",
            platform=platform_name,
            arch=arch,
            binaryVersion=f"ffmpeg version {version}",
            installedAt="2026-09-01T12:10:00Z",
            providerId=resolved.provider_id,
            artifactVersion=version,
            releaseTag=tag,
            publishedAt=published,
            sha256=digest,
            assetName=name,
            releaseUrl=f"https://github.com/BtbN/FFmpeg-Builds/releases/tag/{tag}",
            provenanceUrl="https://ffmpeg.org/download.html",
        )

    def check(self, engine, resolved: ResolvedToolSource):
        with (
            patch("ffmpeg_update_status.trusted_ffmpeg_source_available", return_value=True),
            patch("ffmpeg_update_status.ffmpeg_version", return_value="ffmpeg version local"),
        ):
            return check_ffmpeg_update(engine, resolver=lambda: resolved)

    def test_no_managed_copy_reports_install_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            resolved = self.resolved()
            status = self.check(self.engine(Path(directory) / "tools"), resolved)
            self.assertTrue(status.ok)
            self.assertEqual(status.state, "install_available")
            self.assertTrue(status.update_available)
            self.assertEqual(status.available_release_tag, resolved.release_tag)

    def test_same_release_identity_reports_current(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory) / "tools"
            root = self.make_managed(tools)
            resolved = self.resolved()
            metadata = self.installed_metadata(
                resolved,
                tag=resolved.release_tag,
                published=resolved.published_at,
                digest=resolved.artifact.sha256,
                version=resolved.artifact.version,
                asset_name=resolved.asset_name,
            )
            write_managed_tool_metadata(root, metadata)
            status = self.check(self.engine(tools), resolved)
            self.assertTrue(status.ok)
            self.assertEqual(status.state, "current")
            self.assertFalse(status.update_available)

    def test_newer_release_reports_update_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory) / "tools"
            root = self.make_managed(tools)
            resolved = self.resolved()
            write_managed_tool_metadata(root, self.installed_metadata(resolved))
            status = self.check(self.engine(tools), resolved)
            self.assertTrue(status.ok)
            self.assertEqual(status.state, "update_available")
            self.assertTrue(status.update_available)
            self.assertIn(resolved.release_tag, status.message)

    def test_provider_older_than_installed_never_recommends_downgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory) / "tools"
            root = self.make_managed(tools)
            resolved = self.resolved(published="2026-09-01T12:05:00Z")
            write_managed_tool_metadata(
                root,
                self.installed_metadata(
                    resolved,
                    tag="autobuild-2026-09-03-12-00",
                    published="2026-09-03T12:05:00Z",
                ),
            )
            status = self.check(self.engine(tools), resolved)
            self.assertTrue(status.ok)
            self.assertEqual(status.state, "ahead")
            self.assertFalse(status.update_available)

    def test_same_release_tag_with_changed_digest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory) / "tools"
            root = self.make_managed(tools)
            resolved = self.resolved()
            write_managed_tool_metadata(
                root,
                self.installed_metadata(
                    resolved,
                    tag=resolved.release_tag,
                    published=resolved.published_at,
                    digest="a" * 64,
                    version=resolved.artifact.version,
                    asset_name=resolved.asset_name,
                ),
            )
            status = self.check(self.engine(tools), resolved)
            self.assertFalse(status.ok)
            self.assertEqual(status.state, "integrity_changed")
            self.assertIsNone(status.update_available)

    def test_managed_copy_without_online_metadata_is_not_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory) / "tools"
            self.make_managed(tools)
            resolved = self.resolved()
            status = self.check(self.engine(tools), resolved)
            self.assertTrue(status.ok)
            self.assertEqual(status.state, "unknown_current")
            self.assertIsNone(status.update_available)

    def test_corrupt_local_metadata_is_reported_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory) / "tools"
            root = self.make_managed(tools)
            (root / ".galaxy-tool.json").write_text("{bad-json", encoding="utf-8")
            resolved = self.resolved()
            status = self.check(self.engine(tools), resolved)
            self.assertFalse(status.ok)
            self.assertEqual(status.state, "metadata_invalid")

    def test_provider_failure_and_unsupported_platform_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = self.engine(Path(directory) / "tools")
            with patch("ffmpeg_update_status.trusted_ffmpeg_source_available", return_value=True):
                status = check_ffmpeg_update(engine, resolver=lambda: (_ for _ in ()).throw(OSError("offline")))
            self.assertFalse(status.ok)
            self.assertEqual(status.state, "error")

            called = False

            def should_not_resolve():
                nonlocal called
                called = True
                raise AssertionError("resolver should not run")

            with patch("ffmpeg_update_status.trusted_ffmpeg_source_available", return_value=False):
                status = check_ffmpeg_update(engine, resolver=should_not_resolve)
            self.assertTrue(status.ok)
            self.assertEqual(status.state, "unsupported")
            self.assertFalse(called)

    def test_embedded_self_test(self) -> None:
        run_ffmpeg_update_status_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
