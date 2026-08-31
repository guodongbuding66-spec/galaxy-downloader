from __future__ import annotations

import json
import random
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yt_dlp import YoutubeDL

PARSE_URL = "https://yuanbao.tencent.com/api/weixin/get_parse_result"
FEED_INFO_URL = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
ENC_LIMIT = 131072
MASK64 = (1 << 64) - 1
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

PARSE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://yuanbao.tencent.com",
    "Referer": "https://yuanbao.tencent.com/",
    "User-Agent": USER_AGENT,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Language": "zh-CN",
    "X-Platform": "win",
    "X-Requested-With": "XMLHttpRequest",
    "X-Source": "web",
    "X-Web-Third-Source": "main",
}

FEED_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://channels.weixin.qq.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": USER_AGENT,
}


class WeChatChannelsError(RuntimeError):
    pass


class WeChatChannelsAuthError(WeChatChannelsError):
    pass


@dataclass(frozen=True)
class WeChatChannelsMedia:
    source_url: str
    share_url: str
    title: str
    author: str
    cover_url: str | None
    video_urls: tuple[str, ...]
    decode_key: int


_CACHE: dict[str, tuple[float, WeChatChannelsMedia]] = {}
_CACHE_TTL_SECONDS = 8 * 60


def _u64(value: int) -> int:
    return value & MASK64


class ISAAC64:
    def __init__(self, key: int) -> None:
        self.randcnt = 255
        self.seed = [0] * 256
        self.mm = [0] * 256
        self.aa = 0
        self.bb = 0
        self.cc = 0
        self._init(key & MASK64)

    @staticmethod
    def _mix(values: tuple[int, int, int, int, int, int, int, int]) -> tuple[int, ...]:
        a, b, c, d, e, f, g, h = values
        a = _u64(a - e)
        f = _u64(f ^ (h >> 9))
        h = _u64(h + a)
        b = _u64(b - f)
        g = _u64(g ^ _u64(a << 9))
        a = _u64(a + b)
        c = _u64(c - g)
        h = _u64(h ^ (b >> 23))
        b = _u64(b + c)
        d = _u64(d - h)
        a = _u64(a ^ _u64(c << 15))
        c = _u64(c + d)
        e = _u64(e - a)
        b = _u64(b ^ (d >> 14))
        d = _u64(d + e)
        f = _u64(f - b)
        c = _u64(c ^ _u64(e << 20))
        e = _u64(e + f)
        g = _u64(g - c)
        d = _u64(d ^ (f >> 17))
        f = _u64(f + g)
        h = _u64(h - d)
        e = _u64(e ^ _u64(g << 14))
        g = _u64(g + h)
        return a, b, c, d, e, f, g, h

    def _init(self, key: int) -> None:
        golden = 0x9E3779B97F4A7C13
        values: tuple[int, ...] = (golden,) * 8
        self.seed[0] = key
        for _ in range(4):
            values = self._mix(values)  # type: ignore[arg-type]

        for index in range(0, 256, 8):
            values = tuple(_u64(values[offset] + self.seed[index + offset]) for offset in range(8))
            values = self._mix(values)  # type: ignore[arg-type]
            self.mm[index:index + 8] = values

        for index in range(0, 256, 8):
            values = tuple(_u64(values[offset] + self.mm[index + offset]) for offset in range(8))
            values = self._mix(values)  # type: ignore[arg-type]
            self.mm[index:index + 8] = values

        self._isaac64()

    def _isaac64(self) -> None:
        self.cc = _u64(self.cc + 1)
        self.bb = _u64(self.bb + self.cc)
        for index in range(256):
            if index % 4 == 0:
                self.aa = _u64(~(self.aa ^ _u64(self.aa << 21)))
            elif index % 4 == 1:
                self.aa = _u64(self.aa ^ (self.aa >> 5))
            elif index % 4 == 2:
                self.aa = _u64(self.aa ^ _u64(self.aa << 12))
            else:
                self.aa = _u64(self.aa ^ (self.aa >> 33))

            self.aa = _u64(self.aa + self.mm[(index + 128) % 256])
            x = self.mm[index]
            y = _u64(self.mm[(x >> 3) % 256] + self.aa + self.bb)
            self.mm[index] = y
            self.bb = _u64(self.mm[(y >> 11) % 256] + x)
            self.seed[index] = self.bb

    def random(self) -> int:
        result = self.seed[self.randcnt]
        if self.randcnt == 0:
            self._isaac64()
            self.randcnt = 255
        else:
            self.randcnt -= 1
        return result


