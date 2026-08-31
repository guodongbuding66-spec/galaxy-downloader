from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import web_document as base


SOCIAL_POST_PLATFORMS = {
    "douyin",
    "instagram",
    "tiktok",
    "x",
    "reddit",
    "pinterest",
    "threads",
    "tumblr",
    "weibo",
    "telegram",
}

_EXTRA_EXTENSIONLESS_IMAGE_HOSTS = (
    "fbcdn.net",
    "cdninstagram.com",
    "twimg.com",
    "redd.it",
    "pinimg.com",
)
base.EXTENSIONLESS_IMAGE_HOSTS = tuple(dict.fromkeys(
    (*base.EXTENSIONLESS_IMAGE_HOSTS, *_EXTRA_EXTENSIONLESS_IMAGE_HOSTS)
))

_original_looks_like_image = base._looks_like_image


def _looks_like_image(url: str, key: str = "") -> bool:
    # CDN domains such as twimg.com serve both photos and MP4 clips. A known
    # video extension must win before extensionless-host heuristics classify the
    # URL as an image.
    if base.VIDEO_EXT_RE.search(url):
        return False
    return _original_looks_like_image(url, key)


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith(f".{suffix}")


def should_try_web_document(source_url: str) -> bool:
    try:
        parsed = urlparse(source_url)
    except ValueError:
        return False

    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path or "/"

    # Keep Xiaohongshu's dedicated resolver authoritative; it already
    # distinguishes video/image notes and returns caption + image arrays.
    if _host_matches(host, "xiaohongshu.com") or host == "xhslink.com":
        return False

    if _host_matches(host, "douyin.com"):
        return re.search(r"(?:^|/)note(?:/|$)", path, re.I) is not None
    if _host_matches(host, "tiktok.com"):
        return re.search(r"(?:^|/)photo(?:/|$)", path, re.I) is not None
    if _host_matches(host, "instagram.com"):
        if re.search(r"(?:^|/)(?:reel|reels|tv)(?:/|$)", path, re.I):
            return False
        return re.search(r"(?:^|/)p(?:/|$)", path, re.I) is not None
    if _host_matches(host, "reddit.com") or _host_matches(host, "redd.it"):
        return re.search(r"(?:^|/)(?:gallery|comments)(?:/|$)", path, re.I) is not None
    if _host_matches(host, "twitter.com") or _host_matches(host, "x.com"):
        return re.search(r"(?:^|/)status(?:/|$)", path, re.I) is not None
    if _host_matches(host, "threads.net"):
        return re.search(r"(?:^|/)post(?:/|$)", path, re.I) is not None
    if _host_matches(host, "pinterest.com") or host == "pin.it":
        return True
    if _host_matches(host, "tumblr.com"):
        return True

    # Product pages, articles and generic websites remain eligible exactly as
    # in the base parser. Video-first media sites still bypass this layer.
    return not base._is_video_first_url(source_url)


def _classify(source_url: str, raw_html: str) -> tuple[str, str]:
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower().rstrip(".")

    if _host_matches(host, "xiaohongshu.com") or host == "xhslink.com":
        return "xiaohongshu", "post"
    if _host_matches(host, "douyin.com"):
        return "douyin", "post"
    if _host_matches(host, "instagram.com"):
        return "instagram", "post"
    if _host_matches(host, "tiktok.com"):
        return "tiktok", "post"
    if _host_matches(host, "twitter.com") or _host_matches(host, "x.com"):
        return "x", "post"
    if _host_matches(host, "reddit.com") or _host_matches(host, "redd.it"):
        return "reddit", "post"
    if _host_matches(host, "pinterest.com") or host == "pin.it":
        return "pinterest", "post"
    if _host_matches(host, "threads.net"):
        return "threads", "post"
    if _host_matches(host, "tumblr.com"):
        return "tumblr", "post"
    if _host_matches(host, "weibo.com") or _host_matches(host, "weibo.cn"):
        return "weibo", "post"
    if host == "t.me" or _host_matches(host, "telegram.me"):
        return "telegram", "post"
    if _host_matches(host, "mp.weixin.qq.com") or _host_matches(host, "weixin.qq.com"):
        return "wechat", "article"
    if "amazon." in host or ".amazon." in host:
        return "amazon", "product"
    if "ebay." in host or ".ebay." in host:
        return "ebay", "product"
    if "aliexpress." in host or ".aliexpress." in host:
        return "aliexpress", "product"
    if _host_matches(host, "alibaba.com"):
        return "alibaba", "product"
    if re.search(r"(?:shopify|cdn\.shopify\.com)", raw_html, re.I):
        return "shopify", "product"
    if re.search(r"<article\b", raw_html, re.I):
        return "generic", "article"
    return "generic", "webpage"


_original_document_payload = base._document_payload


def _document_payload(
    source_url: str,
    raw_html: str,
    final_url: str,
    browser: str,
) -> dict[str, Any] | None:
    result = _original_document_payload(source_url, raw_html, final_url, browser)
    if not result or not result.get("success"):
        return result

    data = result.get("data")
    if not isinstance(data, dict):
        return result

    if data.get("documentType") == "post":
        images = data.get("images") if isinstance(data.get("images"), list) else []
        videos = data.get("videos") if isinstance(data.get("videos"), list) else []
        # Do not let a normal video post collapse into its poster image. Mixed
        # media carousels with multiple images remain document results.
        if videos and len(images) <= 1:
            return None

    return result


def install_document_policy() -> None:
    # These are intentionally installed once at process start by entrypoint.py;
    # no request-time monkeypatching, so ThreadingHTTPServer has no race here.
    base._looks_like_image = _looks_like_image
    base.should_try_web_document = should_try_web_document
    base._classify = _classify
    base._document_payload = _document_payload


def parse_web_document(source_url: str, browser: str = "none") -> dict[str, Any]:
    return base.parse_web_document(source_url, browser)
