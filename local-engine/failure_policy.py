from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from recovery_policy import smart_retry_recipe

_URL_RE = re.compile(r"https?://[^\s<>\]\[\)\(\"']+", re.IGNORECASE)
_SECRET_RE = re.compile(
    r"(?i)\b(token|authorization|cookie|session|password|passwd|secret|auth)\s*[:=]\s*[^\s,;]+"
)

FAILURE_DEFINITIONS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "rate-limit",
        "源站限流",
        "源站正在限制请求频率。智能重试会降低并发到 1、启用弱网增强并将速度限制为 5 Mbps。",
        (
            "429",
            "too many requests",
            "rate limit",
            "ratelimit",
            "throttl",
            "请求过于频繁",
            "访问频率",
        ),
    ),
    (
        "browser-cookie",
        "浏览器 Cookie 不可用",
        "浏览器 Cookie 数据库可能被占用或无法解密。完全退出对应浏览器后再重试；不要反复自动重试。",
        (
            "cookie database",
            "cookies-from-browser",
            "failed to decrypt",
            "dpapi",
            "browser cookie",
            "cookie 数据库",
            "无法读取 edge",
            "无法读取 chrome",
            "无法读取 firefox",
            "浏览器正在占用",
        ),
    ),
    (
        "auth",
        "需要登录或验证",
        "源站需要账号登录、验证码或权限验证。先在浏览器完成登录，再选择对应浏览器登录状态后重试。",
        (
            "auth_required",
            "authentication required",
            "login required",
            "sign in",
            "please log in",
            "private video",
            "members-only",
            "confirm you're not a bot",
            "需要登录",
            "尚未检测到有效登录",
            "登录状态",
            "验证码",
        ),
    ),
    (
        "disk",
        "磁盘空间不足",
        "下载目录所在磁盘空间不足。释放空间或移动整个便携目录后再重试。",
        (
            "no space left",
            "disk full",
            "errno 28",
            "not enough space",
            "磁盘空间不足",
            "空间不足",
        ),
    ),
    (
        "geo",
        "区域限制",
        "内容可能受地区、网络出口或账号区域限制。改变本机网络/账号环境后再试，自动重试通常无效。",
        (
            "not available in your country",
            "not available in your region",
            "geo restricted",
            "geo-restricted",
            "geographic restriction",
            "地区限制",
            "区域限制",
        ),
    ),
    (
        "unavailable",
        "内容不可用",
        "源内容可能已删除、下架、仅好友/订阅可见或被版权限制。确认源页面本身仍可正常播放。",
        (
            "video unavailable",
            "content unavailable",
            "this video has been removed",
            "copyright",
            "deleted",
            "removed by",
            "内容不可用",
            "视频不存在",
            "已删除",
            "已下架",
        ),
    ),
    (
        "processing",
        "后处理失败",
        "媒体已进入 FFmpeg/合并/字幕后处理阶段。检查磁盘空间、文件占用和 FFmpeg 后再重新下载。",
        (
            "ffmpeg",
            "postprocess",
            "post-process",
            "conversion failed",
            "merge failed",
            "unable to mux",
            "后处理",
            "合并失败",
            "转换失败",
        ),
    ),
    (
        "extractor",
        "解析器失效",
        "源站页面或接口可能已经变化。先检查 Local Engine/yt-dlp 稳定版更新；单纯重复下载通常不会解决。",
        (
            "unsupported url",
            "unable to extract",
            "extractor error",
            "no video formats found",
            "requested format is not available",
            "nsig extraction",
            "signature extraction",
            "解析失败",
            "无法提取",
            "没有可用格式",
        ),
    ),
    (
        "network",
        "网络连接异常",
        "连接超时、重置或临时 5xx 错误。智能重试会启用弱网增强并把并发分片降低到 2。",
        (
            "timed out",
            "timeout",
            "connection reset",
            "connection aborted",
            "connection refused",
            "network is unreachable",
            "temporary failure",
            "remote end closed",
            "http error 500",
            "http error 502",
            "http error 503",
            "http error 504",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
            "连接超时",
            "连接被重置",
            "网络不可达",
            "临时网络",
        ),
    ),
    (
        "access",
        "源站拒绝访问",
        "源站返回 403/Access Denied。可能需要登录状态、验证码或稍后重试；先打开原页面确认是否可正常访问。",
        (
            "http error 403",
            "403 forbidden",
            "access denied",
            "forbidden",
            "拒绝访问",
        ),
    ),
)


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return "[redacted-url]"
        host = parsed.hostname
        try:
            if parsed.port:
                host = f"{host}:{parsed.port}"
        except ValueError:
            pass
        return urlunsplit((parsed.scheme.lower(), host, parsed.path or "/", "", ""))
    except ValueError:
        return "[redacted-url]"