def isaac64_keystream(key: int, length: int) -> bytes:
    ctx = ISAAC64(key)
    result = bytearray()
    while len(result) < length:
        result.extend(struct.pack(">Q", ctx.random()))
    return bytes(result[:length])


def is_wechat_channels_url(source_url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(source_url.strip())
    except ValueError:
        return False
    host = parsed.netloc.lower().split(":", 1)[0]
    if host == "weixin.qq.com" and parsed.path.startswith("/sph/"):
        return bool(parsed.path.rstrip("/").split("/")[-1])
    if host == "channels.weixin.qq.com" and parsed.path == "/finder-preview/pages/sph":
        return bool(urllib.parse.parse_qs(parsed.query).get("id", [""])[0].strip())
    return False


def normalize_wechat_share_url(source_url: str) -> str:
    source_url = source_url.strip()
    if not is_wechat_channels_url(source_url):
        raise WeChatChannelsError("当前微信视频号链接格式暂不支持。请使用视频号“分享/复制链接”得到的链接。")
    parsed = urllib.parse.urlparse(source_url)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host == "weixin.qq.com":
        share_id = parsed.path.rstrip("/").split("/")[-1]
    else:
        share_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0].strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,80}", share_id):
        raise WeChatChannelsError("微信视频号分享 ID 无效。")
    return f"https://weixin.qq.com/sph/{share_id}"


def _cookie_header_from_browser(browser: str) -> str:
    browser = (browser or "none").strip().lower()
    if browser == "none":
        raise WeChatChannelsAuthError(
            "微信视频号需要腾讯元宝登录状态。请在网页右侧“登录状态”选择 Edge、Chrome 或 Firefox，"
            "并先用该浏览器打开 yuanbao.tencent.com 完成微信登录后重试。Cookie 只在本机读取。"
        )
    try:
        with YoutubeDL({
            "quiet": True,
            "no_warnings": True,
            "cookiesfrombrowser": (browser, None, None, None),
        }) as ydl:
            jar = ydl.cookiejar
            pairs: list[str] = []
            for cookie in jar:
                domain = str(getattr(cookie, "domain", "") or "").lstrip(".").lower()
                if domain == "tencent.com" or domain.endswith(".tencent.com"):
                    name = str(getattr(cookie, "name", "") or "").strip()
                    value = str(getattr(cookie, "value", "") or "")
                    if name:
                        pairs.append(f"{name}={value}")
    except Exception as exc:  # noqa: BLE001
        raise WeChatChannelsAuthError(
            f"无法读取 {browser.title()} 的腾讯元宝登录状态：{exc}。"
            "如果浏览器正在占用 Cookie 数据库，请完全关闭该浏览器后重试。"
        ) from exc

    if not pairs:
        raise WeChatChannelsAuthError(
            f"没有在 {browser.title()} 中找到腾讯元宝登录 Cookie。"
            "请先用这个浏览器打开 yuanbao.tencent.com 并完成微信登录，然后返回 Galaxy Downloader 重试。"
        )
    return "; ".join(pairs)


