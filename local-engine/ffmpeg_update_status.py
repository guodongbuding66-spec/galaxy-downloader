from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ffmpeg_manager import bundled_ffmpeg_directory, existing_managed_ffmpeg, ffmpeg_version
from managed_tool_metadata import ManagedToolMetadata, ManagedToolMetadataError, read_managed_tool_metadata
from tool_sources import ResolvedToolSource, resolve_btbn_ffmpeg_source, trusted_ffmpeg_source_available


@dataclass(frozen=True)
class FfmpegUpdateStatus:
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
    managed_bin = existing_managed_ffmpeg(engine_module)
    if managed_bin is not None:
        version = ffmpeg_version(managed_bin)
        tool_root = Path(managed_bin).parent
        try:
            metadata = read_managed_tool_metadata(tool_root, expected_tool="ffmpeg")
            return "managed", version, tool_root, metadata, None
        except ManagedToolMetadataError as exc:
            return "managed", version, tool_root, None, str(exc)
    bundled = bundled_ffmpeg_directory(engine_module)
    if bundled is not None:
        return "bundled", ffmpeg_version(bundled), None, None, None
    return "unavailable", None, None, None, None


def check_ffmpeg_update(
    engine_module,
    *,
    resolver: Callable[[], ResolvedToolSource] = resolve_btbn_ffmpeg_source,
) -> FfmpegUpdateStatus:
    """Explicitly resolve the trusted FFmpeg source and compare release identity.

    This function is intentionally never called by local inventory refresh or
    startup. The caller decides when a network-backed provider check is wanted.
    """
    current_source, current_version, _tool_root, metadata, metadata_error = _current_state(engine_module)
    if not trusted_ffmpeg_source_available():
        return FfmpegUpdateStatus(
            True,
            "unsupported",
            current_source,
            current_version,
            metadata.releaseTag if metadata else None,
            None,
            None,
            None,
            None,
            "当前平台尚未配置经过审核的 FFmpeg 在线构建源。",
        )

    try:
        available = resolver()
    except Exception as exc:
        return FfmpegUpdateStatus(
            False,
            "error",
            current_source,
            current_version,
            metadata.releaseTag if metadata else None,
            None,
            None,
            None,
            None,
            f"检查 FFmpeg 更新失败：{exc}",
        )

    artifact = available.artifact
    if artifact.tool != "ffmpeg":
        return FfmpegUpdateStatus(
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
        return FfmpegUpdateStatus(
            True,
            "install_available",
            current_release_tag=None,
            update_available=True,
            message=(
                f"发现可安装的可信 FFmpeg 构建 {artifact.version}（{available.release_tag}）。"
                "当前没有在线来源的托管 FFmpeg；安装仍需你手动确认。"
            ),
            **common,
        )

    if metadata_error:
        return FfmpegUpdateStatus(
            False,
            "metadata_invalid",
            current_release_tag=None,
            update_available=None,
            message=(
                "当前托管 FFmpeg 的 Galaxy 来源元数据无效，无法安全比较发布身份。"
                f" 本地二进制不会被修改。详情：{metadata_error}"
            ),
            **common,
        )

    if metadata is None:
        return FfmpegUpdateStatus(
            True,
            "unknown_current",
            current_release_tag=None,
            update_available=None,
            message=(
                f"在线最新可信构建为 {artifact.version}（{available.release_tag}），但当前托管 FFmpeg 没有在线发布元数据，"
                "可能来自随包种子或旧版本，因此不猜测是否需要更新。"
            ),
            **common,
        )

    if metadata.source != "online" or metadata.providerId != available.provider_id:
        return FfmpegUpdateStatus(
            True,
            "unknown_current",
            current_release_tag=metadata.releaseTag,
            update_available=None,
            message=(
                f"在线最新可信构建为 {artifact.version}（{available.release_tag}），但当前托管 FFmpeg 来源"
                f" {metadata.source}/{metadata.providerId or 'unknown'} 无法与该 provider 精确比较。"
            ),
            **common,
        )

    if metadata.platform != artifact.platform or metadata.arch != artifact.arch:
        return FfmpegUpdateStatus(
            False,
            "metadata_invalid",
            current_release_tag=metadata.releaseTag,
            update_available=None,
            message="当前托管 FFmpeg 的来源元数据平台/架构与可信在线构建不一致，已停止自动比较。",
            **common,
        )

    if metadata.releaseTag == available.release_tag:
        same_identity = (
            metadata.sha256 == artifact.sha256
            and metadata.assetName == available.asset_name
            and metadata.artifactVersion == artifact.version
        )
        if not same_identity:
            return FfmpegUpdateStatus(
                False,
                "integrity_changed",
                current_release_tag=metadata.releaseTag,
                update_available=None,
                message=(
                    f"发布标签 {available.release_tag} 与当前安装相同，但资产身份/SHA-256 已发生变化。"
                    "为安全起见 Galaxy 不把它视为普通更新，也不会自动替换本地 FFmpeg。"
                ),
                **common,
            )
        return FfmpegUpdateStatus(
            True,
            "current",
            current_release_tag=metadata.releaseTag,
            update_available=False,
            message=f"当前 Managed FFmpeg 已是可信来源的最新构建 {artifact.version}（{available.release_tag}）。",
            **common,
        )

    current_time = _timestamp(metadata.publishedAt)
    available_time = _timestamp(available.published_at)
    if current_time is None or available_time is None:
        return FfmpegUpdateStatus(
            True,
            "unknown_current",
            current_release_tag=metadata.releaseTag,
            update_available=None,
            message=(
                f"发现不同的可信发布 {available.release_tag}，但无法可靠解析发布时序；"
                "Galaxy 不猜测它是否比当前版本更新。"
            ),
            **common,
        )

    if available_time > current_time:
        return FfmpegUpdateStatus(
            True,
            "update_available",
            current_release_tag=metadata.releaseTag,
            update_available=True,
            message=(
                f"发现 FFmpeg 更新：当前 {metadata.artifactVersion or metadata.binaryVersion}（{metadata.releaseTag}），"
                f"可用 {artifact.version}（{available.release_tag}）。安装仍需你手动确认。"
            ),
            **common,
        )

    if available_time < current_time:
        return FfmpegUpdateStatus(
            True,
            "ahead",
            current_release_tag=metadata.releaseTag,
            update_available=False,
            message=(
                f"当前 Managed FFmpeg 的记录发布时间晚于 provider 当前返回的构建（当前 {metadata.releaseTag}，"
                f"provider {available.release_tag}）。不会建议降级。"
            ),
            **common,
        )

    return FfmpegUpdateStatus(
        False,
        "integrity_changed",
        current_release_tag=metadata.releaseTag,
        update_available=None,
        message=(
            "当前安装与 provider 返回的发布标签不同，但发布时间相同，无法建立单调更新顺序。"
            "为安全起见已停止自动比较。"
        ),
        **common,
    )


def run_ffmpeg_update_status_self_test() -> None:
    import tempfile

    class Engine:
        @staticmethod
        def tools_dir() -> Path:
            return Path(tempfile.gettempdir()) / "galaxy-no-managed-tool"

    status = check_ffmpeg_update(Engine, resolver=lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    assert status.state in {"error", "unsupported"}
