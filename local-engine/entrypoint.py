from __future__ import annotations

import sys
import time
from urllib.parse import urlparse

import bridge
import image_download
import web_document
from archive_policy import install_archive_policy
from bridge_submission_policy import StructuredLocalBridge
from desktop_extras import install_desktop_extras
from desktop_layer_compat import install_desktop_layer_compat
from desktop_manager import install_desktop_manager
from desktop_runtime import install_desktop_runtime
from desktop_ui import install_desktop_ui
from document_policy import (
    install_document_policy,
    parse_web_document,
    prefer_media_first,
    should_try_web_document,
)
from dynamic_document import parse_dynamic_web_document
from failure_policy import run_failure_policy_self_test
from image_archive_policy import install_image_archive_policy
from image_bridge import ImageBridge
from image_download import (
    _IMAGE_JOB_LOCK,
    _sniff_extension,
    _wechat_original_candidate,
    cancel_image_download_job,
)
from job_history import install_history_policy, run_history_self_test
from job_queue import install_job_queue_policy
from media_policy import install_media_policy
from queue_controls import install_queue_controls, run_queue_controls_self_test
from recovery_display import install_recovery_display, run_recovery_display_self_test
from recovery_policy import install_recovery_policy, run_recovery_self_test
from runtime_health import install_runtime_health, run_runtime_health_self_test
from task_center import install_task_center, run_task_center_self_test
from url_policy import is_public_http_url, validated_public_http_url
from workspace_policy import install_workspace_policy, run_workspace_self_test

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


def _document_fallback(source_url: str, browser: str):
    if not should_try_web_document(source_url):
        return None

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
    return None


def _hybrid_parse(source_url: str, browser: str = "none"):
    """Use the correct parser order for media, documents and mixed social posts.

    Explicit document/photo routes use the document parser first. Ambiguous
    social post routes (Instagram /p/, X status, Reddit comments, Threads, etc.)
    are media-first so a real video is never replaced by page-wide image assets.
    If yt-dlp finds no playable media, the document parser still gets a chance to
    return a genuine carousel/photo post.
    """
    if not is_public_http_url(source_url):
        return _bad_source_url()

    if prefer_media_first(source_url):
        media = _original_media_parse(source_url, browser)
        if media.get("success"):
            return media
        document = _document_fallback(source_url, browser)
        if document is not None:
            return document
        return media

    document = _document_fallback(source_url, browser)
    if document is not None:
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
# Policy order matters: archive/media fields extend Job first; workspace owns
# persistent output/transport defaults; recovery then adds optional per-job
# transport overrides without mutating those defaults. The queue captures that
# final Job type; queue/history/runtime policies wrap execution; presentation is
# installed last before the first Tk instance exists.
install_archive_policy(engine)
install_media_policy(engine)
install_workspace_policy(engine)
install_recovery_policy(engine)
install_job_queue_policy(engine)
install_queue_controls(engine)
install_history_policy(engine)
install_runtime_health(engine)
install_image_archive_policy(image_download)
install_desktop_ui(engine)
# The 0.14 shell moved queue/history presentation into Task Center, while the
# 0.11-0.13 wrappers still own several useful controls. Keep their private
# integration points explicit until those wrappers are flattened completely.
install_desktop_layer_compat(engine)
install_desktop_extras(engine)
install_desktop_manager(engine)
install_desktop_runtime(engine)
install_recovery_display(engine)
install_task_center(engine)

# A protocol handoff that reaches an already-running bridge but gets a 4xx (for
# example, a full queue) must still count as "the resident instance handled the
# launch". Otherwise engine.main() starts a second Tk process which can never
# bind port 17836. The website gets the actual 4xx directly and can show it; the
# protocol helper's responsibility is only single-instance coordination.
_original_protocol_handoff = engine.post_job_to_running_engine


def _single_instance_protocol_handoff(payload: dict[str, object], timeout: float = 0.8) -> bool:
    if _original_protocol_handoff(payload, timeout):
        return True
    return engine.bridge_is_running(timeout=min(max(timeout, 0.1), 0.8))


engine.post_job_to_running_engine = _single_instance_protocol_handoff


# EngineWindow used to destroy Tk immediately after setting the media cancel
# event. A bundled yt-dlp/FFmpeg child or the separate image worker could still
# be writing at that moment, leaving an orphan process or partial file. Keep the
# window alive in a cancelling state until both internal job locks are idle.
_original_close_app = engine.EngineWindow.close_app


def _graceful_close_app(window: engine.EngineWindow) -> None:
    if getattr(window, "_galaxy_close_pending", False):
        return

    clear_queue = getattr(window, "clear_queued_jobs", None)
    if callable(clear_queue):
        clear_queue()

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
    assert getattr(engine.EngineWindow, "_galaxy_queue_enabled", False) is True
    assert getattr(engine.EngineWindow, "_galaxy_queue_controls_installed", False) is True
    assert getattr(engine.EngineWindow, "_galaxy_history_installed", False) is True
    assert getattr(engine.EngineWindow, "_galaxy_runtime_health_installed", False) is True
    assert getattr(engine.EngineWindow, "_galaxy_desktop_ui_installed", False) is True
    assert getattr(engine.EngineWindow, "_galaxy_desktop_layer_compat_installed", False) is True
    assert getattr(engine.EngineWindow, "_galaxy_desktop_extras_installed", False) is True
    assert getattr(engine.EngineWindow, "_galaxy_desktop_manager_installed", False) is True
    assert getattr(engine.EngineWindow, "_galaxy_desktop_runtime_installed", False) is True
    assert getattr(engine.EngineWindow, "_galaxy_recovery_display_installed", False) is True
    assert getattr(engine.EngineWindow, "_galaxy_task_center_installed", False) is True
    assert getattr(engine, "_galaxy_archive_policy_installed", False) is True
    assert getattr(engine, "_galaxy_media_policy_installed", False) is True
    assert getattr(engine, "_galaxy_workspace_policy_installed", False) is True
    assert getattr(engine, "_galaxy_recovery_policy_installed", False) is True
    assert getattr(engine, "_galaxy_runtime_health_installed", False) is True
    assert getattr(engine, "_galaxy_desktop_layer_compat_installed", False) is True
    assert getattr(engine, "_galaxy_recovery_display_installed", False) is True
    assert getattr(engine, "_galaxy_task_center_installed", False) is True
    assert getattr(image_download, "_galaxy_image_archive_policy_installed", False) is True
    assert engine.LocalBridge is StructuredLocalBridge
    assert engine.post_job_to_running_engine is _single_instance_protocol_handoff
    run_queue_controls_self_test()
    run_failure_policy_self_test()
    run_recovery_self_test()
    run_recovery_display_self_test()
    run_history_self_test()
    run_workspace_self_test()
    run_runtime_health_self_test()
    run_task_center_self_test()


def _run_ui_smoke_test() -> int:
    """Construct the fully wrapped Tk UI and exit deterministically.

    This mode exists for Windows CI and packaged-EXE validation. It catches
    failures that `--self-test` cannot see because self-test does not instantiate
    Tk widgets. A PyInstaller `--windowed` exception may keep an error dialog
    alive, so CI runs this mode with a hard timeout rather than treating process
    liveness as success.
    """
    app = engine.EngineWindow(None)
    app.withdraw()
    app.update_idletasks()
    app.after(100, app.close_app)
    app.mainloop()
    return 0


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
    if "--ui-smoke-test" in sys.argv:
        return _run_ui_smoke_test()

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