def sanitize_failure_detail(value: object, limit: int = 360) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    if not text:
        return ""
    text = _URL_RE.sub(lambda match: _redact_url(match.group(0)), text)
    text = _SECRET_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    return text[: max(40, min(int(limit), 1200))]


def classify_failure(detail: object, state: object = "failed") -> dict[str, Any]:
    normalized_state = str(state or "").strip().lower()
    if normalized_state == "cancelled":
        return {
            "category": "cancelled",
            "label": "用户取消",
            "advice": "任务由用户取消。可直接重新下载，不需要改变网络参数。",
            "smartRetryable": False,
        }
    if normalized_state != "failed":
        return {
            "category": "",
            "label": "",
            "advice": "",
            "smartRetryable": False,
        }

    text = sanitize_failure_detail(detail, 1200).lower()
    for category, label, advice, patterns in FAILURE_DEFINITIONS:
        if any(pattern.lower() in text for pattern in patterns):
            return {
                "category": category,
                "label": label,
                "advice": advice,
                "smartRetryable": smart_retry_recipe(category) is not None,
            }
    return {
        "category": "unknown",
        "label": "未知失败",
        "advice": "错误暂时无法归类。智能重试会使用弱网增强和 2 个并发分片；若再次失败，请查看诊断日志。",
        "smartRetryable": True,
    }


def smart_retry_payload(item: dict[str, Any]) -> dict[str, Any] | None:
    if str(item.get("state") or "").lower() != "failed":
        return None
    payload = dict(item.get("retryPayload") or {})
    if not str(payload.get("sourceUrl") or "").strip():
        return None

    classification = classify_failure(item.get("detail"), item.get("state"))
    recipe = smart_retry_recipe(classification["category"])
    if recipe is None:
        return None

    payload.update(recipe)
    payload["skipPreviouslyDownloaded"] = False
    title = str(item.get("fileName") or item.get("label") or item.get("sourceHost") or "失败任务")
    payload["displayTitle"] = f"智能重试 · {title}"[:120]
    return payload


def run_failure_policy_self_test() -> None:
    secret = (
        "ERROR HTTP 503 https://user:secret@example.com/watch?v=abc&token=hidden#frag "
        "authorization=BearerSecret"
    )
    safe = sanitize_failure_detail(secret)
    assert "hidden" not in safe
    assert "BearerSecret" not in safe
    assert "user:secret" not in safe
    assert "https://example.com/watch" in safe

    network = classify_failure("ERROR: HTTP Error 503: Service Unavailable")
    assert network["category"] == "network"
    assert network["smartRetryable"] is True
    limited = classify_failure("HTTP Error 429 Too Many Requests")
    assert limited["category"] == "rate-limit"
    assert limited["smartRetryable"] is True
    auth = classify_failure("Login required to view this private video")
    assert auth["category"] == "auth"
    assert auth["smartRetryable"] is False

    retry = smart_retry_payload(
        {
            "state": "failed",
            "detail": "connection reset by peer",
            "label": "demo",
            "retryPayload": {"sourceUrl": "https://example.com/video", "skipPreviouslyDownloaded": True},
        }
    )
    assert retry is not None
    assert retry["networkRetryProfile"] == "resilient"
    assert retry["concurrentFragments"] == 2
    assert retry["skipPreviouslyDownloaded"] is False