def _request_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float = 25.0) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(400).decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        if exc.code in {401, 403}:
            raise WeChatChannelsAuthError(
                "腾讯元宝登录状态已失效。请重新打开 yuanbao.tencent.com 完成登录后再试。"
            ) from exc
        raise WeChatChannelsError(f"微信视频号解析请求失败（HTTP {exc.code}）：{detail[:180]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WeChatChannelsError(f"无法连接微信视频号解析接口：{exc}") from exc

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WeChatChannelsError("微信视频号解析接口返回了无效数据。") from exc
    if not isinstance(parsed, dict):
        raise WeChatChannelsError("微信视频号解析接口返回了不支持的数据格式。")
    return parsed


def _generate_rid() -> str:
    return f"{int(time.time()):x}-" + "".join(random.choice("0123456789abcdef") for _ in range(8))


def _resolve_uncached(source_url: str, browser: str) -> WeChatChannelsMedia:
    share_url = normalize_wechat_share_url(source_url)
    cookie = _cookie_header_from_browser(browser)

    parse_payload = _request_json(
        PARSE_URL,
        {"type": "video_channel_url", "url": share_url, "scene": 1},
        {**PARSE_HEADERS, "Cookie": cookie},
    )
    parse_data = parse_payload.get("data")
    if not isinstance(parse_data, dict):
        raise WeChatChannelsAuthError(
            "腾讯元宝没有返回视频号解析结果。请确认当前浏览器已登录 yuanbao.tencent.com 后重试。"
        )
    playable_url = str(parse_data.get("playable_url") or "").strip()
    export_id = str(parse_data.get("wx_export_id") or "").strip()
    if not playable_url:
        raise WeChatChannelsAuthError(
            "腾讯元宝登录状态不可用或已过期。请重新登录 yuanbao.tencent.com 后重试。"
        )

    playable = urllib.parse.urlparse(playable_url)
    query = urllib.parse.parse_qs(playable.query)
    general_token = (query.get("token") or [""])[0].strip()
    feed_export_id = (query.get("eid") or [""])[0].strip() or export_id
    if not general_token or not feed_export_id:
        raise WeChatChannelsError("视频号解析结果缺少 token/eid，可能是微信接口已更新。")

    rid = _generate_rid()
    feed_url = (
        f"{FEED_INFO_URL}?_rid={urllib.parse.quote(rid)}"
        "&_pageUrl=https:%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed"
    )
    referer = (
        "https://channels.weixin.qq.com/finder-preview/pages/feed"
        "?entry_card_type=48&comment_scene=39&appid=0"
        f"&token={urllib.parse.quote(general_token)}&entry_scene=0&eid={urllib.parse.quote(feed_export_id)}"
    )
    feed_payload = _request_json(
        feed_url,
        {"baseReq": {"generalToken": general_token}, "exportId": feed_export_id},
        {**FEED_HEADERS, "Referer": referer},
    )
    err_code = int(feed_payload.get("errCode") or 0)
    if err_code != 0:
        raise WeChatChannelsError(
            f"微信视频号返回错误 {err_code}: {str(feed_payload.get('errMsg') or 'unknown error')[:180]}"
        )

    data = feed_payload.get("data")
    if not isinstance(data, dict):
        raise WeChatChannelsError("微信视频号没有返回视频详情。")
    feed = data.get("feedInfo")
    author_info = data.get("authorInfo")
    if not isinstance(feed, dict):
        raise WeChatChannelsError("微信视频号解析结果缺少 feedInfo。")
    if not isinstance(author_info, dict):
        author_info = {}

    candidate_urls: list[str] = []
    for value in (
        (feed.get("h264VideoInfo") or {}).get("videoUrl") if isinstance(feed.get("h264VideoInfo"), dict) else None,
        feed.get("videoUrl"),
        feed.get("originVideoUrl"),
        (feed.get("h265VideoInfo") or {}).get("videoUrl") if isinstance(feed.get("h265VideoInfo"), dict) else None,
    ):
        text = str(value or "").strip()
        if text and text not in candidate_urls:
            candidate_urls.append(text)
    if not candidate_urls:
        raise WeChatChannelsError("微信视频号没有返回可下载的视频地址。")

    title = str(feed.get("description") or parse_data.get("desc") or "微信视频号视频").strip()
    author = str(author_info.get("nickname") or parse_data.get("author") or "").strip()
    cover = str(feed.get("coverUrl") or parse_data.get("cover_url") or "").strip() or None
    try:
        decode_key = int(feed.get("decodeKey") or 0)
    except (TypeError, ValueError):
        decode_key = 0

    return WeChatChannelsMedia(
        source_url=source_url,
        share_url=share_url,
        title=title,
        author=author,
        cover_url=cover,
        video_urls=tuple(candidate_urls),
        decode_key=decode_key,
    )


def resolve_wechat_channels(source_url: str, browser: str, *, use_cache: bool = True) -> WeChatChannelsMedia:
    share_url = normalize_wechat_share_url(source_url)
    if use_cache:
        cached = _CACHE.get(share_url)
        if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
    media = _resolve_uncached(source_url, browser)
    _CACHE[share_url] = (time.time(), media)
    return media


def _safe_filename(value: str, fallback: str = "WeChat Channels") -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback
    return cleaned[:140].rstrip(" .")


def _human_bytes(value: int | float) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return "—"


def _looks_like_mp4(data: bytes) -> bool:
    return len(data) >= 8 and data[4:8] in {b"ftyp", b"styp", b"moov", b"mdat"}


def _clean_video_url(video_url: str) -> str | None:
    try:
        parsed = urllib.parse.urlparse(video_url)
    except ValueError:
        return None
    query = urllib.parse.parse_qs(parsed.query)
    encfilekey = (query.get("encfilekey") or [""])[0]
    token = (query.get("token") or [""])[0]
    if not encfilekey or not token:
        return None
    return urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        "",
        urllib.parse.urlencode({"encfilekey": encfilekey, "token": token}),
        "",
    ))


