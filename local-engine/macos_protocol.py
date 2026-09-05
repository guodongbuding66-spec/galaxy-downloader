from __future__ import annotations

import sys
import threading
from urllib.parse import urlparse

MACOS_URL_COMMAND = "::tk::mac::LaunchURL"


def _runtime_platform(value: str | None = None) -> str:
    return str(value or sys.platform).strip().lower()


def _present_window(window) -> None:
    try:
        window.deiconify()
        window.lift()
        window.focus_force()
    except Exception:  # noqa: BLE001 - desktop focus is best-effort
        return


def _protocol_action(raw_url: str, protocol: str) -> str:
    try:
        parsed = urlparse(str(raw_url or "").strip())
    except ValueError:
        return ""
    if parsed.scheme.lower() != str(protocol or "").lower():
        return ""
    return (parsed.netloc or parsed.path.lstrip("/")).strip().lower()


def _set_protocol_error(window, detail: str) -> None:
    setter = getattr(window, "set_status", None)
    if callable(setter):
        try:
            setter("Protocol request rejected", str(detail)[:220])
        except Exception:  # noqa: BLE001 - status reporting must not break event handling
            pass


def _handoff_protocol_job(engine_module, window, payload: dict[str, object]) -> None:
    def worker() -> None:
        try:
            handled = bool(engine_module.post_job_to_running_engine(payload))
        except Exception:  # noqa: BLE001 - fail closed when local bridge is unavailable
            handled = False
        if handled:
            return

        def report() -> None:
            _set_protocol_error(window, "Local bridge is unavailable")

        try:
            window.after(0, report)
        except Exception:  # noqa: BLE001
            report()

    threading.Thread(target=worker, daemon=True, name="galaxy-macos-protocol").start()


def handle_macos_url(engine_module, window, raw_url: str) -> bool:
    """Handle one macOS Launch Services URL on the Tk/UI thread.

    `galaxy-downloader://open` only raises the resident window. Download URLs are
    normalized through the existing engine parser and then handed back through
    the resident HTTP bridge on a worker thread. Reusing that bridge preserves
    queue, validation and single-instance semantics without blocking Tk.
    """
    action = _protocol_action(raw_url, getattr(engine_module, "PROTOCOL", ""))
    if not action:
        _set_protocol_error(window, "Unsupported URL scheme")
        return False

    _present_window(window)
    if action == "open":
        return True

    try:
        job = engine_module.parse_job(raw_url)
        payload = engine_module.job_to_payload(job)
    except Exception as exc:  # noqa: BLE001 - parser owns user-facing validation contract
        _set_protocol_error(window, str(exc))
        return False

    _handoff_protocol_job(engine_module, window, payload)
    return True


def register_macos_url_handler(engine_module, window) -> bool:
    """Register TkAqua's kAEGetURL/GURL callback for a live EngineWindow."""
    if _runtime_platform() != "darwin":
        return False

    createcommand = getattr(window, "createcommand", None)
    if not callable(createcommand):
        return False

    def launch_url(*urls: object) -> None:
        for raw in urls:
            handle_macos_url(engine_module, window, str(raw))

    try:
        createcommand(MACOS_URL_COMMAND, launch_url)
    except Exception as exc:  # noqa: BLE001 - older/non-Aqua Tk must fail closed
        setattr(window, "_galaxy_macos_protocol_error", str(exc))
        return False

    setattr(window, "_galaxy_macos_protocol_active", True)
    setattr(window, "_galaxy_macos_protocol_callback", launch_url)
    return True


def install_macos_protocol(engine_module, *, platform: str | None = None):
    if getattr(engine_module, "_galaxy_macos_protocol_installed", False):
        return engine_module.EngineWindow

    engine_module._galaxy_macos_protocol_installed = True
    enabled = _runtime_platform(platform) == "darwin"
    engine_module._galaxy_macos_protocol_enabled = enabled
    if not enabled:
        return engine_module.EngineWindow

    window_cls = engine_module.EngineWindow
    original_init = window_cls.__init__

    def init_with_macos_protocol(window, *args, **kwargs):
        original_init(window, *args, **kwargs)
        register_macos_url_handler(engine_module, window)

    window_cls.__init__ = init_with_macos_protocol
    return window_cls


def run_macos_protocol_self_test() -> None:
    assert _protocol_action("galaxy-downloader://open", "galaxy-downloader") == "open"
    assert (
        _protocol_action(
            "galaxy-downloader://download?url=https%3A%2F%2Fexample.com%2Fdemo.mp4",
            "galaxy-downloader",
        )
        == "download"
    )
    assert _protocol_action("https://example.com", "galaxy-downloader") == ""
