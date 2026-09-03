from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from url_policy import validated_public_http_url

MAX_GALLERY_FILES = 500
MAX_SOCIAL_FILES = 200
MAX_PROVIDER_LOG_BYTES = 256_000
MAX_TELEGRAM_HTML_BYTES = 5_000_000
MAX_TELEGRAM_MEDIA_BYTES = 2_000_000_000
MAX_TELEGRAM_CANDIDATES = 10

SOCIAL_PROFILE_HOSTS = frozenset({
    "x.com", "www.x.com", "twitter.com", "www.twitter.com",
    "reddit.com", "www.reddit.com", "old.reddit.com",
})
BILIBILI_HOSTS = frozenset({"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"})
TELEGRAM_HOSTS = frozenset({"t.me", "www.t.me", "telegram.me", "www.telegram.me"})
BROWSERS = frozenset({"none", "edge", "chrome", "firefox", "brave"})
_TELEGRAM_CHANNEL_RE = re.compile(r"^[A-Za-z0-9_]{3,64}$")
_SAFE_MEDIA_EXTENSIONS = frozenset({".mp4", ".webm", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".m4v"})


class ContentProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    message: str
    path: Path | None = None
    count: int = 0

    def public_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path) if self.path is not None else ""
        return data


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _safe_managed_directory(root: Path, child: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / child
    if target.exists() and target.is_symlink():
        raise ContentProviderError(f"{child} 下载目录不能是符号链接")
    target.mkdir(parents=True, exist_ok=True)
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ContentProviderError("Provider 下载目录越界") from exc
    return target


def find_gallery_dl(engine_module) -> Path | None:
    names = ("gallery-dl.exe", "gallery-dl") if os.name == "nt" else ("gallery-dl",)
    roots: list[Path] = []
    accessor = getattr(engine_module, "tools_dir", None)
    if callable(accessor):
        with suppress(OSError, RuntimeError, TypeError, ValueError):
            tools = Path(accessor())
            roots.extend((tools / "gallery-dl" / "bin", tools / "gallery-dl", tools / "bin", tools))
    app_dir_accessor = getattr(engine_module, "app_dir", None)
    if callable(app_dir_accessor):
        with suppress(OSError, RuntimeError, TypeError, ValueError):
            app_root = Path(app_dir_accessor())
            roots.extend((app_root / "bin", app_root))
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


def _bounded_log(path: Path) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > MAX_PROVIDER_LOG_BYTES:
                handle.seek(max(0, size - MAX_PROVIDER_LOG_BYTES))
            raw = handle.read(MAX_PROVIDER_LOG_BYTES)
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace").strip()[-4000:]


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
    try:
        safe_max = max(1, min(int(max_files), MAX_GALLERY_FILES))
        timeout = max(60, min(int(timeout_seconds), 7200))
    except (TypeError, ValueError) as exc:
        raise ContentProviderError("gallery-dl 参数无效") from exc

    root = _safe_managed_directory(Path(engine_module.default_download_dir()), "gallery")
    command = [str(executable), "--destination", str(root), "--range", f"1-{safe_max}", "--", url]
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="galaxy-gallery-stdout-", delete=False) as stdout_file, tempfile.NamedTemporaryFile(
            prefix="galaxy-gallery-stderr-", delete=False
        ) as stderr_file:
            stdout_path = Path(stdout_file.name)
            stderr_path = Path(stderr_file.name)
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout,
                check=False,
                shell=False,
                creationflags=_creation_flags(),
            )
        if result.returncode != 0:
            detail = _bounded_log(stderr_path) or _bounded_log(stdout_path)
            raise ContentProviderError(detail or f"gallery-dl exited with {result.returncode}")
    except subprocess.TimeoutExpired as exc:
        raise ContentProviderError("gallery-dl 下载超时") from exc
    except OSError as exc:
        raise ContentProviderError(str(exc)) from exc
    finally:
        for path in (stdout_path, stderr_path):
            if path is not None:
                with suppress(OSError):
                    path.unlink()
    return ProviderResult("gallery-dl", "gallery-dl 下载完成", root, safe_max)