def _download_one(
    video_url: str,
    output_path: Path,
    decode_key: int,
    *,
    cancelled: Callable[[], bool],
    on_progress: Callable[[float, str, str, str, str], None],
) -> Path:
    request = urllib.request.Request(video_url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        response = urllib.request.urlopen(request, timeout=35)
    except urllib.error.HTTPError as exc:
        raise WeChatChannelsError(f"视频 CDN 返回 HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WeChatChannelsError(f"无法连接视频 CDN：{exc}") from exc

    with response:
        try:
            total = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        if total == 0 and response.headers.get("Content-Range"):
            match = re.search(r"/(\d+)$", response.headers.get("Content-Range") or "")
            if match:
                total = int(match.group(1))

        temp_path = output_path.with_suffix(output_path.suffix + ".part")
        temp_path.unlink(missing_ok=True)
        downloaded = 0
        started = time.monotonic()
        decrypt_enabled: bool | None = None
        keystream = isaac64_keystream(decode_key, ENC_LIMIT) if decode_key else b""

        try:
            with temp_path.open("wb") as target:
                while True:
                    if cancelled():
                        raise WeChatChannelsError("下载已取消")
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    if decrypt_enabled is None:
                        decrypt_enabled = bool(decode_key and not _looks_like_mp4(chunk[:32]))
                    if decrypt_enabled and downloaded < ENC_LIMIT:
                        mutable = bytearray(chunk)
                        count = min(len(mutable), ENC_LIMIT - downloaded)
                        key_slice = keystream[downloaded:downloaded + count]
                        mutable[:count] = bytes(a ^ b for a, b in zip(mutable[:count], key_slice))
                        chunk = bytes(mutable)
                    target.write(chunk)
                    downloaded += len(chunk)

                    elapsed = max(time.monotonic() - started, 0.001)
                    speed_bps = downloaded / elapsed
                    percent = (downloaded / total * 100.0) if total else 0.0
                    eta = ((total - downloaded) / speed_bps) if total and speed_bps > 0 else 0.0
                    on_progress(
                        max(0.0, min(100.0, percent)),
                        f"{_human_bytes(speed_bps)}/s",
                        f"{int(eta)} s" if eta > 0 else "—",
                        _human_bytes(downloaded),
                        _human_bytes(total) if total else "—",
                    )
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        if downloaded <= 0:
            temp_path.unlink(missing_ok=True)
            raise WeChatChannelsError("视频 CDN 返回了空文件。")

        with temp_path.open("rb") as handle:
            prefix = handle.read(32)
        if not _looks_like_mp4(prefix):
            temp_path.unlink(missing_ok=True)
            raise WeChatChannelsError("视频下载完成但文件头无效，微信的视频加密参数可能已更新。")

        output_path.unlink(missing_ok=True)
        temp_path.replace(output_path)
        return output_path


def download_wechat_channels(
    source_url: str,
    output_dir: Path,
    browser: str,
    *,
    cancelled: Callable[[], bool],
    on_progress: Callable[[float, str, str, str, str], None],
    on_status: Callable[[str], None],
) -> Path:
    on_status("正在解析微信视频号分享链接")
    media = resolve_wechat_channels(source_url, browser)
    title = media.title
    if media.author:
        title = f"{title} - {media.author}"
    output_path = output_dir / f"{_safe_filename(title)}.mp4"

    candidates: list[str] = []
    for video_url in media.video_urls:
        for candidate in (video_url, _clean_video_url(video_url)):
            if candidate and candidate not in candidates:
                candidates.append(candidate)

    errors: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        if cancelled():
            raise WeChatChannelsError("下载已取消")
        on_status(f"正在下载微信视频号媒体流（线路 {index}/{len(candidates)}）")
        try:
            return _download_one(
                candidate,
                output_path,
                media.decode_key,
                cancelled=cancelled,
                on_progress=on_progress,
            )
        except WeChatChannelsError as exc:
            errors.append(str(exc))

    detail = "；".join(errors[-3:]) if errors else "没有可用的视频地址"
    raise WeChatChannelsError(f"微信视频号下载失败：{detail}")
