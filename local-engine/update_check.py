from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.request import Request, urlopen

LATEST_RELEASE_API = "https://api.github.com/repos/guodongbuding66-spec/galaxy-downloader/releases/latest"
RELEASES_PAGE = "https://github.com/guodongbuding66-spec/galaxy-downloader/releases"
TAG_PREFIX = "local-engine-v"
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str | None
    release_url: str
    update_available: bool
    error: str | None = None


def _parts(value: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.fullmatch(value.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_newer_version(latest: str, current: str) -> bool:
    latest_parts = _parts(latest)
    current_parts = _parts(current)
    if latest_parts is None or current_parts is None:
        return False
    return latest_parts > current_parts


def check_latest_stable(current_version: str, timeout: float = 5.0) -> UpdateInfo:
    """Read GitHub's latest stable release without changing any local files.

    This function is intentionally read-only. The UI only calls it after the
    user presses "Check for updates" and can offer to open the release page; it
    never replaces the running executable or installs anything silently.
    """
    request = Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"GalaxyLocalEngine/{current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed GitHub endpoint
            payload = json.loads(response.read(512 * 1024).decode("utf-8"))
        tag = str(payload.get("tag_name") or "").strip()
        html_url = str(payload.get("html_url") or RELEASES_PAGE).strip() or RELEASES_PAGE
        latest = tag[len(TAG_PREFIX):] if tag.startswith(TAG_PREFIX) else None
        if latest is None or _parts(latest) is None:
            return UpdateInfo(
                current_version=current_version,
                latest_version=None,
                release_url=html_url,
                update_available=False,
                error="Latest GitHub release is not a Galaxy Local Engine release.",
            )
        return UpdateInfo(
            current_version=current_version,
            latest_version=latest,
            release_url=html_url,
            update_available=is_newer_version(latest, current_version),
        )
    except Exception as exc:  # noqa: BLE001 - UI needs a compact network diagnostic
        return UpdateInfo(
            current_version=current_version,
            latest_version=None,
            release_url=RELEASES_PAGE,
            update_available=False,
            error=str(exc),
        )
