from __future__ import annotations

import html as html_lib
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

from yt_dlp import YoutubeDL

MAX_HTML_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 120
MAX_VIDEOS = 30
MAX_JSON_NODES = 20_000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
IMAGE_EXT_RE = re.compile(r"\.(?:avif|bmp|gif|jpe?g|png|webp)(?:$|[?#])", re.I)
VIDEO_EXT_RE = re.compile(r"\.(?:m4v|mov|mp4|webm)(?:$|[?#])", re.I)
TRACKING_ASSET_RE = re.compile(
    r"(?:sprite|favicon|icon[-_/]|logo[-_/]|avatar[-_/]|badge|placeholder|loading|spacer|pixel)[^/]*\.(?:gif|jpe?g|png|webp)",
    re.I,
)
EXTENSIONLESS_IMAGE_HOSTS = (
    "mmbiz.qpic.cn",
    "qpic.cn",
    "douyinpic.com",
    "xhscdn.com",
    "alicdn.com",
    "shopifycdn.net",
)
VIDEO_FIRST_HOSTS = (
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "dailymotion.com",
    "dai.ly",
    "bilibili.com",
    "tiktok.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "twitch.tv",
    "soundcloud.com",
    "reddit.com",
    "pinterest.com",
    "streamable.com",
    "nicovideo.jp",
    "niconico.com",
    "vk.com",
    "tumblr.com",
    "threads.net",
)


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith(f".{suffix}")


def _is_video_first_url(source_url: str) -> bool:
    try:
        parsed = urlparse(source_url)
    except ValueError:
        return True
    host = (parsed.hostname or "").lower().rstrip(".")
    if _host_matches(host, "xiaohongshu.com") or host == "xhslink.com":
        return True
    if _host_matches(host, "douyin.com"):
        return re.search(r"(?:^|/)note(?:/|$)", parsed.path, re.I) is None
    return any(_host_matches(host, suffix) for suffix in VIDEO_FIRST_HOSTS)


def should_try_web_document(source_url: str) -> bool:
    return not _is_video_first_url(source_url)


def _safe_hostname(hostname: str) -> bool:
    host = hostname.strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
    except ValueError:
        pass

    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return True
    for entry in addresses:
        value = entry[4][0]
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            return False
    return True


def _safe_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and _safe_hostname(parsed.hostname)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        target = urljoin(req.full_url, newurl)
        if not _safe_http_url(target):
            raise urllib.error.HTTPError(target, 403, "Unsafe redirect target", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _browser_cookie_header(source_url: str, browser: str) -> str:
    requested = (browser or "none").strip().lower()
    if requested == "none":
        return ""
    with YoutubeDL(
        {
            "quiet": True,
            "no_warnings": True,
            "cookiesfrombrowser": (requested, None, None, None),
        }
    ) as ydl:
        request = urllib.request.Request(source_url)
        ydl.cookiejar.add_cookie_header(request)
        return request.get_header("Cookie") or ""


def _fetch_html(source_url: str, browser: str) -> tuple[str, str]:
    if not _safe_http_url(source_url):
        raise ValueError("URL is not allowed")

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Accept-Encoding": "identity",
        "User-Agent": USER_AGENT,
    }
    cookie = _browser_cookie_header(source_url, browser)
    if cookie:
        headers["Cookie"] = cookie

    opener = urllib.request.build_opener(_SafeRedirectHandler())
    request = urllib.request.Request(source_url, headers=headers, method="GET")
    with opener.open(request, timeout=25) as response:
        final_url = response.geturl()
        if not _safe_http_url(final_url):
            raise ValueError("URL redirect is not allowed")
        content_type = str(response.headers.get("Content-Type") or "")
        if content_type and not re.search(r"(?:text/html|application/xhtml\+xml|text/plain)", content_type, re.I):
            raise ValueError(f"Unsupported document content type: {content_type}")
        declared = str(response.headers.get("Content-Length") or "").strip()
        if declared.isdigit() and int(declared) > MAX_HTML_BYTES:
            raise ValueError("Document is too large")
        payload = response.read(MAX_HTML_BYTES + 1)
        if len(payload) > MAX_HTML_BYTES:
            raise ValueError("Document is too large")
        charset = response.headers.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace"), final_url


