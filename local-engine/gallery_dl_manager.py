from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from email.parser import Parser
from pathlib import Path
from typing import Callable

from gallery_dl_runtime_dependencies import ensure_gallery_dl_runtime_dependencies
from gallery_dl_source import ResolvedGalleryDlSource, resolve_gallery_dl_source
from managed_tool_metadata import (
    MANAGED_TOOL_METADATA_SCHEMA,
    ManagedToolMetadata,
    write_managed_tool_metadata,
)
from tool_artifacts import ToolArtifactError, download_verified_artifact, install_verified_artifact


@dataclass(frozen=True)
class GalleryDlActionResult:
    ok: bool
    changed: bool
    version: str | None
    source: str
    message: str


def managed_gallery_dl_root(engine_module) -> Path:
    return Path(engine_module.tools_dir()) / "gallery-dl"


def _dist_info_directories(root: Path) -> tuple[Path, ...]:
    try:
        values = tuple(
            item
            for item in Path(root).iterdir()
            if item.is_dir() and not item.is_symlink() and item.name.startswith("gallery_dl-") and item.name.endswith(".dist-info")
        )
    except OSError:
        return ()
    return values


def gallery_dl_version(root: Path | None) -> str | None:
    if root is None:
        return None
    directory = Path(root)
    package = directory / "gallery_dl" / "__init__.py"
    if not directory.is_dir() or directory.is_symlink() or not package.is_file() or package.is_symlink():
        return None
    dist_infos = _dist_info_directories(directory)
    if len(dist_infos) != 1:
        return None
    metadata = dist_infos[0] / "METADATA"
    if not metadata.is_file() or metadata.is_symlink():
        return None
    try:
        if metadata.stat().st_size > 1024 * 1024:
            return None
        parsed = Parser().parsestr(metadata.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    name = str(parsed.get("Name") or "").strip().lower().replace("_", "-")
    version = str(parsed.get("Version") or "").strip()
    if name != "gallery-dl" or not version or len(version) > 128:
        return None
    return version


def existing_managed_gallery_dl(engine_module) -> Path | None:
    root = managed_gallery_dl_root(engine_module)
    return root if gallery_dl_version(root) is not None else None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def install_managed_gallery_dl_online(
    engine_module,
    *,
    resolver: Callable[[], ResolvedGalleryDlSource] = resolve_gallery_dl_source,
    downloader: Callable[..., Path] = download_verified_artifact,
    installer: Callable[..., Path] = install_verified_artifact,
    installed_at_factory: Callable[[], str] = _utc_now_iso,
    workspace_root: Path | None = None,
) -> GalleryDlActionResult:
    """Install/update gallery-dl from the pinned PyPI project metadata boundary.

    The wheel is never executed as an installer. Galaxy verifies its PyPI
    SHA-256, extracts it with the common bounded archive implementation, checks
    package metadata, writes local provenance inside staging, and only then
    atomically promotes the staged directory to tools/gallery-dl.
    """
    current_root = existing_managed_gallery_dl(engine_module)
    current_version = gallery_dl_version(current_root)
    tools_root = Path(engine_module.tools_dir())
    tools_root.mkdir(parents=True, exist_ok=True)
    parent = Path(workspace_root) if workspace_root is not None else tools_root
    parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=".gallery-dl-online-", dir=str(parent)))

    try:
        ensure_gallery_dl_runtime_dependencies()
        resolved = resolver()
        artifact = resolved.artifact
        if artifact.tool != "gallery-dl":
            raise ToolArtifactError(f"trusted provider returned unexpected tool: {artifact.tool}")
        archive_path = workspace / resolved.asset_name
        downloader(artifact, archive_path)
        target = managed_gallery_dl_root(engine_module)
        validated_version: str | None = None

        def validate_before_promotion(payload: Path) -> bool:
            nonlocal validated_version
            validated_version = gallery_dl_version(payload)
            if validated_version != artifact.version:
                return False
            metadata = ManagedToolMetadata(
                schemaVersion=MANAGED_TOOL_METADATA_SCHEMA,
                tool="gallery-dl",
                source="online",
                platform=artifact.platform,
                arch=artifact.arch,
                binaryVersion=validated_version,
                installedAt=installed_at_factory(),
                providerId=resolved.provider_id,
                artifactVersion=artifact.version,
                releaseTag=resolved.release_tag,
                publishedAt=resolved.published_at,
                sha256=artifact.sha256,
                assetName=resolved.asset_name,
                releaseUrl=resolved.release_url,
                provenanceUrl=resolved.provenance_url,
            )
            write_managed_tool_metadata(payload, metadata)
            return True

        installer(
            artifact,
            archive_path,
            target,
            required_files=("gallery_dl/__init__.py", "gallery_dl/__main__.py"),
            validator=validate_before_promotion,
            max_members=20_000,
            max_extracted_bytes=512 * 1024 * 1024,
        )
        if validated_version is None:
            raise AssertionError("validated gallery-dl version was not captured before promotion")

        invalidate = getattr(engine_module, "invalidate_tool_inventory", None)
        if callable(invalidate):
            invalidate()
        return GalleryDlActionResult(
            True,
            current_version != validated_version,
            validated_version,
            "managed",
            (
                f"Managed gallery-dl {validated_version} was installed from {resolved.provider_id} "
                "after SHA-256, package metadata and provenance validation."
            ),
        )
    except Exception as exc:
        fallback_root = existing_managed_gallery_dl(engine_module)
        fallback_version = gallery_dl_version(fallback_root)
        return GalleryDlActionResult(
            False,
            False,
            fallback_version or current_version,
            "managed" if (fallback_version or current_version) else "unavailable",
            f"Could not install Managed gallery-dl from the trusted online source: {exc}",
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def remove_managed_gallery_dl(engine_module) -> GalleryDlActionResult:
    root = managed_gallery_dl_root(engine_module)
    version = gallery_dl_version(root)
    if version is None:
        return GalleryDlActionResult(True, False, None, "unavailable", "Managed gallery-dl is not installed.")
    if root.is_symlink() or not root.is_dir():
        return GalleryDlActionResult(False, False, version, "managed", "Managed gallery-dl root is not a safe directory.")
    try:
        shutil.rmtree(root)
    except OSError as exc:
        return GalleryDlActionResult(False, False, version, "managed", f"Could not remove Managed gallery-dl: {exc}")
    invalidate = getattr(engine_module, "invalidate_tool_inventory", None)
    if callable(invalidate):
        invalidate()
    return GalleryDlActionResult(True, True, None, "unavailable", "Managed gallery-dl was removed.")


def run_gallery_dl_manager_self_test() -> None:
    import hashlib
    import zipfile

    from gallery_dl_source import ResolvedGalleryDlSource
    from managed_tool_metadata import read_managed_tool_metadata
    from tool_artifacts import ToolArtifact, runtime_arch, runtime_platform

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        tools = root / "tools"
        workspace = root / "workspace"
        version = "1.32.11"
        asset_name = f"gallery_dl-{version}-py3-none-any.whl"
        wheel = root / asset_name
        dist_info = f"gallery_dl-{version}.dist-info"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("gallery_dl/__init__.py", "__version__ = 'test'\n")
            archive.writestr("gallery_dl/__main__.py", "def main():\n    return 0\n")
            archive.writestr(
                f"{dist_info}/METADATA",
                f"Metadata-Version: 2.1\nName: gallery-dl\nVersion: {version}\n\n",
            )
        payload = wheel.read_bytes()
        platform_name = runtime_platform()
        arch = runtime_arch()
        artifact = ToolArtifact(
            tool="gallery-dl",
            version=version,
            platform=platform_name,
            arch=arch,
            url=f"https://files.pythonhosted.org/packages/aa/bb/{asset_name}",
            sha256=hashlib.sha256(payload).hexdigest(),
            archive="zip",
        )
        resolved = ResolvedGalleryDlSource(
            provider_id="pypi-gallery-dl",
            artifact=artifact,
            release_tag=version,
            published_at="2026-09-04T10:00:00Z",
            release_url=f"https://pypi.org/project/gallery-dl/{version}/",
            asset_name=asset_name,
            provenance_url="https://github.com/mikf/gallery-dl",
        )

        class Engine:
            @staticmethod
            def tools_dir() -> Path:
                return tools

        def fake_download(_artifact, destination: Path) -> Path:
            target = Path(destination)
            target.write_bytes(payload)
            return target

        result = install_managed_gallery_dl_online(
            Engine,
            resolver=lambda: resolved,
            downloader=fake_download,
            installed_at_factory=lambda: "2026-09-07T00:00:00Z",
            workspace_root=workspace,
        )
        assert result.ok is True
        assert result.changed is True
        assert result.version == version
        installed = existing_managed_gallery_dl(Engine)
        assert installed == tools / "gallery-dl"
        assert gallery_dl_version(installed) == version
        metadata = read_managed_tool_metadata(installed, expected_tool="gallery-dl")
        assert metadata is not None
        assert metadata.providerId == "pypi-gallery-dl"
        assert metadata.sha256 == artifact.sha256
        assert metadata.binaryVersion == version
        assert not any(workspace.glob(".gallery-dl-online-*"))

        removed = remove_managed_gallery_dl(Engine)
        assert removed.ok is True and removed.changed is True
        assert existing_managed_gallery_dl(Engine) is None
