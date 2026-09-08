from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from gallery_dl_source import ResolvedGalleryDlSource  # noqa: E402
from gallery_dl_update_status import check_gallery_dl_update  # noqa: E402
from managed_tool_metadata import (  # noqa: E402
    MANAGED_TOOL_METADATA_SCHEMA,
    ManagedToolMetadata,
    write_managed_tool_metadata,
)
from tool_artifacts import ToolArtifact, runtime_arch, runtime_platform  # noqa: E402


class GalleryDlUpdateStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tools = self.root / "tools"
        self.platform = runtime_platform()
        self.arch = runtime_arch()

        tools = self.tools

        class Engine:
            @staticmethod
            def tools_dir() -> Path:
                return tools

        self.engine = Engine

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _resolved(
        self,
        version: str,
        *,
        published_at: str,
        sha256: str | None = None,
        release_tag: str | None = None,
    ) -> ResolvedGalleryDlSource:
        asset_name = f"gallery_dl-{version}-py3-none-any.whl"
        digest = sha256 or hashlib.sha256(asset_name.encode("utf-8")).hexdigest()
        artifact = ToolArtifact(
            tool="gallery-dl",
            version=version,
            platform=self.platform,
            arch=self.arch,
            url=f"https://files.pythonhosted.org/packages/aa/bb/{asset_name}",
            sha256=digest,
            archive="zip",
        )
        return ResolvedGalleryDlSource(
            provider_id="pypi-gallery-dl",
            artifact=artifact,
            release_tag=release_tag or version,
            published_at=published_at,
            release_url=f"https://pypi.org/project/gallery-dl/{version}/",
            asset_name=asset_name,
            provenance_url="https://github.com/mikf/gallery-dl",
        )

    def _install_fixture(
        self,
        version: str,
        *,
        published_at: str,
        sha256: str | None = None,
        release_tag: str | None = None,
        provider_id: str = "pypi-gallery-dl",
    ) -> ResolvedGalleryDlSource:
        resolved = self._resolved(
            version,
            published_at=published_at,
            sha256=sha256,
            release_tag=release_tag,
        )
        root = self.tools / "gallery-dl"
        (root / "gallery_dl").mkdir(parents=True, exist_ok=True)
        (root / "gallery_dl" / "__init__.py").write_text("__version__ = 'fixture'\n", encoding="utf-8")
        dist_info = root / f"gallery_dl-{version}.dist-info"
        dist_info.mkdir(parents=True, exist_ok=True)
        (dist_info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: gallery-dl\nVersion: {version}\n\n",
            encoding="utf-8",
        )
        write_managed_tool_metadata(
            root,
            ManagedToolMetadata(
                schemaVersion=MANAGED_TOOL_METADATA_SCHEMA,
                tool="gallery-dl",
                source="online",
                platform=self.platform,
                arch=self.arch,
                binaryVersion=version,
                installedAt="2026-09-07T00:00:00Z",
                providerId=provider_id,
                artifactVersion=version,
                releaseTag=resolved.release_tag,
                publishedAt=published_at,
                sha256=resolved.artifact.sha256,
                assetName=resolved.asset_name,
                releaseUrl=resolved.release_url,
                provenanceUrl=resolved.provenance_url,
            ),
        )
        return resolved

    def test_missing_install_reports_install_available(self) -> None:
        available = self._resolved("1.32.11", published_at="2026-09-04T10:00:00Z")
        status = check_gallery_dl_update(self.engine, resolver=lambda: available)
        self.assertTrue(status.ok)
        self.assertEqual(status.state, "install_available")
        self.assertEqual(status.current_source, "unavailable")
        self.assertEqual(status.available_version, "1.32.11")
        self.assertTrue(status.update_available)

    def test_same_release_identity_reports_current(self) -> None:
        installed = self._install_fixture("1.32.11", published_at="2026-09-04T10:00:00Z")
        status = check_gallery_dl_update(self.engine, resolver=lambda: installed)
        self.assertTrue(status.ok)
        self.assertEqual(status.state, "current")
        self.assertEqual(status.current_version, "1.32.11")
        self.assertFalse(status.update_available)

    def test_newer_provider_release_reports_update_available(self) -> None:
        self._install_fixture("1.32.10", published_at="2026-08-30T10:00:00Z")
        available = self._resolved("1.32.11", published_at="2026-09-04T10:00:00Z")
        status = check_gallery_dl_update(self.engine, resolver=lambda: available)
        self.assertTrue(status.ok)
        self.assertEqual(status.state, "update_available")
        self.assertEqual(status.current_version, "1.32.10")
        self.assertEqual(status.available_version, "1.32.11")
        self.assertTrue(status.update_available)

    def test_older_provider_release_never_suggests_downgrade(self) -> None:
        self._install_fixture("1.32.12", published_at="2026-09-06T10:00:00Z")
        available = self._resolved("1.32.11", published_at="2026-09-04T10:00:00Z")
        status = check_gallery_dl_update(self.engine, resolver=lambda: available)
        self.assertTrue(status.ok)
        self.assertEqual(status.state, "ahead")
        self.assertFalse(status.update_available)

    def test_same_release_tag_with_changed_digest_is_integrity_error(self) -> None:
        installed = self._install_fixture("1.32.11", published_at="2026-09-04T10:00:00Z")
        available = self._resolved(
            "1.32.11",
            published_at="2026-09-04T10:00:00Z",
            sha256="f" * 64,
        )
        self.assertNotEqual(installed.artifact.sha256, available.artifact.sha256)
        status = check_gallery_dl_update(self.engine, resolver=lambda: available)
        self.assertFalse(status.ok)
        self.assertEqual(status.state, "integrity_changed")
        self.assertIsNone(status.update_available)

    def test_provider_mismatch_is_not_guessed_as_update(self) -> None:
        self._install_fixture(
            "1.32.10",
            published_at="2026-08-30T10:00:00Z",
            provider_id="legacy-provider",
        )
        available = self._resolved("1.32.11", published_at="2026-09-04T10:00:00Z")
        status = check_gallery_dl_update(self.engine, resolver=lambda: available)
        self.assertTrue(status.ok)
        self.assertEqual(status.state, "unknown_current")
        self.assertIsNone(status.update_available)

    def test_provider_failure_is_bounded_error(self) -> None:
        status = check_gallery_dl_update(
            self.engine,
            resolver=lambda: (_ for _ in ()).throw(RuntimeError("offline")),
        )
        self.assertFalse(status.ok)
        self.assertEqual(status.state, "error")
        self.assertIn("offline", status.message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