def _clean_text(value: str) -> str:
    text = html_lib.unescape(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|section|article|li|h[1-6]|blockquote)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _absolute_url(raw: str | None, base: str) -> str | None:
    value = html_lib.unescape(str(raw or "")).strip().replace("\\u0026", "&").replace("\\/", "/")
    if not value or re.match(r"^(?:data|blob|javascript):", value, re.I):
        return None
    if "," in value:
        value = value.split(",", 1)[0].strip().split()[0]
    target = urljoin(base, value)
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return parsed._replace(fragment="").geturl()


def _looks_like_image(url: str, key: str = "") -> bool:
    if TRACKING_ASSET_RE.search(url):
        return False
    if IMAGE_EXT_RE.search(url):
        return True
    host = (urlparse(url).hostname or "").lower()
    if any(_host_matches(host, suffix) for suffix in EXTENSIONLESS_IMAGE_HOSTS):
        return True
    return bool(
        re.search(r"(?:src|image|img|photo|pic|cover|poster|thumbnail)", key, re.I)
        and re.search(r"(?:image|img|photo|pic|qpic|alicdn|cloudfront|cdn|media)", url, re.I)
    )


def _looks_like_video(url: str, key: str = "") -> bool:
    if VIDEO_EXT_RE.search(url):
        return True
    return bool(
        re.search(r"(?:video|contenturl|playurl|playaddr|streamurl|src|url)", key, re.I)
        and re.search(r"(?:video|vod|media|stream|play)", url, re.I)
        and not IMAGE_EXT_RE.search(url)
    )


class _DocumentParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_chunks: list[str] = []
        self.in_title = False
        self.meta: dict[str, list[str]] = {}
        self.images: list[str] = []
        self.videos: list[str] = []
        self._image_seen: set[str] = set()
        self._video_seen: set[str] = set()
        self.scripts: list[str] = []
        self._script_chunks: list[str] | None = None
        self._script_attrs: dict[str, str] = {}
        self._wechat_depth = 0
        self._wechat_chunks: list[str] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(key).lower(): str(value or "") for key, value in attrs}

    def _add_image(self, raw: str | None, key: str) -> None:
        if len(self.images) >= MAX_IMAGES:
            return
        url = _absolute_url(raw, self.base_url)
        if not url or url in self._image_seen or not _looks_like_image(url, key):
            return
        self._image_seen.add(url)
        self.images.append(url)

    def _add_video(self, raw: str | None, key: str) -> None:
        if len(self.videos) >= MAX_VIDEOS:
            return
        url = _absolute_url(raw, self.base_url)
        if not url or url in self._video_seen or not _looks_like_video(url, key):
            return
        self._video_seen.add(url)
        self.videos.append(url)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = self._attrs(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            identity = (values.get("property") or values.get("name") or values.get("itemprop") or "").lower()
            content = values.get("content", "")
            if identity and content:
                self.meta.setdefault(identity, []).append(content)
                if identity in {"og:image", "twitter:image", "twitter:image:src"}:
                    self._add_image(content, identity)
                if identity in {"og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"}:
                    self._add_video(content, identity)
        if tag in {"img", "source"}:
            for key in ("data-src", "data-original", "data-lazy-src", "data-actualsrc", "src", "srcset"):
                self._add_image(values.get(key), key)
        if tag in {"video", "source", "a"}:
            for key in ("src", "data-src", "href"):
                self._add_video(values.get(key), key)
        if tag == "script":
            self._script_attrs = values
            self._script_chunks = []
        if values.get("id") == "js_content":
            self._wechat_depth = 1
        elif self._wechat_depth > 0 and tag not in {"img", "source", "br", "hr", "meta", "link", "input"}:
            self._wechat_depth += 1
        if self._wechat_depth > 0 and tag == "br":
            self._wechat_chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag == "script" and self._script_chunks is not None:
            body = "".join(self._script_chunks).strip()
            attrs = self._script_attrs
            likely_json = (
                "json" in attrs.get("type", "").lower()
                or re.search(r"(?:__next_data__|serialized-server-data|render_data|__initial_state__|__data__|product)", attrs.get("id", ""), re.I)
                or body.startswith(("{", "[", "%7B", "%5B"))
            )
            if likely_json and body and len(body) <= 2_500_000:
                self.scripts.append(body)
            self._script_chunks = None
            self._script_attrs = {}
        if self._wechat_depth > 0 and tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}:
            self._wechat_chunks.append("\n")
        if self._wechat_depth > 0 and tag not in {"img", "source", "br", "hr", "meta", "link", "input"}:
            self._wechat_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_chunks.append(data)
        if self._script_chunks is not None:
            self._script_chunks.append(data)
        if self._wechat_depth > 0:
            self._wechat_chunks.append(data)

    @property
    def wechat_text(self) -> str:
        return _clean_text("".join(self._wechat_chunks))


