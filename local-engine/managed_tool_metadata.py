from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

MANAGED_TOOL_METADATA_FILENAME = ".galaxy-tool.json"
MANAGED_TOOL_METADATA_SCHEMA = 1
MAX_MANAGED_TOOL_METADATA_BYTES = 32 * 1024


class ManagedToolMetadataError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManagedToolMetadata:
    schemaVersion: int
    tool: str
    source: str
    platform: str
    arch: str
    binaryVersion: str
    installedAt: str
    providerId: str | None = None
    artifactVersion: str | None = None
    releaseTag: str | None = None
    publishedAt: str | None = None
    sha256: str | None = None
    assetName: str | None = None
    releaseUrl: str | None = None
    provenanceUrl: str | None = None


def _text(value: object, *, field: str, required: bool = True, max_length: int = 2048) -> str | None:
    if value is None:
        if required:
            raise ManagedToolMetadataError(f"managed tool metadata field is required: {field}")
        return None
    text = str(value).strip()
    if not text:
        if required:
            raise ManagedToolMetadataError(f"managed tool metadata field is empty: {field}")
        return None
    if len(text) > max_length:
        raise ManagedToolMetadataError(f"managed tool metadata field is too long: {field}")
    if any(ord(character) < 32 for character in text):
        raise ManagedToolMetadataError(f"managed tool metadata field contains control characters: {field}")
    return text


def validate_managed_tool_metadata(metadata: ManagedToolMetadata, *, expected_tool: str | None = None) -> ManagedToolMetadata:
    if metadata.schemaVersion != MANAGED_TOOL_METADATA_SCHEMA:
        raise ManagedToolMetadataError(f"unsupported managed tool metadata schema: {metadata.schemaVersion}")
    tool = _text(metadata.tool, field="tool", max_length=128)
    if expected_tool is not None and tool != expected_tool:
        raise ManagedToolMetadataError(f"managed tool metadata tool mismatch: expected {expected_tool}, got {tool}")
    source = _text(metadata.source, field="source", max_length=64)
    if source not in {"online", "bundled-seed"}:
        raise ManagedToolMetadataError(f"unsupported managed tool metadata source: {source}")
    _text(metadata.platform, field="platform", max_length=64)
    _text(metadata.arch, field="arch", max_length=64)
    _text(metadata.binaryVersion, field="binaryVersion", max_length=512)
    _text(metadata.installedAt, field="installedAt", max_length=128)

    if source == "online":
        for field_name in (
            "providerId",
            "artifactVersion",
            "releaseTag",
            "publishedAt",
            "sha256",
            "assetName",
            "releaseUrl",
            "provenanceUrl",
        ):
            _text(getattr(metadata, field_name), field=field_name, max_length=2048)
        digest = str(metadata.sha256 or "").lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ManagedToolMetadataError("managed tool metadata SHA-256 is malformed")
        asset_name = str(metadata.assetName or "")
        if "/" in asset_name or "\\" in asset_name or asset_name in {".", ".."}:
            raise ManagedToolMetadataError("managed tool metadata assetName must be a single file name")
    return metadata


def metadata_path(tool_root: Path) -> Path:
    return Path(tool_root) / MANAGED_TOOL_METADATA_FILENAME


def write_managed_tool_metadata(tool_root: Path, metadata: ManagedToolMetadata) -> Path:
    """Write provenance into a staged tool root before that root is promoted.

    Existing metadata is rejected rather than overwritten so an archive cannot
    smuggle its own provenance record into the managed-tool trust boundary.
    """
    validate_managed_tool_metadata(metadata, expected_tool=metadata.tool)
    root = Path(tool_root)
    if not root.is_dir() or root.is_symlink():
        raise ManagedToolMetadataError("managed tool metadata root must be a real directory")
    target = metadata_path(root)
    if target.exists() or target.is_symlink():
        raise ManagedToolMetadataError("managed tool archive already contains Galaxy provenance metadata")

    payload = json.dumps(asdict(metadata), ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if len(payload) > MAX_MANAGED_TOOL_METADATA_BYTES:
        raise ManagedToolMetadataError("managed tool metadata exceeds size limit")

    temporary = root / f".{MANAGED_TOOL_METADATA_FILENAME}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as output:
            output.write(payload)
            output.flush()
        temporary.replace(target)
        return target
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _from_payload(payload: object) -> ManagedToolMetadata:
    if not isinstance(payload, dict):
        raise ManagedToolMetadataError("managed tool metadata must be a JSON object")
    try:
        schema = int(payload.get("schemaVersion"))
    except (TypeError, ValueError) as exc:
        raise ManagedToolMetadataError("managed tool metadata schemaVersion is invalid") from exc
    metadata = ManagedToolMetadata(
        schemaVersion=schema,
        tool=str(payload.get("tool") or ""),
        source=str(payload.get("source") or ""),
        platform=str(payload.get("platform") or ""),
        arch=str(payload.get("arch") or ""),
        binaryVersion=str(payload.get("binaryVersion") or ""),
        installedAt=str(payload.get("installedAt") or ""),
        providerId=payload.get("providerId"),
        artifactVersion=payload.get("artifactVersion"),
        releaseTag=payload.get("releaseTag"),
        publishedAt=payload.get("publishedAt"),
        sha256=payload.get("sha256"),
        assetName=payload.get("assetName"),
        releaseUrl=payload.get("releaseUrl"),
        provenanceUrl=payload.get("provenanceUrl"),
    )
    return metadata


def read_managed_tool_metadata(tool_root: Path, *, expected_tool: str | None = None) -> ManagedToolMetadata | None:
    target = metadata_path(tool_root)
    if not target.exists():
        return None
    if target.is_symlink() or not target.is_file():
        raise ManagedToolMetadataError("managed tool metadata path is not a regular file")
    size = target.stat().st_size
    if size <= 0 or size > MAX_MANAGED_TOOL_METADATA_BYTES:
        raise ManagedToolMetadataError("managed tool metadata file size is invalid")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManagedToolMetadataError(f"could not read managed tool metadata: {exc}") from exc
    metadata = _from_payload(payload)
    return validate_managed_tool_metadata(metadata, expected_tool=expected_tool)


def run_managed_tool_metadata_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        root.mkdir(exist_ok=True)
        metadata = ManagedToolMetadata(
            schemaVersion=MANAGED_TOOL_METADATA_SCHEMA,
            tool="ffmpeg",
            source="online",
            platform="windows",
            arch="x86-64",
            binaryVersion="ffmpeg version test",
            installedAt="2026-09-02T00:00:00Z",
            providerId="btbn-ffmpeg-builds",
            artifactVersion="N-126313-g1ae4048218",
            releaseTag="autobuild-2026-09-01-13-13",
            publishedAt="2026-09-01T13:36:08Z",
            sha256="a" * 64,
            assetName="ffmpeg-N-126313-g1ae4048218-win64-gpl.zip",
            releaseUrl="https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-09-01-13-13",
            provenanceUrl="https://ffmpeg.org/download.html",
        )
        write_managed_tool_metadata(root, metadata)
        loaded = read_managed_tool_metadata(root, expected_tool="ffmpeg")
        assert loaded == metadata
