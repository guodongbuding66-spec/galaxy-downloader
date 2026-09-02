from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from managed_tool_metadata import ManagedToolMetadataError, read_managed_tool_metadata
from tool_artifacts import runtime_arch, runtime_platform


@dataclass(frozen=True)
class ManagedToolSpec:
    tool: str
    display_name: str
    required: bool
    capabilities: tuple[str, ...]
    supports_managed_copy: bool
    supports_online_install: bool
    supports_update_check: bool


@dataclass(frozen=True)
class ManagedToolObservation:
    ready: bool
    source: str
    version: str | None
    managed_root: Path | None = None


@dataclass(frozen=True)
class ManagedToolHealth:
    tool: str
    display_name: str
    required: bool
    ready: bool
    source: str
    version: str | None
    managed: bool
    state: str
    health: str
    metadata_state: str
    provider_id: str | None
    artifact_version: str | None
    release_tag: str | None
    installed_at: str | None
    supports_managed_copy: bool
    supports_online_install: bool
    supports_update_check: bool
    capabilities: tuple[str, ...]
    message: str


DEFAULT_MANAGED_TOOL_SPECS: tuple[ManagedToolSpec, ...] = (
    ManagedToolSpec(
        tool="yt-dlp",
        display_name="yt-dlp",
        required=True,
        capabilities=("extract", "download", "metadata"),
        supports_managed_copy=True,
        supports_online_install=False,
        supports_update_check=False,
    ),
    ManagedToolSpec(
        tool="ffmpeg",
        display_name="FFmpeg",
        required=True,
        capabilities=("merge", "transcode", "probe", "media-cleanup"),
        supports_managed_copy=True,
        supports_online_install=True,
        supports_update_check=True,
    ),
)


def registered_tool_specs() -> tuple[ManagedToolSpec, ...]:
    return DEFAULT_MANAGED_TOOL_SPECS


def _health(
    spec: ManagedToolSpec,
    observation: ManagedToolObservation,
    *,
    state: str,
    health: str,
    metadata_state: str,
    message: str,
    provider_id: str | None = None,
    artifact_version: str | None = None,
    release_tag: str | None = None,
    installed_at: str | None = None,
) -> ManagedToolHealth:
    return ManagedToolHealth(
        tool=spec.tool,
        display_name=spec.display_name,
        required=spec.required,
        ready=bool(observation.ready),
        source=str(observation.source or "unavailable"),
        version=observation.version,
        managed=str(observation.source or "") == "managed",
        state=state,
        health=health,
        metadata_state=metadata_state,
        provider_id=provider_id,
        artifact_version=artifact_version,
        release_tag=release_tag,
        installed_at=installed_at,
        supports_managed_copy=spec.supports_managed_copy,
        supports_online_install=spec.supports_online_install,
        supports_update_check=spec.supports_update_check,
        capabilities=spec.capabilities,
        message=message,
    )