def social_profile_download(engine_module, source_url: object, *, max_files: int = MAX_SOCIAL_FILES) -> ProviderResult:
    url = validated_public_http_url(str(source_url or ""))
    host = (urlparse(url).hostname or "").lower()
    if host not in SOCIAL_PROFILE_HOSTS:
        raise ContentProviderError("仅支持 X/Twitter 与 Reddit 公开资料页")
    try:
        safe_max = max(1, min(int(max_files), MAX_SOCIAL_FILES))
    except (TypeError, ValueError) as exc:
        raise ContentProviderError("批量文件数量无效") from exc
    return gallery_download(engine_module, url, max_files=safe_max)


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
    browser_id = str(browser or "none").strip().lower()
    if browser_id not in BROWSERS:
        raise ContentProviderError("浏览器 Cookie 来源无效")
    selected: list[int] = []
    for raw in selected_items or ():
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 < value <= 10_000 and value not in selected:
            selected.append(value)
        if len(selected) >= 500:
            break
    return {
        "sourceUrl": url,
        "videoQuality": "best",
        "audioQuality": "best",
        "includeAudio": True,
        "includeSubtitle": bool(subtitles),
        "subtitleMode": "both",
        "browser": browser_id,
        "collectionMode": "selected" if selected else "all",
        "selectedItems": selected,
        "displayTitle": "Bilibili 深度下载",
    }


def _telegram_embed_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in TELEGRAM_HOSTS:
        raise ContentProviderError("不是 Telegram 公共帖子链接")
    if parsed.username is not None or parsed.password is not None:
        raise ContentProviderError("Telegram URL 不能包含凭据")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or not _TELEGRAM_CHANNEL_RE.fullmatch(parts[0]) or not parts[1].isdigit():
        raise ContentProviderError("Telegram 链接必须是公开频道/用户的单个帖子")
    post_id = int(parts[1])
    if post_id <= 0:
        raise ContentProviderError("Telegram 帖子 ID 无效")
    return f"https://t.me/{parts[0]}/{post_id}?embed=1&mode=tme"


