from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from url_policy import validated_public_http_url

BROWSERS = frozenset({"none", "edge", "chrome", "firefox", "brave"})
SUPPORTED_PROVIDER_IDS = frozenset({"udemy", "hotmart"})
_HOTMART_DOWNLOAD_UNAVAILABLE = "Hotmart 目前仅支持课程来源识别；授权下载适配器尚未实现"


class CourseProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class CourseProviderDescriptor:
    id: str
    name: str
    status: str
    requires_authorized_session: bool
    supports_browser_cookies: bool
    supports_subtitles: bool
    supports_attachments: bool
    download_available: bool
    download_unavailable_reason: str
    drm_bypass_supported: bool

    def public_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        return {
            "id": payload["id"],
            "name": payload["name"],
            "status": payload["status"],
            "requiresAuthorizedSession": payload["requires_authorized_session"],
            "supportsBrowserCookies": payload["supports_browser_cookies"],
            "supportsSubtitles": payload["supports_subtitles"],
            "supportsAttachments": payload["supports_attachments"],
            "downloadAvailable": payload["download_available"],
            "downloadUnavailableReason": payload["download_unavailable_reason"],
            "drmBypassSupported": payload["drm_bypass_supported"],
        }


_UDEMY_DESCRIPTOR = CourseProviderDescriptor(
    id="udemy",
    name="Udemy",
    status="foundation",
    requires_authorized_session=True,
    supports_browser_cookies=True,
    supports_subtitles=True,
    supports_attachments=True,
    download_available=True,
    download_unavailable_reason="",
    drm_bypass_supported=False,
)

_HOTMART_DESCRIPTOR = CourseProviderDescriptor(
    id="hotmart",
    name="Hotmart",
    status="discovery",
    requires_authorized_session=True,
    supports_browser_cookies=False,
    supports_subtitles=False,
    supports_attachments=False,
    download_available=False,
    download_unavailable_reason=_HOTMART_DOWNLOAD_UNAVAILABLE,
    drm_bypass_supported=False,
)

_PROVIDER_DESCRIPTORS = {
    _UDEMY_DESCRIPTOR.id: _UDEMY_DESCRIPTOR,
    _HOTMART_DESCRIPTOR.id: _HOTMART_DESCRIPTOR,
}


def list_course_providers() -> list[dict[str, Any]]:
    return [
        _UDEMY_DESCRIPTOR.public_payload(),
        _HOTMART_DESCRIPTOR.public_payload(),
    ]


def _is_udemy_host(host: str) -> bool:
    clean = str(host or "").strip().lower().rstrip(".")
    return clean == "udemy.com" or clean.endswith(".udemy.com")


def _is_hotmart_club_host(host: str) -> bool:
    clean = str(host or "").strip().lower().rstrip(".")
    suffix = ".club.hotmart.com"
    if not clean.endswith(suffix):
        return False
    club_subdomain = clean[: -len(suffix)].strip(".")
    return bool(club_subdomain)


def _validated_course_url(source_url: object) -> str:
    try:
        return validated_public_http_url(str(source_url or ""))
    except Exception as exc:
        raise CourseProviderError(str(exc)) from exc


def _detect_provider_from_validated_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if _is_udemy_host(host):
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2 or parts[0].lower() != "course" or not parts[1].strip():
            raise CourseProviderError("Udemy URL 必须指向 /course/<slug>/ 课程页面")
        return "udemy"
    if _is_hotmart_club_host(host):
        return "hotmart"
    if host == "club.hotmart.com":
        raise CourseProviderError("Hotmart Club URL 必须指向 <club>.club.hotmart.com 成员区")
    raise CourseProviderError("暂不支持该课程平台")


def detect_course_provider(source_url: object) -> str:
    return _detect_provider_from_validated_url(_validated_course_url(source_url))


def _clean_browser(value: object) -> str:
    browser = str(value or "none").strip().lower()
    if browser not in BROWSERS:
        raise CourseProviderError("浏览器 Cookie 来源无效")
    return browser


def _clean_provider(value: object, *, detected: str) -> str:
    requested = str(value or "auto").strip().lower()
    if requested in {"", "auto"}:
        return detected
    if requested not in SUPPORTED_PROVIDER_IDS:
        raise CourseProviderError("课程 Provider 无效")
    if requested != detected:
        raise CourseProviderError("课程 URL 与指定 Provider 不匹配")
    return requested


def resolve_course_provider(
    source_url: object,
    *,
    provider: object = "auto",
) -> dict[str, Any]:
    """Resolve provider identity and safe capabilities without constructing a download plan."""
    url = _validated_course_url(source_url)
    detected = _detect_provider_from_validated_url(url)
    provider_id = _clean_provider(provider, detected=detected)
    descriptor = _PROVIDER_DESCRIPTORS.get(provider_id)
    if descriptor is None:
        raise CourseProviderError("课程 Provider 尚未实现")
    public = descriptor.public_payload()
    return {
        "provider": provider_id,
        "providerName": public["name"],
        "sourceUrl": url,
        "status": public["status"],
        "requiresAuthorizedSession": public["requiresAuthorizedSession"],
        "supportsBrowserCookies": public["supportsBrowserCookies"],
        "supportsSubtitles": public["supportsSubtitles"],
        "supportsAttachments": public["supportsAttachments"],
        "downloadAvailable": public["downloadAvailable"],
        "downloadUnavailableReason": public["downloadUnavailableReason"],
        "drmBypassSupported": public["drmBypassSupported"],
    }


def build_course_provider_plan(
    source_url: object,
    *,
    provider: object = "auto",
    browser: object = "none",
    include_subtitles: object = True,
    include_attachments: object = True,
) -> dict[str, Any]:
    if not isinstance(include_subtitles, bool):
        raise CourseProviderError("includeSubtitles 必须是布尔值")
    if not isinstance(include_attachments, bool):
        raise CourseProviderError("includeAttachments 必须是布尔值")

    resolution = resolve_course_provider(source_url, provider=provider)
    provider_id = str(resolution["provider"])
    url = str(resolution["sourceUrl"])
    if not resolution["downloadAvailable"]:
        raise CourseProviderError(
            str(resolution.get("downloadUnavailableReason") or "课程 Provider 尚未实现")
        )
    if provider_id != "udemy":
        raise CourseProviderError("课程 Provider 尚未实现")

    browser_id = _clean_browser(browser)
    engine_payload = {
        "sourceUrl": url,
        "videoQuality": "best",
        "audioQuality": "best",
        "includeAudio": True,
        "includeSubtitle": include_subtitles,
        "subtitleMode": "both" if include_subtitles else "none",
        "includeCourseAttachments": include_attachments,
        "splitChapters": False,
        "browser": browser_id,
        "collectionMode": "all",
        "displayTitle": "Udemy 课程下载",
    }
    warnings: list[str] = []
    if browser_id == "none":
        warnings.append("付费或已报名课程通常需要选择已登录 Udemy 的浏览器 Cookie 来源")
    warnings.append("仅处理账号已获授权访问的课程；不提供 DRM 绕过")

    return {
        **resolution,
        "enginePayload": engine_payload,
        "warnings": warnings,
    }
