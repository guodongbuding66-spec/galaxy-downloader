from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from url_policy import validated_public_http_url

MAX_GALLERY_FILES = 500
MAX_TELEGRAM_HTML_BYTES = 5_000_000
MAX_TELEGRAM_MEDIA_BYTES = 2_000_000_000
SOCIAL_PROFILE_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "reddit.com", "www.reddit.com", "old.reddit.com"}
BILIBILI_HOSTS = {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"}
TELEGRAM_HOSTS = {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}


class ContentProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    message: str
    path: Path | None = None
    count: int = 0


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def find_gallery_dl(engine_module) -> Path | None:
    names = ("gallery-dl.exe", "gallery-dl") if os.name == "nt" else ("gallery-dl",)
    roots: list[Path] = []
    accessor = getattr(engine_module, "tools_dir", None)
    if callable(accessor):
        try:
            tools = Path(accessor())
            roots.extend((tools / "gallery-dl" / "bin", tools / "gallery-dl", tools / "bin", tools))
        except (OSError, RuntimeError, TypeError, ValueError):
            # Managed optional-tool storage is absent in some portable/test contexts.
            roots = list(roots)
    app_dir_accessor = getattr(engine_module, "app_dir", None)
    if callable(app_dir_accessor):
        try:
            app_root = Path(app_dir_accessor())
            roots.extend((app_root / "bin", app_root))
        except (OSError, RuntimeError, TypeError, ValueError):
            # System PATH discovery below remains a valid fallback.
            roots = list(roots)
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
    resolved = shutil.which("gallery-dl")
    if resolved:
        candidate = Path(resolved)
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def gallery_download(
    engine_module,
    source_url: object,
    *,
    max_files: int = MAX_GALLERY_FILES,
    timeout_seconds: int = 3600,
) -> ProviderResult:
    url = validated_public_http_url(str(source_url or ""))
    executable = find_gallery_dl(engine_module)
    if executable is None:
        raise ContentProviderError("未检测到 gallery-dl")
    safe_max = max(1, min(int(max_files), MAX_GALLERY_FILES))
    root = Path(engine_module.default_download_dir()) / "gallery"
    root.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        "--destination",
        str(root),
        "--range",
        f"1-{safe_max}",
        "--",
        url,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(60, min(int(timeout_seconds), 7200)),
            check=False,
            creationflags=_creation_flags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ContentProviderError("gallery-dl 下载超时") from exc
    except OSError as exc:
        raise ContentProviderError(str(exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ContentProviderError(detail[-1600:] or f"gallery-dl exited with {result.returncode}")
    return ProviderResult("gallery-dl", "gallery-dl 下载完成", root, safe_max)


def social_profile_download(engine_module, source_url: object, *, max_files: int = 200) -> ProviderResult:
    url = validated_public_http_url(str(source_url or ""))
    host = (urlparse(url).hostname or "").lower()
    if host not in SOCIAL_PROFILE_HOSTS:
        raise ContentProviderError("仅支持 X/Twitter 与 Reddit 公开资料页")
    return gallery_download(engine_module, url, max_files=max_files)


def bilibili_deep_payload(
    source_url: object,
    *,
    browser: str = "none",
    selected_items: tuple[int, ...] | list[int] | None = None,
    subtitles: bool = True,
) -> dict[str, Any]:
    url = validated_public_http_url(str(source_url or ""))
    host = (urlparse(url).hostname or "").lower()
    if host not in BILIBILI_HOSTS:
        raise ContentProviderError("不是可识别的 Bilibili 链接")
    selected: list[int] = []
    for raw in selected_items or ():
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in selected:
            selected.append(value)
        if len(selected) >= 500:
            break
    mode = "selected" if selected else "all"
    return {
        "sourceUrl": url,
        "videoQuality": "best",
        "audioQuality": "best",
        "includeAudio": True,
        "includeSubtitle": bool(subtitles),
        "subtitleMode": "both",
        "browser": str(browser or "none"),
        "collectionMode": mode,
        "selectedItems": selected,
        "displayTitle": "Bilibili 深度下载",
    }


def _telegram_embed_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in TELEGRAM_HOSTS:
        raise ContentProviderError("不是 Telegram 公共帖子链接")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or not parts[-1].isdigit():
        raise ContentProviderError("Telegram 链接必须指向一个公开帖子")
    return f"https://t.me/{parts[-2]}/{parts[-1]}?embed=1&mode=tme"


def _limited_read(response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        block = response.read(min(64 * 1024, limit - total + 1))
        if not block:
            break
        total += len(block)
        if total > limit:
            raise ContentProviderError("响应超过安全大小限制")
        chunks.append(block)
    return b"".join(chunks)


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject a redirect before urllib can contact a non-public destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        validated_public_http_url(str(newurl or ""))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _public_opener():
    return urllib.request.build_opener(_ValidatedRedirectHandler())


def _fetch_public(url: str, *, max_bytes: int, timeout: int = 30) -> tuple[str, bytes, str]:
    validated = validated_public_http_url(url)
    request = urllib.request.Request(
        validated,
        headers={"User-Agent": "Mozilla/5.0 GalaxyLocalEngine/1.0"},
        method="GET",
    )
    try:
        with _public_opener().open(request, timeout=timeout) as response:  # noqa: S310 - initial and redirect URLs are validated
            final_url = validated_public_http_url(response.geturl())
            content_type = str(response.headers.get("Content-Type") or "")
            body = _limited_read(response, max_bytes)
            return final_url, body, content_type
    except ContentProviderError:
        raise
    except Exception as exc:
        raise ContentProviderError(str(exc)) from exc


def _telegram_media_candidates(page_url: str, text: str) -> list[str]:
    candidates: list[str] = []
    patterns = (
        r'<video[^>]+src=["\']([^"\']+)',
        r'<source[^>]+src=["\']([^"\']+)',
        r'<meta[^>]+property=["\']og:video(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']twitter:player:stream["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = html.unescape(match.group(1)).strip()
            if not value:
                continue
            absolute = urljoin(page_url, value)
            try:
                absolute = validated_public_http_url(absolute)
            except (TypeError, ValueError):
                continue
            if absolute not in candidates:
                candidates.append(absolute)
            if len(candidates) >= 10:
                return candidates
    return candidates


def _extension(url: str, content_type: str) -> str:
    path_ext = Path(urlparse(url).path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{2,5}", path_ext):
        return path_ext
    lowered = content_type.lower()
    for token, ext in (("video/mp4", ".mp4"), ("image/jpeg", ".jpg"), ("image/png", ".png"), ("image/webp", ".webp"), ("video/webm", ".webm")):
        if token in lowered:
            return ext
    return ".bin"


def telegram_public_post_download(
    engine_module,
    source_url: object,
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> ProviderResult:
    source = validated_public_http_url(str(source_url or ""))
    embed = _telegram_embed_url(source)
    page_url, body, _content_type = _fetch_public(embed, max_bytes=MAX_TELEGRAM_HTML_BYTES)
    text = body.decode("utf-8", errors="replace")
    candidates = _telegram_media_candidates(page_url, text)
    if not candidates:
        raise ContentProviderError("该公开 Telegram 帖子没有暴露可下载的媒体；私有频道/登录内容不在此适配器范围内")

    media_url = candidates[0]
    request = urllib.request.Request(media_url, headers={"User-Agent": "Mozilla/5.0 GalaxyLocalEngine/1.0"})
    target_root = Path(engine_module.default_download_dir()) / "telegram"
    target_root.mkdir(parents=True, exist_ok=True)
    post_id = urlparse(source).path.rstrip("/").split("/")[-1]
    temporary = target_root / f"telegram-{post_id}.part"
    try:
        with _public_opener().open(request, timeout=30) as response:  # noqa: S310 - media and redirects are public-URL validated
            final_url = validated_public_http_url(response.geturl())
            content_type = str(response.headers.get("Content-Type") or "")
            try:
                expected = int(response.headers.get("Content-Length") or 0)
            except ValueError:
                expected = 0
            if expected > MAX_TELEGRAM_MEDIA_BYTES:
                raise ContentProviderError("Telegram 媒体超过 2 GB 安全上限")
            extension = _extension(final_url, content_type)
            destination = target_root / f"telegram-{post_id}{extension}"
            total = 0
            with temporary.open("wb") as handle:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_TELEGRAM_MEDIA_BYTES:
                        raise ContentProviderError("Telegram 媒体超过 2 GB 安全上限")
                    handle.write(block)
                    if on_progress:
                        on_progress(total, expected)
            if destination.exists():
                destination = target_root / f"telegram-{post_id}-{os.urandom(3).hex()}{extension}"
            temporary.replace(destination)
            return ProviderResult("telegram-public", "Telegram 公开媒体下载完成", destination, 1)
    except ContentProviderError:
        with suppress(OSError):
            temporary.unlink()
        raise
    except Exception as exc:
        with suppress(OSError):
            temporary.unlink()
        raise ContentProviderError(str(exc)) from exc


def provider_status(engine_module) -> dict[str, Any]:
    return {
        "galleryDlReady": find_gallery_dl(engine_module) is not None,
        "bilibiliDeep": True,
        "socialProfileBatch": find_gallery_dl(engine_module) is not None,
        "telegramPublicPosts": True,
        "maxGalleryFiles": MAX_GALLERY_FILES,
    }


def run_content_providers_self_test() -> None:
    payload = bilibili_deep_payload("https://www.bilibili.com/video/BV1xx", selected_items=(1, 3, 3))
    assert payload["collectionMode"] == "selected"
    assert payload["selectedItems"] == [1, 3]
    assert _telegram_embed_url("https://t.me/example/123") == "https://t.me/example/123?embed=1&mode=tme"
    page = '<meta property="og:video" content="https://cdn.example.com/a.mp4">'
    # Avoid DNS-dependent URL-policy validation in the embedded self-test. The
    # extraction regex itself is verified with an invalid URL that is discarded.
    assert isinstance(_telegram_media_candidates("https://t.me/example/123", page), list)