def _limited_read(response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = limit - total
        block = response.read(min(64 * 1024, max(1, remaining + 1)))
        if not block:
            break
        total += len(block)
        if total > limit:
            raise ContentProviderError("响应超过安全大小限制")
        chunks.append(block)
    return b"".join(chunks)


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        validated_public_http_url(str(newurl or ""))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _public_opener():
    return urllib.request.build_opener(_ValidatedRedirectHandler())


def _fetch_public(url: str, *, max_bytes: int, timeout: int = 30) -> tuple[str, bytes, str]:
    validated = validated_public_http_url(url)
    request = urllib.request.Request(validated, headers={"User-Agent": "Mozilla/5.0 GalaxyLocalEngine/1.0"}, method="GET")
    try:
        with _public_opener().open(request, timeout=max(5, min(int(timeout), 60))) as response:  # noqa: S310
            final_url = validated_public_http_url(response.geturl())
            content_type = str(response.headers.get("Content-Type") or "")
            return final_url, _limited_read(response, max_bytes), content_type
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
        for match in re.finditer(pattern, text[:MAX_TELEGRAM_HTML_BYTES], flags=re.IGNORECASE):
            value = html.unescape(match.group(1)).strip()
            if not value:
                continue
            absolute = urljoin(page_url, value)
            try:
                absolute = validated_public_http_url(absolute)
            except Exception:
                continue
            if absolute not in candidates:
                candidates.append(absolute)
            if len(candidates) >= MAX_TELEGRAM_CANDIDATES:
                return candidates
    return candidates


def _extension(url: str, content_type: str) -> str:
    path_ext = Path(urlparse(url).path).suffix.lower()
    if path_ext in _SAFE_MEDIA_EXTENSIONS:
        return ".jpg" if path_ext == ".jpeg" else path_ext
    lowered = content_type.lower()
    for token, ext in (("video/mp4", ".mp4"), ("video/webm", ".webm"), ("image/jpeg", ".jpg"), ("image/png", ".png"), ("image/webp", ".webp"), ("image/gif", ".gif")):
        if token in lowered:
            return ext
    raise ContentProviderError("Telegram 媒体类型不在允许范围内")


def telegram_public_post_download(
    engine_module,
    source_url: object,
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> ProviderResult:
    source = validated_public_http_url(str(source_url or ""))
    embed = _telegram_embed_url(source)
    page_url, body, _content_type = _fetch_public(embed, max_bytes=MAX_TELEGRAM_HTML_BYTES)
    candidates = _telegram_media_candidates(page_url, body.decode("utf-8", errors="replace"))
    if not candidates:
        raise ContentProviderError("该公开 Telegram 帖子没有暴露可下载媒体；私有/登录内容不在适配器范围内")

    request = urllib.request.Request(candidates[0], headers={"User-Agent": "Mozilla/5.0 GalaxyLocalEngine/1.0"}, method="GET")
    target_root = _safe_managed_directory(Path(engine_module.default_download_dir()), "telegram")
    post_id = urlparse(source).path.rstrip("/").split("/")[-1]
    temporary = target_root / f".telegram-{post_id}-{os.urandom(4).hex()}.part"
    try:
        with _public_opener().open(request, timeout=30) as response:  # noqa: S310
            final_url = validated_public_http_url(response.geturl())
            content_type = str(response.headers.get("Content-Type") or "")
            try:
                expected = int(response.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                expected = 0
            if expected < 0 or expected > MAX_TELEGRAM_MEDIA_BYTES:
                raise ContentProviderError("Telegram 媒体大小无效或超过 2 GB 安全上限")
            extension = _extension(final_url, content_type)
            destination = target_root / f"telegram-{post_id}{extension}"
            if destination.exists():
                destination = target_root / f"telegram-{post_id}-{os.urandom(3).hex()}{extension}"
            total = 0
            with temporary.open("xb") as handle:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_TELEGRAM_MEDIA_BYTES:
                        raise ContentProviderError("Telegram 媒体超过 2 GB 安全上限")
                    handle.write(block)
                    if on_progress is not None:
                        on_progress(total, expected)
            if total <= 0:
                raise ContentProviderError("Telegram 媒体响应为空")
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
    gallery_ready = find_gallery_dl(engine_module) is not None
    return {
        "galleryDlReady": gallery_ready,
        "bilibiliDeep": True,
        "socialProfileBatch": gallery_ready,
        "telegramPublicPosts": True,
        "maxGalleryFiles": MAX_GALLERY_FILES,
        "maxSocialFiles": MAX_SOCIAL_FILES,
        "automaticLogin": False,
        "privateTelegram": False,
    }


def run_content_providers_self_test() -> None:
    from unittest.mock import patch

    with patch("content_providers.validated_public_http_url", side_effect=lambda value: str(value)):
        payload = bilibili_deep_payload(
            "https://www.bilibili.com/video/BV1xx",
            browser="edge",
            selected_items=(1, 3, 3, -1),
        )
        assert payload["collectionMode"] == "selected"
        assert payload["selectedItems"] == [1, 3]
        assert payload["browser"] == "edge"
        assert _telegram_embed_url("https://t.me/example_1/123") == "https://t.me/example_1/123?embed=1&mode=tme"
        try:
            _telegram_embed_url("https://t.me/+private/123")
        except ContentProviderError:
            pass
        else:
            raise AssertionError("private Telegram invitation was accepted")
        page = '<meta property="og:video" content="https://cdn.example.com/a.mp4">'
        assert _telegram_media_candidates("https://t.me/example_1/123", page) == ["https://cdn.example.com/a.mp4"]
        assert _extension("https://cdn.example.com/a.unknown", "video/mp4") == ".mp4"
        try:
            bilibili_deep_payload("https://www.bilibili.com/video/BV1xx", browser="../bad")
        except ContentProviderError:
            pass
        else:
            raise AssertionError("unsafe browser value was accepted")
