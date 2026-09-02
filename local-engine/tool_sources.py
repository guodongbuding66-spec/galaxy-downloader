from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from tool_artifacts import ToolArtifact, ToolArtifactError, runtime_arch, runtime_platform, validate_artifact

BTBN_PROVIDER_ID = "btbn-ffmpeg-builds"
BTBN_RELEASES_API = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases?per_page=10"
BTBN_RELEASES_PAGE = "https://github.com/BtbN/FFmpeg-Builds/releases"
FFMPEG_PROVIDER_PROVENANCE = "https://ffmpeg.org/download.html"
MAX_PROVIDER_RESPONSE_BYTES = 5 * 1024 * 1024

_TARGETS: dict[tuple[str, str], tuple[str, str]] = {
    ("windows", "x86-64"): ("win64", "zip"),
    ("windows", "arm64"): ("winarm64", "zip"),
    ("linux", "x86-64"): ("linux64", "tar.xz"),
    ("linux", "arm64"): ("linuxarm64", "tar.xz"),
}


class ToolSourceError(ToolArtifactError):
    pass


@dataclass(frozen=True)
class ResolvedToolSource:
    provider_id: str
    artifact: ToolArtifact
    release_tag: str
    published_at: str
    release_url: str
    asset_name: str
    provenance_url: str


def _validate_provider_api_url(url: str) -> None:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or parsed.hostname != "api.github.com":
        raise ToolSourceError("trusted BtbN metadata must come from api.github.com over HTTPS")
    if parsed.path != "/repos/BtbN/FFmpeg-Builds/releases":
        raise ToolSourceError("unexpected BtbN provider API path")


def _read_json_response(response: BinaryIO, *, expected_url: str) -> Any:
    getter = getattr(response, "geturl", None)
    final_url = str(getter() if callable(getter) else expected_url)
    _validate_provider_api_url(final_url)
    data = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
    if len(data) > MAX_PROVIDER_RESPONSE_BYTES:
        raise ToolSourceError("BtbN provider metadata exceeds size limit")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolSourceError(f"invalid BtbN provider metadata: {exc}") from exc


