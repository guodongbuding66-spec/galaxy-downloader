from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from gallery_dl_manager import existing_managed_gallery_dl, gallery_dl_version
from gallery_dl_source import ResolvedGalleryDlSource, resolve_gallery_dl_source
from managed_tool_metadata import ManagedToolMetadata, ManagedToolMetadataError, read_managed_tool_metadata


@dataclass(frozen=True)
class GalleryDlUpdateStatus:
    ok: bool
    state: str
    current_source: str
    current_version: str | None
    current_release_tag: str | None
    available_version: str | None
    available_release_tag: str | None
    available_published_at: str | None
    update_available: bool | None
    message: str


def _timestamp(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _current_state(engine_module) -> tuple[str, str | None, Path | None, ManagedToolMetadata | None, str | None]:
    root = existing_managed_gallery_dl(engine_module)
    if root is None:
        return "unavailable", None, None, None, None
    version = gallery_dl_version(root)
    try:
        metadata = read_managed_tool_metadata(root, expected_tool="gallery-dl")
        return "managed", version, root, metadata, None
    except ManagedToolMetadataError as exc:
        return "managed", version, root, None, str(exc)


def check_gallery_dl_update(
    engine_module,
    *,
    resolver: Callable[[], ResolvedGalleryDlSource] = resolve_gallery_dl_source,
) -> GalleryDlUpdateStatus:
    """Explicitly compare Managed gallery-dl with the trusted PyPI release identity.

    Inventory/startup never calls this function. It performs provider network
    access only after a caller explicitly requests the managed-tool `check`
    action.
    """
    current_source, current_version, _root, metadata, metadata_error = _current_state(engine_module)
    try:
        available = resolver()
    except Exception as exc:
        return GalleryDlUpdateStatus(
            False,
            "error",
            current_source,
            current_version,
            metadata.releaseTag if metadata else None,
            None,
            None,
            None,
            None,
            f"检查 gallery-dl 更新失败：{exc}",
        )

    artifact = available.artifact
    if artifact.tool != "gallery-dl":
        return GalleryDlUpdateStatus(
            False,
            "error",
            current_source,
            current_version,
            metadata.releaseTag if metadata else None,
            None,
            None,
            None,
            None,
            f"可信来源返回了意外工具：{artifact.tool}",
        )

    common = dict(
        current_source=current_source,
        current_version=current_version,
        available_version=artifact.version,
        available_release_tag=available.release_tag,
        available_published_at=available.published_at,
    )

    if current_source != "managed":
        return GalleryDlUpdateStatus(
            True,
            "install_available",
            current_release_tag=None,
            update_available=True,
            message=f"发现可安装的 gallery-dl {artifact.version}。安装仍需你手动确认。",
            **common,
        )

    if metadata_error:
        return GalleryDlUpdateStatus(
            False,
            "metadata_invalid",
            current_release_tag=None,
            update_available=None,
            message=(
                "当前 Managed gallery-dl 的 Galaxy 来源元数据无效，无法安全比较发布身份。"
                f" 本地包不会被修改。详情：{metadata_error}"
            ),
            **common,
        )

    if metadata is None:
        return GalleryDlUpdateStatus(
            True,
            "unknown_current",
            current_release_tag=None,
            update_available=None,
            message="当前 Managed gallery-dl 没有 Galaxy 在线来源元数据，因此不会猜测更新关系。",
            **common,
        )

    if metadata.source != "online" or metadata.providerId != available.provider_id:
        return GalleryDlUpdateStatus(
            True,
            "unknown_current",
            current_release_tag=metadata.releaseTag,
            update_available=None,
            message=(
                f"当前 gallery-dl 来源 {metadata.source}/{metadata.providerId or 'unknown'} "
                "无法与可信 PyPI provider 精确比较。"
            ),
            **common,
        )

    if metadata.platform != artifact.platform or metadata.arch != artifact.arch:
        return GalleryDlUpdateStatus(
            False,
            "metadata_invalid",
            current_release_tag=metadata.releaseTag,
            update_available=None,
            message="当前 Managed gallery-dl 的来源元数据平台/架构与本机可信 artifact 不一致。",
            **common,
        )

    if metadata.releaseTag == available.release_tag:
        same_identity = (
            metadata.sha256 == artifact.sha256
            and metadata.assetName == available.asset_name
            and metadata.artifactVersion == artifact.version
            and metadata.binaryVersion == current_version
        )
        if not same_identity:
            return GalleryDlUpdateStatus(
                False,
                "integrity_changed",
                current_release_tag=metadata.releaseTag,
                update_available=None,
                message=(
                    f"gallery-dl 发布 {available.release_tag} 与当前记录标签相同，但资产身份或 SHA-256 已变化。"
                    "为安全起见不会把它视为普通更新。"
                ),
                **common,
            )
        return GalleryDlUpdateStatus(
            True,
            "current",
            current_release_tag=metadata.releaseTag,
            update_available=False,
            message=f"当前 Managed gallery-dl 已是可信 PyPI 最新版本 {artifact.version}。",
            **common,
        )

    current_time = _timestamp(metadata.publishedAt)
    available_time = _timestamp(available.published_at)
    if current_time is None or available_time is None:
        return GalleryDlUpdateStatus(
            True,
            "unknown_current",
            current_release_tag=metadata.releaseTag,
            update_available=None,
            message="发现不同的 gallery-dl 发布，但无法可靠解析发布时间，因此不猜测更新顺序。",
            **common,
        )

    if available_time > current_time:
        return GalleryDlUpdateStatus(
            True,
            "update_available",
            current_release_tag=metadata.releaseTag,
            update_available=True,
            message=(
                f"发现 gallery-dl 更新：当前 {current_version or metadata.binaryVersion}，"
                f"可用 {artifact.version}。安装仍需你手动确认。"
            ),
            **common,
        )

    if available_time < current_time:
        return GalleryDlUpdateStatus(
            True,
            "ahead",
            current_release_tag=metadata.releaseTag,
            update_available=False,
            message="当前 Managed gallery-dl 的记录发布时间晚于 provider 当前返回版本，不建议降级。",
            **common,
        )

    return GalleryDlUpdateStatus(
        False,
        "integrity_changed",
        current_release_tag=metadata.releaseTag,
        update_available=None,
        message="当前安装与 provider 返回的发布标签不同但发布时间相同，已停止自动比较。",
        **common,
    )


def run_gallery_dl_update_status_self_test() -> None:
    import tempfile

    root = Path(tempfile.gettempdir()) / "galaxy-gallery-dl-update-status-missing"

    class Engine:
        @staticmethod
        def tools_dir() -> Path:
            return root

    status = check_gallery_dl_update(
        Engine,
        resolver=lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert status.ok is False
    assert status.state == "error"
    assert status.current_source == "unavailable"