def evaluate_tool_health(spec: ManagedToolSpec, observation: ManagedToolObservation) -> ManagedToolHealth:
    """Evaluate one dependency using local state only.

    This function never resolves provider metadata, downloads artifacts or mutates
    the managed-tool directory. It is safe to call from startup/status refreshes.
    """
    source = str(observation.source or "unavailable")
    if not observation.ready:
        return _health(
            spec,
            observation,
            state="missing",
            health="error" if spec.required else "warning",
            metadata_state="not-applicable",
            message=f"{spec.display_name} is not available.",
        )

    if source != "managed":
        if source not in {"bundled", "system"}:
            return _health(
                spec,
                observation,
                state="source-unknown",
                health="warning",
                metadata_state="not-applicable",
                message=f"{spec.display_name} is usable but its local source is not recognized.",
            )
        return _health(
            spec,
            observation,
            state=source,
            health="ok",
            metadata_state="not-managed",
            message=f"{spec.display_name} is ready from the {source} source.",
        )

    root = Path(observation.managed_root) if observation.managed_root is not None else None
    if root is None or not root.is_dir() or root.is_symlink():
        return _health(
            spec,
            observation,
            state="managed-root-invalid",
            health="warning",
            metadata_state="unavailable",
            message=f"{spec.display_name} is marked managed but its managed root cannot be inspected safely.",
        )

    try:
        metadata = read_managed_tool_metadata(root, expected_tool=spec.tool)
    except ManagedToolMetadataError as exc:
        return _health(
            spec,
            observation,
            state="metadata-invalid",
            health="warning",
            metadata_state="invalid",
            message=f"{spec.display_name} is usable, but its Galaxy provenance metadata is invalid: {exc}",
        )

    if metadata is None:
        return _health(
            spec,
            observation,
            state="managed-untracked",
            health="warning",
            metadata_state="missing",
            message=f"{spec.display_name} is usable as a managed tool but has no Galaxy provenance record.",
        )

    if metadata.platform != runtime_platform() or metadata.arch != runtime_arch():
        return _health(
            spec,
            observation,
            state="platform-mismatch",
            health="warning",
            metadata_state="valid",
            provider_id=metadata.providerId,
            artifact_version=metadata.artifactVersion,
            release_tag=metadata.releaseTag,
            installed_at=metadata.installedAt,
            message=(
                f"{spec.display_name} provenance targets {metadata.platform}/{metadata.arch}, "
                f"but this runtime is {runtime_platform()}/{runtime_arch()}."
            ),
        )

    observed_version = str(observation.version or "").strip()
    recorded_version = str(metadata.binaryVersion or "").strip()
    if observed_version and recorded_version and observed_version != recorded_version:
        return _health(
            spec,
            observation,
            state="binary-drift",
            health="warning",
            metadata_state="valid",
            provider_id=metadata.providerId,
            artifact_version=metadata.artifactVersion,
            release_tag=metadata.releaseTag,
            installed_at=metadata.installedAt,
            message=(
                f"{spec.display_name} is usable, but its observed binary version no longer matches "
                "the version recorded at managed-tool installation time."
            ),
        )

    state = "managed-online" if metadata.source == "online" else "managed-seed"
    return _health(
        spec,
        observation,
        state=state,
        health="ok",
        metadata_state="valid",
        provider_id=metadata.providerId,
        artifact_version=metadata.artifactVersion,
        release_tag=metadata.releaseTag,
        installed_at=metadata.installedAt,
        message=f"{spec.display_name} managed-tool state is healthy.",
    )


def public_tool_health(status: ManagedToolHealth) -> dict[str, object]:
    """Return bridge-safe health data without filesystem paths."""
    payload = asdict(status)
    payload["capabilities"] = list(status.capabilities)
    return {
        "tool": payload["tool"],
        "displayName": payload["display_name"],
        "required": payload["required"],
        "ready": payload["ready"],
        "source": payload["source"],
        "version": payload["version"],
        "managed": payload["managed"],
        "state": payload["state"],
        "health": payload["health"],
        "metadataState": payload["metadata_state"],
        "providerId": payload["provider_id"],
        "artifactVersion": payload["artifact_version"],
        "releaseTag": payload["release_tag"],
        "installedAt": payload["installed_at"],
        "supportsManagedCopy": payload["supports_managed_copy"],
        "supportsOnlineInstall": payload["supports_online_install"],
        "supportsUpdateCheck": payload["supports_update_check"],
        "capabilities": payload["capabilities"],
        "message": payload["message"],
    }


def registry_summary(statuses: Iterable[ManagedToolHealth]) -> dict[str, object]:
    values = tuple(statuses)
    required = tuple(item for item in values if item.required)
    return {
        "dependenciesReady": all(item.ready and item.health != "error" for item in required),
        "dependencyWarningCount": sum(1 for item in values if item.health == "warning"),
        "dependencyErrorCount": sum(1 for item in values if item.health == "error"),
        "managedToolRegistry": [public_tool_health(item) for item in values],
    }


def run_managed_tool_registry_self_test() -> None:
    missing = evaluate_tool_health(
        DEFAULT_MANAGED_TOOL_SPECS[0],
        ManagedToolObservation(False, "unavailable", None),
    )
    assert missing.state == "missing"
    assert missing.health == "error"
    summary = registry_summary((missing,))
    assert summary["dependenciesReady"] is False
    public = summary["managedToolRegistry"][0]
    assert "path" not in " ".join(public.keys()).lower()