def _meta_first(parser: _DocumentParser, *keys: str) -> str:
    for key in keys:
        values = parser.meta.get(key.lower(), [])
        if values and values[0].strip():
            return _clean_text(values[0])
    return ""


def _decode_script_json(raw: str) -> Any | None:
    candidates = [raw.strip()]
    if re.match(r"^%(?:7B|5B)", raw.strip(), re.I):
        try:
            from urllib.parse import unquote
            candidates.append(unquote(raw.strip()))
        except ValueError:
            pass
    for candidate in candidates:
        if not candidate.startswith(("{", "[")):
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _collect_json(parser: _DocumentParser, payload: Any) -> tuple[str, str, str, str]:
    title = ""
    description = ""
    author = ""
    published_at = ""
    stack: list[tuple[Any, str]] = [(payload, "")]
    visited = 0
    while stack and visited < MAX_JSON_NODES:
        value, key = stack.pop()
        visited += 1
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                continue
            if not title and re.match(r"^(?:name|title|headline)$", key, re.I) and len(raw) < 300:
                title = _clean_text(raw)
            if not description and re.match(r"^(?:description|desc|caption|content|content_text|text|summary)$", key, re.I) and len(raw) < 20_000:
                description = _clean_text(raw)
            if not author and re.match(r"^(?:author|authorname|author_name|nickname|user_name|username)$", key, re.I) and len(raw) < 200:
                author = _clean_text(raw)
            if not published_at and re.match(r"^(?:datepublished|date_published|publishdate|publish_date|publishedat|published_at|uploaddate)$", key, re.I) and len(raw) < 100:
                published_at = _clean_text(raw)
            parser._add_image(raw, key)
            parser._add_video(raw, key)
            continue
        if isinstance(value, list):
            for item in reversed(value):
                stack.append((item, key))
        elif isinstance(value, dict):
            for child_key, child in value.items():
                stack.append((child, str(child_key)))
    return title, description, author, published_at


def _classify(source_url: str, raw_html: str) -> tuple[str, str]:
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    if _host_matches(host, "xiaohongshu.com") or host == "xhslink.com":
        return "xiaohongshu", "post"
    if _host_matches(host, "douyin.com"):
        return "douyin", "post"
    if _host_matches(host, "mp.weixin.qq.com") or _host_matches(host, "weixin.qq.com"):
        return "wechat", "article"
    if "amazon." in host or ".amazon." in host:
        return "generic", "product"
    if "ebay." in host or ".ebay." in host:
        return "generic", "product"
    if "aliexpress." in host or ".aliexpress." in host:
        return "generic", "product"
    if _host_matches(host, "alibaba.com"):
        return "generic", "product"
    if re.search(r"(?:shopify|cdn\.shopify\.com)", raw_html, re.I):
        return "generic", "product"
    if re.search(r"<article\b", raw_html, re.I):
        return "generic", "article"
    return "generic", "webpage"


