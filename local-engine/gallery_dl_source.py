from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, BinaryIO, Callable
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from tool_artifacts import ToolArtifact, ToolArtifactError, runtime_arch, runtime_platform, validate_artifact

GALLERY_DL_PROVIDER_ID = "pypi-gallery-dl"
GALLERY_DL_METADATA_API = "https://pypi.org/pypi/gallery-dl/json"
GALLERY_DL_PROJECT_URL = "https://pypi.org/project/gallery-dl/"
GALLERY_DL_PROVENANCE_URL = "https://github.com/mikf/gallery-dl"
MAX_PROVIDER_RESPONSE_BYTES = 2 * 1024 * 1024
_STABLE_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){2,3}$")


class GalleryDlSourceError(ToolArtifactError):
    pass


@dataclass(frozen=True)
class ResolvedGalleryDlSource:
    provider_id: str
    artifact: ToolArtifact
    release_tag: str
    published_at: str
    release_url: str
    asset_name: str
    provenance_url: str


def _validate_metadata_url(url: str) -> None:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or parsed.hostname != "pypi.org":
        raise GalleryDlSourceError("gallery-dl metadata must come from pypi.org over HTTPS")
    if parsed.path != "/pypi/gallery-dl/json" or parsed.query or parsed.fragment:
        raise GalleryDlSourceError("unexpected gallery-dl PyPI metadata URL")


def _read_json_response(response: BinaryIO, *, expected_url: str) -> dict[str, Any]:
    getter = getattr(response, "geturl", None)
    final_url = str(getter() if callable(getter) else expected_url)
    _validate_metadata_url(final_url)
    data = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
    if len(data) > MAX_PROVIDER_RESPONSE_BYTES:
        raise GalleryDlSourceError("gallery-dl PyPI metadata exceeds size limit")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GalleryDlSourceError(f"invalid gallery-dl PyPI metadata: {exc}") from exc
    if not isinstance(payload, dict):
        raise GalleryDlSourceError("gallery-dl PyPI metadata must be a JSON object")
    return payload


def fetch_gallery_dl_metadata(
    *,
    opener: Callable[..., BinaryIO] = urlopen,
    timeout: float = 15.0,
) -> dict[str, Any]:
    _validate_metadata_url(GALLERY_DL_METADATA_API)
    request = Request(
        GALLERY_DL_METADATA_API,
        headers={
            "Accept": "application/json",
            "User-Agent": "GalaxyLocalEngine/trusted-tool-source",
        },
        method="GET",
    )
    try:
        response = opener(request, timeout=max(1.0, float(timeout)))
        with response:
            return _read_json_response(response, expected_url=GALLERY_DL_METADATA_API)
    except GalleryDlSourceError:
        raise
    except Exception as exc:
        raise GalleryDlSourceError(f"could not read gallery-dl PyPI metadata: {exc}") from exc


def _stable_version(payload: dict[str, Any]) -> str:
    info = payload.get("info")
    if not isinstance(info, dict):
        raise GalleryDlSourceError("gallery-dl PyPI metadata is missing project info")
    version = str(info.get("version") or "").strip()
    if not _STABLE_VERSION.fullmatch(version):
        raise GalleryDlSourceError("gallery-dl PyPI latest version is not a stable numeric release")
    return version


def _wheel_asset(payload: dict[str, Any], version: str) -> dict[str, Any]:
    expected_name = f"gallery_dl-{version}-py3-none-any.whl"
    urls = payload.get("urls")
    if not isinstance(urls, list):
        raise GalleryDlSourceError("gallery-dl PyPI metadata is missing release files")
    matches = []
    for item in urls:
        if not isinstance(item, dict):
            continue
        if str(item.get("filename") or "") != expected_name:
            continue
        if str(item.get("packagetype") or "") != "bdist_wheel":
            continue
        if bool(item.get("yanked")):
            continue
        matches.append(item)
    if len(matches) != 1:
        raise GalleryDlSourceError(f"expected exactly one gallery-dl universal wheel, found {len(matches)}")
    return matches[0]