def fetch_btbn_releases(
    *,
    opener: Callable[..., BinaryIO] = urlopen,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    _validate_provider_api_url(BTBN_RELEASES_API)
    request = Request(
        BTBN_RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "GalaxyLocalEngine/trusted-tool-source",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        response = opener(request, timeout=max(1.0, float(timeout)))
        with response:
            payload = _read_json_response(response, expected_url=BTBN_RELEASES_API)
    except ToolSourceError:
        raise
    except Exception as exc:
        raise ToolSourceError(f"could not read BtbN release metadata: {exc}") from exc
    if not isinstance(payload, list):
        raise ToolSourceError("BtbN release metadata must be a JSON array")
    return [item for item in payload if isinstance(item, dict)]


def _immutable_release(releases: list[dict[str, Any]]) -> dict[str, Any]:
    for release in releases:
        tag = str(release.get("tag_name") or "")
        if not tag.startswith("autobuild-"):
            continue
        if bool(release.get("draft")) or bool(release.get("prerelease")):
            continue
        release_url = str(release.get("html_url") or "")
        expected_release_url = f"https://github.com/BtbN/FFmpeg-Builds/releases/tag/{quote(tag, safe='-') }"
        if release_url != expected_release_url:
            continue
        assets = release.get("assets")
        if not isinstance(assets, list):
            continue
        return release
    raise ToolSourceError("no immutable BtbN autobuild release was available")


def _asset_pattern(target: str, archive: str) -> re.Pattern[str]:
    extension = re.escape(archive)
    return re.compile(rf"^ffmpeg-N-[0-9]+-g[0-9a-f]+-{re.escape(target)}-gpl\.{extension}$")


def _asset_for_release(release: dict[str, Any], *, target: str, archive: str) -> dict[str, Any]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ToolSourceError("BtbN release assets are missing")
    pattern = _asset_pattern(target, archive)
    matches = [asset for asset in assets if isinstance(asset, dict) and pattern.fullmatch(str(asset.get("name") or ""))]
    if len(matches) != 1:
        raise ToolSourceError(f"expected exactly one BtbN {target} GPL static asset, found {len(matches)}")
    return matches[0]


def _digest(asset: dict[str, Any]) -> str:
    value = str(asset.get("digest") or "").strip().lower()
    if not value.startswith("sha256:"):
        raise ToolSourceError("BtbN asset metadata did not include a SHA-256 digest")
    digest = value.split(":", 1)[1]
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ToolSourceError("BtbN asset SHA-256 digest is malformed")
    return digest


def _asset_download_url(release_tag: str, asset_name: str, asset: dict[str, Any]) -> str:
    url = str(asset.get("browser_download_url") or "")
    expected = (
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
        f"{quote(release_tag, safe='-')}/{quote(asset_name, safe='.-')}"
    )
    if url != expected:
        raise ToolSourceError("BtbN asset download URL did not match the pinned repository/release")
    return url


def resolve_btbn_ffmpeg_source(
    *,
    platform_name: str | None = None,
    arch: str | None = None,
    releases: list[dict[str, Any]] | None = None,
    opener: Callable[..., BinaryIO] = urlopen,
    timeout: float = 15.0,
) -> ResolvedToolSource:
    selected_platform = platform_name or runtime_platform()
    selected_arch = arch or runtime_arch()
    target_info = _TARGETS.get((selected_platform, selected_arch))
    if target_info is None:
        raise ToolSourceError(f"BtbN does not provide a trusted build for {selected_platform}/{selected_arch}")
    target, archive = target_info
    release = _immutable_release(releases if releases is not None else fetch_btbn_releases(opener=opener, timeout=timeout))
    release_tag = str(release["tag_name"])
    release_url = str(release["html_url"])
    published_at = str(release.get("published_at") or "")
    if not published_at:
        raise ToolSourceError("BtbN release publication time is missing")

    asset = _asset_for_release(release, target=target, archive=archive)
    asset_name = str(asset["name"])
    digest = _digest(asset)
    download_url = _asset_download_url(release_tag, asset_name, asset)
    build_match = re.match(r"^ffmpeg-(N-[0-9]+-g[0-9a-f]+)-", asset_name)
    if build_match is None:
        raise ToolSourceError("could not derive BtbN FFmpeg build version")

    artifact = ToolArtifact(
        tool="ffmpeg",
        version=build_match.group(1),
        platform=selected_platform,
        arch=selected_arch,
        url=download_url,
        sha256=digest,
        archive=archive,
    )
    validate_artifact(artifact, platform_name=selected_platform, arch=selected_arch)
    return ResolvedToolSource(
        provider_id=BTBN_PROVIDER_ID,
        artifact=artifact,
        release_tag=release_tag,
        published_at=published_at,
        release_url=release_url,
        asset_name=asset_name,
        provenance_url=FFMPEG_PROVIDER_PROVENANCE,
    )


def trusted_ffmpeg_source_available(*, platform_name: str | None = None, arch: str | None = None) -> bool:
    return ((platform_name or runtime_platform()), (arch or runtime_arch())) in _TARGETS


def run_tool_sources_self_test() -> None:
    digest = "a" * 64
    release_tag = "autobuild-2026-09-01-13-13"
    asset_name = "ffmpeg-N-126313-g1ae4048218-win64-gpl.zip"
    releases = [
        {
            "tag_name": "latest",
            "draft": False,
            "prerelease": False,
            "html_url": "https://github.com/BtbN/FFmpeg-Builds/releases/tag/latest",
            "assets": [],
        },
        {
            "tag_name": release_tag,
            "draft": False,
            "prerelease": False,
            "published_at": "2026-09-01T13:36:08Z",
            "html_url": f"https://github.com/BtbN/FFmpeg-Builds/releases/tag/{release_tag}",
            "assets": [
                {
                    "name": asset_name,
                    "digest": f"sha256:{digest}",
                    "browser_download_url": (
                        f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{release_tag}/{asset_name}"
                    ),
                }
            ],
        },
    ]
    resolved = resolve_btbn_ffmpeg_source(platform_name="windows", arch="x86-64", releases=releases)
    assert resolved.provider_id == BTBN_PROVIDER_ID
    assert resolved.release_tag == release_tag
    assert resolved.artifact.version == "N-126313-g1ae4048218"
    assert resolved.artifact.sha256 == digest
    assert resolved.artifact.archive == "zip"
    assert trusted_ffmpeg_source_available(platform_name="windows", arch="x86-64") is True
    assert trusted_ffmpeg_source_available(platform_name="macos", arch="arm64") is False
