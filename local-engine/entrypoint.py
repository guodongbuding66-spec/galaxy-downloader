from __future__ import annotations

import sys
import time
from urllib.parse import urlparse

import bridge
import web_document
from document_policy import install_document_policy, parse_web_document, should_try_web_document
from dynamic_document import parse_dynamic_web_document
from image_bridge import ImageBridge
from image_download import (
    _IMAGE_JOB_LOCK,
    _sniff_extension,
    _wechat_original_candidate,
    cancel_image_download_job,
)
from url_policy import is_public_http_url, validated_public_http_url

# Static document redirects and CDP request interception resolve this helper from
# the shared web_document module at request time. Install the fail-closed public
# URL boundary before either parser begins serving requests.
web_document._safe_http_url = is_public_http_url
install_document_policy()
_original_media_parse = bridge.parse_with_bundled_ytdlp


def _bad_source_url() -> dict[str, object]:
    return {
        "success": False,
        "code": "BAD_REQUEST",
        "status": 400,
        "error": "仅允许解析公网 HTTP(S) 链接，localhost、私网、保留地址和带凭据的 URL 已被阻止。",
    }


def _hybrid_parse(source_url: str, browser: str = "none"):
    """Prefer rich document parsing, then dynamic CDP, then yt-dlp.

    Static HTML remains the cheap first choice. When modern commerce/social pages
    return only a JS shell, the local engine renders the page with Edge/Chrome
    and feeds the resulting DOM back through the same document normalizer.
    """
    if not is_public_http_url(source_url):
        return _bad_source_url()

    if should_try_web_document(source_url):
        document = parse_web_document(source_url, browser)
        if document.get("success"):
            return document

        static_auth_required = document.get("code") == "AUTH_REQUIRED"
        dynamic = parse_dynamic_web_document(source_url, browser)
        if dynamic.get("success"):
            return dynamic
        if dynamic.get("code") == "BROWSER_COOKIE_UNAVAILABLE":
            return dynamic

        # Anonymous 401/403 must survive the dynamic attempt so the browser-side
        # bridge knows to retry explicitly with a logged-in browser profile.
        if static_auth_required and browser == "none":
            return document

    return _original_media_parse(source_url, browser)


# LocalBridge resolves this function from the bridge module at request time, so
# assigning it before engine.main() starts the HTTP server is sufficient and
# avoids duplicating the stable bridge implementation.
bridge._valid_source_url = is_public_http_url
bridge.parse_with_bundled_ytdlp = _hybrid_parse

# parse_job() and job_from_payload() resolve this global when a protocol/HTTP
# download request is received. Patching it once at process start keeps parse,
# bridge downloads, and galaxy-downloader:// launches on the same public-URL
# boundary without duplicating the engine's stable job normalization logic.
import engine  # noqa: E402  import after bridge/document policy installation

engine._validated_source_url = validated_public_http_url


# EngineWindow used to destroy Tk immediately after setting the media cancel
# event. A bundled yt-dlp/FFmpeg child or the separate image worker could still
# be writing at that moment, leaving an orphan process or partial file. Keep the
# window alive in a cancelling state until both internal job locks are idle.
_original_close_app = engine.EngineWindow.close_app


def _graceful_close_app(window: engine.EngineWindow) -> None:
    if getattr(window, "_galaxy_close_pending", False):
        return

    media_active = bool(window.running)
    image_active = _IMAGE_JOB_LOCK.locked()
    if not media_active and not image_active:
        _original_close_app(window)
        return

    setattr(window, "_galaxy_close_pending", True)
    if media_active:
        window.cancel_event.set()
    if image_active:
        cancel_image_download_job()
    window.set_status("Cancelling", "Waiting for local downloads to stop safely before exit")
    try:
        window.cancel_button.state(["disabled"])
    except Exception:
        pass

    def finish_when_idle() -> None:
        if window.running or _IMAGE_JOB_LOCK.locked():
            window.after(100, finish_when_idle)
            return
        _original_close_app(window)

    window.after(100, finish_when_idle)


engine.EngineWindow.close_app = _graceful_close_app


def _consume_open_protocol_request() -> bool:
    """Turn galaxy-downloader://open into a normal desktop-app launch.

    The installer already registers the galaxy-downloader protocol. Keeping this
    action outside engine.parse_job() avoids weakening the media download grammar
    while still giving the website a reliable "Open Local Engine" button.
    """
    for index, argument in enumerate(sys.argv[1:], start=1):
        if argument.startswith("--"):
            continue
        try:
            parsed = urlparse(argument)
        except ValueError:
            return False
        action = (parsed.netloc or parsed.path.lstrip("/")).lower()
        if parsed.scheme.lower() == engine.PROTOCOL and action == "open":
            del sys.argv[index]
            return True
        return False
    return False


def _run_image_self_test() -> None:
    sample = "https://mmbiz.qpic.cn/sz_mmbiz_jpg/demo/640?wx_fmt=jpeg&tp=webp&wxfrom=5"
    original = _wechat_original_candidate(sample)
    assert original is not None
    assert "/0?" in original
    assert "wx_fmt=jpeg" in original
    assert "tp=webp" not in original
    assert _sniff_extension(b"\xff\xd8\xff\xe0", "application/octet-stream", sample) == "jpg"
    assert _sniff_extension(b"RIFF\x00\x00\x00\x00WEBP", "", sample) == "webp"


def _cancel_image_worker_before_exit(timeout_seconds: float = 40.0) -> None:
    """Best-effort cleanup for non-GUI exits and unexpected main-loop returns."""
    if not _IMAGE_JOB_LOCK.locked():
        return
    cancel_image_download_job()
    deadline = time.monotonic() + timeout_seconds
    while _IMAGE_JOB_LOCK.locked() and time.monotonic() < deadline:
        time.sleep(0.05)


def main() -> int:
    _consume_open_protocol_request()
    if "--self-test" in sys.argv:
        _run_image_self_test()
        return engine.main()
    if "--version" in sys.argv:
        return engine.main()

    # A second loopback bridge handles direct image/original-asset downloads.
    # It never routes image bytes through Galaxy's public Cloudflare/Container
    # infrastructure; the user's machine connects to the source CDN directly.
    image_bridge = ImageBridge(engine.VERSION)
    started = image_bridge.start()
    try:
        return engine.main()
    finally:
        _cancel_image_worker_before_exit()
        if started:
            image_bridge.stop()


if __name__ == "__main__":
    raise SystemExit(main())
