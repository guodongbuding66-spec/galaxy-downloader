from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from url_policy import validated_public_http_url

BROWSERS = frozenset({"none", "edge", "chrome", "firefox", "brave"})
SUPPORTED_PROVIDER_IDS = frozenset({"udemy"})


class CourseProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class CourseProviderDescriptor:
    id: str
    name: str
    status: str
    requires_authorized_session: bool
    supports_subtitles: bool
    supports_attachments: bool
    drm_bypass_supported: bool

    def public_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        return {
            "id": payload["id"],
            "name": payload["name"],
            "status": payload["status"],
            "requiresAuthorizedSession": payload["requires_authorized_session"],
            "supportsSubtitles": payload["supports_subtitles"],
            "supportsAttachments": payload["supports_attachments"],
            "drmBypassSupported": payload["drm_bypass_supported"],
        }


_UDEMY_DESCRIPTOR = CourseProviderDescriptor(
    id="udemy",
    name="Udemy",
    status="foundation",
    requires_authorized_session=True,
    supports_subtitles=True,
    supports_attachments=True,
    drm_bypass_supported=False,
)


def list_course_providers() -> list[dict[str, Any]]:
    return [_UDEMY_DESCRIPTOR.public_payload()]


def _is_udemy_host(host: str) -> bool:
    clean = str(host or "").strip().lower().rstrip(".")
    return clean == "udemy.com" or clean.endswith(".udemy.com")


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
    raise CourseProviderError("暂不支持该课程平台；当前仅支持 Udemy")


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

    url = _validated_course_url(source_url)
    detected = _detect_provider_from_validated_url(url)
    provider_id = _clean_provider(provider, detected=detected)
    browser_id = _clean_browser(browser)

    if provider_id != "udemy":
        raise CourseProviderError("课程 Provider 尚未实现")

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
        "provider": provider_id,
        "sourceUrl": url,
        "requiresAuthorizedSession": True,
        "drmBypassSupported": False,
        "enginePayload": engine_payload,
        "warnings": warnings,
    }
