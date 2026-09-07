from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from gallery_dl_manager import (  # noqa: E402
    existing_managed_gallery_dl,
    gallery_dl_version,
    install_managed_gallery_dl_online,
    remove_managed_gallery_dl,
    run_gallery_dl_manager_self_test,
)
from gallery_dl_source import (  # noqa: E402
    GALLERY_DL_METADATA_API,
    GalleryDlSourceError,
    ResolvedGalleryDlSource,
    fetch_gallery_dl_metadata,
    resolve_gallery_dl_source,
    run_gallery_dl_source_self_test,
)
from managed_tool_metadata import read_managed_tool_metadata  # noqa: E402
from managed_tool_registry import DEFAULT_MANAGED_TOOL_SPECS, ManagedToolObservation, evaluate_tool_health  # noqa: E402
from tool_artifacts import ToolArtifact, runtime_arch, runtime_platform  # noqa: E402


class _Response(BytesIO):
    def __init__(self, payload: bytes, url: str = GALLERY_DL_METADATA_API):
        super().__init__(payload)
        self._url = url

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


class ManagedGalleryDlTests(unittest.TestCase):
    VERSION = "1.32.11"

    def metadata_payload(self, *, url_host: str = "files.pythonhosted.org", version: str | None = None) -> dict:
        selected = version or self.VERSION
        asset = f"gallery_dl-{selected}-py3-none-any.whl"
        return {
            "info": {"version": selected},
            "urls": [
                {
                    "filename": asset,
                    "packagetype": "bdist_wheel",
                    "yanked": False,
                    "url": f"https://{url_host}/packages/aa/bb/{asset}",
                    "digests": {"sha256": "a" * 64},
                    "upload_time_iso_8601": "2026-09-04T10:00:00Z",
                }
            ],
        }

    def wheel_fixture(self, root: Path, *, version: str | None = None, forged_metadata: bool = False) -> tuple[ResolvedGalleryDlSource, bytes]:
        selected = version or self.VERSION
        asset = f"gallery_dl-{selected}-py3-none-any.whl"
        wheel = root / asset
        dist_info = f"gallery_dl-{selected}.dist-info"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("gallery_dl/__init__.py", "__version__ = 'fixture'\n")
            archive.writestr("gallery_dl/__main__.py", "def main():\n    return 0\n")
            archive.writestr(
                f"{dist_info}/METADATA",
                f"Metadata-Version: 2.1\nName: gallery-dl\nVersion: {selected}\n\n",
            )
            if forged_metadata:
                archive.writestr(".galaxy-tool.json", "{}")
        payload = wheel.read_bytes()
        artifact = ToolArtifact(
            tool="gallery-dl",
            version=selected,
            platform=runtime_platform(),
            arch=runtime_arch(),
            url=f"https://files.pythonhosted.org/packages/aa/bb/{asset}",
            sha256=hashlib.sha256(payload).hexdigest(),
            archive="zip",
        )
        return (
            ResolvedGalleryDlSource(
                provider_id="pypi-gallery-dl",
                artifact=artifact,
                release_tag=selected,
                published_at="2026-09-04T10:00:00Z",
                release_url=f"https://pypi.org/project/gallery-dl/{selected}/",
                asset_name=asset,
                provenance_url="https://github.com/mikf/gallery-dl",
            ),
            payload,
        )

    @staticmethod
    def engine(tools: Path):
        class Engine:
            invalidations = 0

            @staticmethod
            def tools_dir() -> Path:
                return tools

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

    def test_provider_accepts_only_pypi_metadata_boundary_and_universal_wheel(self) -> None:
        payload = self.metadata_payload()
        response = _Response(json.dumps(payload).encode("utf-8"))
        loaded = fetch_gallery_dl_metadata(opener=lambda *_args, **_kwargs: response)
        resolved = resolve_gallery_dl_source(platform_name="windows", arch="x86-64", metadata=loaded)
        self.assertEqual(resolved.artifact.tool, "gallery-dl")
        self.assertEqual(resolved.artifact.version, self.VERSION)
        self.assertEqual(resolved.artifact.archive, "zip")
        self.assertEqual(resolved.asset_name, f"gallery_dl-{self.VERSION}-py3-none-any.whl")

        bad_redirect = _Response(json.dumps(payload).encode("utf-8"), "https://example.com/pypi/gallery-dl/json")
        with self.assertRaises(GalleryDlSourceError):
            fetch_gallery_dl_metadata(opener=lambda *_args, **_kwargs: bad_redirect)
        with self.assertRaises(GalleryDlSourceError):
            resolve_gallery_dl_source(platform_name="windows", arch="x86-64", metadata=self.metadata_payload(url_host="example.com"))
        with self.assertRaises(GalleryDlSourceError):
            resolve_gallery_dl_source(platform_name="windows", arch="x86-64", metadata=self.metadata_payload(version="1.32.12.dev1"))

    def test_install_writes_provenance_and_remove_cleans_managed_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            resolved, payload = self.wheel_fixture(root)
            engine = self.engine(tools)
            result = install_managed_gallery_dl_online(
                engine,
                resolver=lambda: resolved,
                downloader=self.downloader(payload),
                installed_at_factory=lambda: "2026-09-07T00:00:00Z",
                workspace_root=root / "workspace",
            )
            self.assertTrue(result.ok)
            self.assertTrue(result.changed)
            self.assertEqual(result.version, self.VERSION)
            installed = existing_managed_gallery_dl(engine)
            self.assertIsNotNone(installed)
            self.assertEqual(gallery_dl_version(installed), self.VERSION)
            metadata = read_managed_tool_metadata(installed, expected_tool="gallery-dl")
            self.assertIsNotNone(metadata)
            self.assertEqual(metadata.providerId, "pypi-gallery-dl")
            self.assertEqual(metadata.binaryVersion, self.VERSION)
            self.assertEqual(metadata.sha256, resolved.artifact.sha256)
            self.assertEqual(engine.invalidations, 1)
            self.assertFalse(any((root / "workspace").glob(".gallery-dl-online-*")))

            spec = next(item for item in DEFAULT_MANAGED_TOOL_SPECS if item.tool == "gallery-dl")
            health = evaluate_tool_health(
                spec,
                ManagedToolObservation(True, "managed", self.VERSION, installed),
            )
            self.assertEqual(health.state, "managed-online")
            self.assertEqual(health.health, "ok")

            removed = remove_managed_gallery_dl(engine)
            self.assertTrue(removed.ok)
            self.assertTrue(removed.changed)
            self.assertIsNone(existing_managed_gallery_dl(engine))
            self.assertEqual(engine.invalidations, 2)

    def test_failed_validation_or_forged_provenance_preserves_previous_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            engine = self.engine(tools)
            old_resolved, old_payload = self.wheel_fixture(root, version="1.32.10")
            first = install_managed_gallery_dl_online(
                engine,
                resolver=lambda: old_resolved,
                downloader=self.downloader(old_payload),
                workspace_root=root / "workspace-old",
            )
            self.assertTrue(first.ok)
            self.assertEqual(gallery_dl_version(existing_managed_gallery_dl(engine)), "1.32.10")

            forged, forged_payload = self.wheel_fixture(root, version=self.VERSION, forged_metadata=True)
            second = install_managed_gallery_dl_online(
                engine,
                resolver=lambda: forged,
                downloader=self.downloader(forged_payload),
                workspace_root=root / "workspace-new",
            )
            self.assertFalse(second.ok)
            self.assertEqual(gallery_dl_version(existing_managed_gallery_dl(engine)), "1.32.10")

    def test_embedded_self_tests(self) -> None:
        run_gallery_dl_source_self_test()
        run_gallery_dl_manager_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
