from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import dynamic_document as _dynamic
import headless_service as _service
from url_policy import validated_public_http_url

MAX_CANDIDATES = 64
MAX_AUTHORIZATIONS = 500
AUTHORIZATION_TTL_SECONDS = 6 * 60 * 60
_WIDEVINE_UUID = "edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"
_MEDIA_EXTENSIONS = (".m3u8", ".mpd", ".mp4", ".m4a", ".webm", ".mov")
_MEDIA_MIME_PREFIXES = ("video/", "audio/")
_MEDIA_MIME_EXACT = {
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "application/dash+xml",
}


class HotmartCourseError(_service.HeadlessServiceError):
    pass


class HotmartDrmProtectedError(HotmartCourseError):
    pass


@dataclass(frozen=True)
class HotmartMediaCandidate:
    url: str
    mime_type: str = ""
    source: str = "network"
    request_id: str = ""

    @property
    def kind(self) -> str:
        lowered = self.url.lower().split("?", 1)[0]
        mime = self.mime_type.lower()
        if lowered.endswith(".m3u8") or "mpegurl" in mime:
            return "hls"
        if lowered.endswith(".mpd") or "dash+xml" in mime:
            return "dash"
        if lowered.endswith((".mp4", ".mov")) or mime.startswith("video/"):
            return "video"
        if lowered.endswith((".m4a", ".webm")) or mime.startswith("audio/"):
            return "audio"
        return "media"


_AUTH_LOCK = threading.RLock()
_AUTHORIZATIONS: OrderedDict[str, dict[str, Any]] = OrderedDict()
_AUTH_INSTALLED = False


def _clean_browser(value: object) -> str:
    browser = str(value or "none").strip().lower()
    if browser not in {"edge", "chrome", "firefox", "brave"}:
        raise HotmartCourseError("Hotmart 下载需要选择已登录 Hotmart 的 Edge、Chrome、Firefox 或 Brave")
    return browser


