from __future__ import annotations

from typing import Any, Callable

import headless_service as _service

BROWSER_COOKIE_SOURCES = frozenset({"none", "edge", "chrome", "firefox", "brave"})


class HeadlessBrowserCookieError(_service.HeadlessServiceError):
    pass


def browser_cookie_source(value: object) -> str:
    source = str(value or "none").strip().lower()
    if source not in BROWSER_COOKIE_SOURCES:
        raise HeadlessBrowserCookieError("unsupported browser cookie source")
    return source


_ORIGINAL_DOWNLOAD_OPTIONS: Callable[..., dict[str, Any]] = _service._download_options
_ORIGINAL_SUBMIT = _service.HeadlessRuntime.submit
_INSTALLED = False


def _download_options_with_browser(payload: dict[str, Any], root, progress_hook) -> dict[str, Any]:
    source = browser_cookie_source(payload.get("browser"))
    options = _ORIGINAL_DOWNLOAD_OPTIONS(payload, root, progress_hook)
    if source != "none":
        # Use yt-dlp's native browser-cookie loader. No cookie values or arbitrary
        # cookie-file paths enter the Headless request contract.
        options["cookiesfrombrowser"] = (source, None, None, None)
    return options


def _submit_with_browser_validation(self, payload: dict[str, Any]):
    if isinstance(payload, dict):
        browser_cookie_source(payload.get("browser"))
    return _ORIGINAL_SUBMIT(self, payload)


def install_headless_browser_cookie_support() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _service._download_options = _download_options_with_browser
    _service.HeadlessRuntime.submit = _submit_with_browser_validation
    _INSTALLED = True