def _digest(asset: dict[str, Any]) -> str:
    digests = asset.get("digests")
    value = str(digests.get("sha256") if isinstance(digests, dict) else "").strip().lower()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise GalleryDlSourceError("gallery-dl PyPI wheel SHA-256 digest is missing or malformed")
    return value


def _asset_url(asset: dict[str, Any], asset_name: str) -> str:
    url = str(asset.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "files.pythonhosted.org":
        raise GalleryDlSourceError("gallery-dl wheel must be hosted on files.pythonhosted.org over HTTPS")
    if parsed.username or parsed.password or parsed.query:
        raise GalleryDlSourceError("gallery-dl wheel URL contains unexpected credentials or query parameters")
    basename = PurePosixPath(parsed.path).name
    if basename != asset_name:
        raise GalleryDlSourceError("gallery-dl wheel URL file name does not match PyPI metadata")
    return url


def resolve_gallery_dl_source(
    *,
    platform_name: str | None = None,
    arch: str | None = None,
    metadata: dict[str, Any] | None = None,
    opener: Callable[..., BinaryIO] = urlopen,
    timeout: float = 15.0,
) -> ResolvedGalleryDlSource:
    selected_platform = platform_name or runtime_platform()
    selected_arch = arch or runtime_arch()
    payload = metadata if metadata is not None else fetch_gallery_dl_metadata(opener=opener, timeout=timeout)
    version = _stable_version(payload)
    asset = _wheel_asset(payload, version)
    asset_name = str(asset["filename"])
    published_at = str(asset.get("upload_time_iso_8601") or asset.get("upload_time") or "").strip()
    if not published_at:
        raise GalleryDlSourceError("gallery-dl PyPI wheel publication time is missing")
    artifact = ToolArtifact(
        tool="gallery-dl",
        version=version,
        platform=selected_platform,
        arch=selected_arch,
        url=_asset_url(asset, asset_name),
        sha256=_digest(asset),
        archive="zip",
    )
    validate_artifact(artifact, platform_name=selected_platform, arch=selected_arch)
    return ResolvedGalleryDlSource(
        provider_id=GALLERY_DL_PROVIDER_ID,
        artifact=artifact,
        release_tag=version,
        published_at=published_at,
        release_url=f"{GALLERY_DL_PROJECT_URL}{quote(version, safe='.')}/",
        asset_name=asset_name,
        provenance_url=GALLERY_DL_PROVENANCE_URL,
    )


def run_gallery_dl_source_self_test() -> None:
    version = "1.32.11"
    asset_name = f"gallery_dl-{version}-py3-none-any.whl"
    digest = "a" * 64
    payload = {
        "info": {"version": version},
        "urls": [
            {
                "filename": asset_name,
                "packagetype": "bdist_wheel",
                "yanked": False,
                "url": f"https://files.pythonhosted.org/packages/aa/bb/{asset_name}",
                "digests": {"sha256": digest},
                "upload_time_iso_8601": "2026-09-04T10:00:00Z",
            }
        ],
    }
    resolved = resolve_gallery_dl_source(platform_name="windows", arch="x86-64", metadata=payload)
    assert resolved.provider_id == GALLERY_DL_PROVIDER_ID
    assert resolved.artifact.tool == "gallery-dl"
    assert resolved.artifact.version == version
    assert resolved.artifact.archive == "zip"
    assert resolved.artifact.sha256 == digest
    assert resolved.asset_name == asset_name

    bad = dict(payload)
    bad["info"] = {"version": "1.32.12.dev1"}
    try:
        resolve_gallery_dl_source(platform_name="windows", arch="x86-64", metadata=bad)
    except GalleryDlSourceError:
        pass
    else:
        raise AssertionError("prerelease gallery-dl version was accepted")