def _is_hotmart_club_url(url: str) -> bool:
    try:
        host = str(urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    suffix = ".club.hotmart.com"
    return host.endswith(suffix) and bool(host[: -len(suffix)].strip("."))


def _validated_hotmart_url(value: object) -> str:
    try:
        url = validated_public_http_url(str(value or "").strip())
    except Exception as exc:
        raise HotmartCourseError(str(exc)) from exc
    if not _is_hotmart_club_url(url):
        raise HotmartCourseError("Hotmart URL 必须指向 <club>.club.hotmart.com 成员区")
    return url


def _validated_media_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or raw.lower().startswith(("blob:", "data:", "file:", "javascript:")):
        raise HotmartCourseError("Hotmart 媒体候选不是可下载的公网 HTTP(S) 资源")
    try:
        validated = validated_public_http_url(raw)
    except Exception as exc:
        raise HotmartCourseError(str(exc)) from exc
    # `validated_public_http_url` is expected to preserve signed query strings.
    # Fail closed if a future validator ever strips them.
    if urlparse(raw).query and urlparse(validated).query != urlparse(raw).query:
        raise HotmartCourseError("Hotmart 签名媒体 URL 在安全校验期间被修改")
    return validated


def _candidate_key(candidate: HotmartMediaCandidate) -> str:
    return candidate.url.strip()


def _looks_like_media(url: str, mime_type: str = "") -> bool:
    clean = str(url or "").strip()
    if not clean.lower().startswith(("http://", "https://")):
        return False
    path = urlparse(clean).path.lower()
    mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    return path.endswith(_MEDIA_EXTENSIONS) or mime.startswith(_MEDIA_MIME_PREFIXES) or mime in _MEDIA_MIME_EXACT


def _candidate_score(candidate: HotmartMediaCandidate) -> tuple[int, int, int]:
    kind_score = {"hls": 500, "dash": 450, "video": 400, "audio": 250, "media": 100}.get(candidate.kind, 0)
    source_score = {"dom": 40, "network": 30, "performance": 20}.get(candidate.source, 0)
    signed_score = 10 if urlparse(candidate.url).query else 0
    return kind_score, source_score, signed_score


def rank_hotmart_candidates(values: list[HotmartMediaCandidate]) -> list[HotmartMediaCandidate]:
    deduped: dict[str, HotmartMediaCandidate] = {}
    for candidate in values[: MAX_CANDIDATES * 4]:
        if not _looks_like_media(candidate.url, candidate.mime_type):
            continue
        try:
            safe_url = _validated_media_url(candidate.url)
        except HotmartCourseError:
            continue
        normalized = HotmartMediaCandidate(
            url=safe_url,
            mime_type=str(candidate.mime_type or "")[:160],
            source=str(candidate.source or "network")[:40],
            request_id=str(candidate.request_id or "")[:180],
        )
        key = _candidate_key(normalized)
        current = deduped.get(key)
        if current is None or _candidate_score(normalized) > _candidate_score(current):
            deduped[key] = normalized
    ranked = sorted(deduped.values(), key=_candidate_score, reverse=True)
    return ranked[:MAX_CANDIDATES]


def manifest_uses_drm(text: object, *, kind: str = "") -> bool:
    body = str(text or "").lower()
    if not body:
        return False
    if _WIDEVINE_UUID in body or "com.widevine.alpha" in body:
        return True
    if "<contentprotection" in body or "cenc:pssh" in body:
        return True
    if kind == "hls" or "#extm3u" in body:
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped.startswith("#ext-x-key"):
                continue
            if "method=sample-aes" in stripped or "keyformat=" in stripped:
                return True
    return False


class _HotmartProbeClient(_dynamic._CdpClient):
    def __init__(self, ws_url: str):
        super().__init__(ws_url)
        self.candidates: list[HotmartMediaCandidate] = []

    def _handle_event(self, payload: dict[str, Any]) -> None:
        super()._handle_event(payload)
        if payload.get("method") != "Network.responseReceived":
            return
        params = payload.get("params")
        if not isinstance(params, dict):
            return
        response = params.get("response")
        if not isinstance(response, dict):
            return
        url = str(response.get("url") or "").strip()
        mime = str(response.get("mimeType") or "").strip()
        if not _looks_like_media(url, mime):
            return
        self.candidates.append(
            HotmartMediaCandidate(
                url=url,
                mime_type=mime,
                source="network",
                request_id=str(params.get("requestId") or ""),
            )
        )


def _browser_process(executable: Path, profile_dir: str, port: int) -> subprocess.Popen[Any]:
    args = [
        str(executable),
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-component-update",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-extensions",
        "--autoplay-policy=no-user-gesture-required",
        "--window-size=1365,900",
        "about:blank",
    ]
    return subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=_dynamic._creation_flags(),
    )


def _dom_media_candidates(client: _HotmartProbeClient) -> list[HotmartMediaCandidate]:
    expression = r"""
(() => {
  const out = [];
  const push = (url, source) => {
    if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) return;
    out.push({url, source});
  };
  for (const media of document.querySelectorAll('video,audio')) {
    push(media.currentSrc, 'dom');
    push(media.src, 'dom');
    for (const source of media.querySelectorAll('source')) push(source.src, 'dom');
  }
  for (const entry of performance.getEntriesByType('resource')) push(entry.name, 'performance');
  return out.slice(0, 128);
})()
"""
    raw = _dynamic._evaluate_value(client, expression, timeout=4.0)
    result: list[HotmartMediaCandidate] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if _looks_like_media(url):
                result.append(HotmartMediaCandidate(url=url, source=str(item.get("source") or "dom")))
    return result


def _manifest_body(client: _HotmartProbeClient, candidate: HotmartMediaCandidate) -> str:
    if not candidate.request_id or candidate.kind not in {"hls", "dash"}:
        return ""
    try:
        payload = client.call("Network.getResponseBody", {"requestId": candidate.request_id}, timeout=2.0)
    except Exception:
        return ""
    if payload.get("base64Encoded"):
        return ""
    return str(payload.get("body") or "")[:2_000_000]