def _document_payload(source_url: str, raw_html: str, final_url: str, browser: str) -> dict[str, Any] | None:
    parser = _DocumentParser(final_url)
    parser.feed(raw_html)

    json_title = ""
    json_description = ""
    json_author = ""
    json_published_at = ""
    for raw in parser.scripts:
        payload = _decode_script_json(raw)
        if payload is None:
            continue
        title, description, author, published_at = _collect_json(parser, payload)
        json_title = json_title or title
        json_description = json_description or description
        json_author = json_author or author
        json_published_at = json_published_at or published_at

    platform, document_type = _classify(final_url, raw_html)
    title = _meta_first(parser, "og:title", "twitter:title") or _clean_text("".join(parser.title_chunks)) or json_title or (urlparse(final_url).hostname or "Web document")
    description = _meta_first(parser, "og:description", "twitter:description", "description") or json_description
    author = _meta_first(parser, "author", "article:author") or json_author
    published_at = _meta_first(parser, "article:published_time", "date", "pubdate") or json_published_at
    site_name = _meta_first(parser, "og:site_name", "application-name")
    text_content = parser.wechat_text if platform == "wechat" else description

    images = parser.images[:MAX_IMAGES]
    videos = [item for item in parser.videos if VIDEO_EXT_RE.search(item) or re.search(r"(?:video|vod|media)", item, re.I)][:MAX_VIDEOS]
    has_document_signal = (
        document_type != "webpage"
        or len(images) >= 2
        or (len(images) >= 1 and len(text_content) >= 20)
        or bool(videos)
    )
    if not has_document_signal:
        return None

    return {
        "success": True,
        "data": {
            "title": title,
            "desc": description or text_content[:1200],
            "textContent": text_content,
            "author": author or None,
            "publishedAt": published_at or None,
            "siteName": site_name or None,
            "documentType": document_type,
            "cover": images[0] if images else None,
            "platform": platform,
            "downloadAudioUrl": None,
            "downloadVideoUrl": None,
            "originDownloadAudioUrl": None,
            "originDownloadVideoUrl": None,
            "videoAudioMode": "not_applicable",
            "mediaActions": {"video": "hide", "audio": "hide"},
            "url": source_url,
            "kind": "image",
            "noteType": "image",
            "images": [
                {"index": index + 1, "url": url, "downloadUrl": url}
                for index, url in enumerate(images)
            ],
            "videos": [
                {
                    "id": f"document-video-{index + 1}",
                    "title": f"{title} · {index + 1}",
                    "downloadVideoUrl": url,
                    "originDownloadVideoUrl": url,
                    "downloadAudioUrl": None,
                    "originDownloadAudioUrl": None,
                    "videoAudioMode": "muxed",
                    "mediaActions": {"video": "direct-download", "audio": "extract-audio"},
                }
                for index, url in enumerate(videos)
            ],
            "localAuthBrowser": None if browser == "none" else browser,
        },
    }


def parse_web_document(source_url: str, browser: str = "none") -> dict[str, Any]:
    if not should_try_web_document(source_url):
        return {"success": False, "code": "UNSUPPORTED_PLATFORM", "status": 422, "error": "Prefer media parser"}
    try:
        raw_html, final_url = _fetch_html(source_url, browser)
        payload = _document_payload(source_url, raw_html, final_url, browser)
        if payload is not None:
            return payload
        return {"success": False, "code": "UNSUPPORTED_PLATFORM", "status": 422, "error": "No document media found"}
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return {
                "success": False,
                "code": "AUTH_REQUIRED",
                "status": 401,
                "error": "该网页拒绝匿名访问。请使用已登录目标平台的浏览器重试。",
            }
        return {"success": False, "code": "PARSE_FAILED", "status": 502, "error": f"Document request failed (HTTP {exc.code})"}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {"success": False, "code": "PARSE_FAILED", "status": 502, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "code": "PARSE_FAILED", "status": 502, "error": f"Document parser failed: {exc}"}