def resolve_authorized_hotmart_media(source_url: object, browser: object) -> dict[str, Any]:
    """Resolve media already accessible to the user's authorized Hotmart session.

    This function never authenticates around Hotmart, never modifies CDN query
    signatures, and never decrypts protected streams. It launches a temporary
    browser, imports the user's explicitly selected browser cookies through the
    existing bounded cookie loader, observes resources the page itself obtains,
    and returns one non-DRM public media URL for the normal download runtime.
    """

    page_url = _validated_hotmart_url(source_url)
    browser_id = _clean_browser(browser)
    candidates = _dynamic._browser_candidates(browser_id)
    if not candidates:
        raise HotmartCourseError("需要本机 Edge 或 Chrome 来解析 Hotmart 已授权课程页面")

    last_error: Exception | None = None
    for _browser_name, executable in candidates:
        profile_dir = tempfile.mkdtemp(prefix="galaxy-hotmart-course-")
        port = _dynamic._free_port()
        process: subprocess.Popen[Any] | None = None
        client: _HotmartProbeClient | None = None
        try:
            process = _browser_process(executable, profile_dir, port)
            ws_url = _dynamic._wait_page_ws(port, process)
            client = _HotmartProbeClient(ws_url)
            client.call("Network.enable")
            client.call("Page.enable")
            client.call("Runtime.enable")
            client.call(
                "Fetch.enable",
                {"patterns": [{"urlPattern": "http://*"}, {"urlPattern": "https://*"}]},
            )
            client.call(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": "window.__galaxyEncryptedMediaSeen=false;document.addEventListener('encrypted',()=>{window.__galaxyEncryptedMediaSeen=true;},true);"
                },
            )
            _dynamic._install_browser_cookies(client, page_url, browser_id)
            client.call("Page.navigate", {"url": page_url}, timeout=5.0)

            deadline = time.monotonic() + _dynamic.CDP_NAVIGATION_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if client.blocked_document_url:
                    raise HotmartCourseError("Hotmart 页面尝试导航到被阻止的私网/本地地址")
                with suppress(Exception):
                    ready = _dynamic._evaluate_value(client, "document.readyState", timeout=1.5)
                    if ready in {"interactive", "complete"}:
                        break
                time.sleep(0.25)

            # Ask existing media elements to load. This does not synthesize
            # credentials or bypass user gestures; it only encourages the page
            # to request resources it is already authorized to render.
            with suppress(Exception):
                _dynamic._evaluate_value(
                    client,
                    "new Promise(r=>{for(const v of document.querySelectorAll('video,audio')){try{v.load()}catch(e){}};setTimeout(()=>r(true),1200)})",
                    await_promise=True,
                    timeout=3.0,
                )
            with suppress(Exception):
                _dynamic._evaluate_value(client, "document.readyState", timeout=1.5)

            encrypted = bool(_dynamic._evaluate_value(client, "Boolean(window.__galaxyEncryptedMediaSeen)", timeout=1.5))
            ranked = rank_hotmart_candidates(client.candidates + _dom_media_candidates(client))
            if encrypted:
                raise HotmartDrmProtectedError("Hotmart 课程使用浏览器 DRM/EME，Galaxy 不提供 DRM 绕过")
            if not ranked:
                raise HotmartCourseError("当前已授权 Hotmart 页面没有发现可下载的非 DRM 媒体；请确认已登录并打开具体课程/课时页面")

            for candidate in ranked:
                body = _manifest_body(client, candidate)
                if body and manifest_uses_drm(body, kind=candidate.kind):
                    continue
                return {
                    "mediaUrl": candidate.url,
                    "referer": page_url,
                    "browser": browser_id,
                    "kind": candidate.kind,
                    "mimeType": candidate.mime_type,
                    "candidateCount": len(ranked),
                }
            raise HotmartDrmProtectedError("Hotmart 页面发现的媒体清单均包含 DRM/ContentProtection，Galaxy 已拒绝下载")
        except (HotmartCourseError, HotmartDrmProtectedError) as exc:
            last_error = exc
        except Exception as exc:  # noqa: BLE001
            last_error = HotmartCourseError(str(exc))
        finally:
            if client is not None:
                client.close()
            if process is not None:
                with suppress(Exception):
                    process.terminate()
                    process.wait(timeout=3.0)
                if process.poll() is None:
                    with suppress(Exception):
                        process.kill()
            shutil.rmtree(profile_dir, ignore_errors=True)
        if isinstance(last_error, HotmartDrmProtectedError):
            raise last_error
    if isinstance(last_error, HotmartCourseError):
        raise last_error
    raise HotmartCourseError("Hotmart 授权媒体解析失败")


def _prune_authorizations_locked(now: float) -> None:
    expired = [token for token, value in _AUTHORIZATIONS.items() if float(value.get("expiresAt") or 0) <= now]
    for token in expired:
        _AUTHORIZATIONS.pop(token, None)
    while len(_AUTHORIZATIONS) >= MAX_AUTHORIZATIONS:
        _AUTHORIZATIONS.popitem(last=False)


def register_hotmart_download_authorization(*, browser: object, referer: object) -> str:
    browser_id = _clean_browser(browser)
    page_url = _validated_hotmart_url(referer)
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _AUTH_LOCK:
        _prune_authorizations_locked(now)
        _AUTHORIZATIONS[token] = {
            "browser": browser_id,
            "referer": page_url,
            "expiresAt": now + AUTHORIZATION_TTL_SECONDS,
        }
    return token


def revoke_hotmart_download_authorization(token: object) -> None:
    clean = str(token or "").strip()
    if not clean:
        return
    with _AUTH_LOCK:
        _AUTHORIZATIONS.pop(clean, None)


def _authorization_context(token: object) -> dict[str, str]:
    clean = str(token or "").strip()
    if not clean:
        raise HotmartCourseError("Hotmart 内部授权令牌缺失")
    now = time.monotonic()
    with _AUTH_LOCK:
        _prune_authorizations_locked(now)
        value = _AUTHORIZATIONS.get(clean)
        if value is None:
            raise HotmartCourseError("Hotmart 内部授权令牌无效或已过期")
        _AUTHORIZATIONS.move_to_end(clean)
        return {"browser": str(value["browser"]), "referer": str(value["referer"])}


def install_headless_hotmart_authorization() -> None:
    """Compose process-local Hotmart auth onto the current download options.

    Public callers cannot provide a browser Referer/header bundle. Only a random
    in-process authorization token minted by the managed course coordinator can
    activate this layer. Unknown/forged tokens fail closed.
    """

    global _AUTH_INSTALLED
    if _AUTH_INSTALLED:
        return
    current_download_options = _service._download_options

    def download_options_with_hotmart(payload: dict[str, Any], root: Path, progress_hook):
        options = current_download_options(payload, root, progress_hook)
        token = payload.get("_hotmartAuthorizationToken")
        if token in {None, ""}:
            return options
        context = _authorization_context(token)
        options["cookiesfrombrowser"] = (context["browser"], None, None, None)
        headers = dict(options.get("http_headers") or {})
        headers["Referer"] = context["referer"]
        options["http_headers"] = headers
        return options

    download_options_with_hotmart._galaxy_hotmart_authorization = True  # type: ignore[attr-defined]
    _service._download_options = download_options_with_hotmart
    _AUTH_INSTALLED = True


def run_hotmart_course_provider_self_test() -> None:
    signed = "https://cdn.example.com/master.m3u8?Policy=abc&Signature=xyz&Key-Pair-Id=123"
    values = rank_hotmart_candidates(
        [
            HotmartMediaCandidate(signed, "application/vnd.apple.mpegurl", "network", "1"),
            HotmartMediaCandidate(signed, "application/vnd.apple.mpegurl", "performance", ""),
            HotmartMediaCandidate("https://cdn.example.com/video.mp4", "video/mp4", "dom", ""),
            HotmartMediaCandidate("blob:https://cdn.example.com/123", "video/mp4", "dom", ""),
        ]
    )
    assert values and values[0].url == signed
    assert len([item for item in values if item.url == signed]) == 1
    assert manifest_uses_drm("<ContentProtection schemeIdUri='urn:uuid:" + _WIDEVINE_UUID + "'/>", kind="dash")
    assert manifest_uses_drm("#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI=\"skd://key\"", kind="hls")
    assert not manifest_uses_drm("#EXTM3U\n#EXTINF:6,\nsegment.ts", kind="hls")


if __name__ == "__main__":
    run_hotmart_course_provider_self_test()
    print("Hotmart course provider self-test passed")
