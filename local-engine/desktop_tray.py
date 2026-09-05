from __future__ import annotations

import importlib.util
import sys
import threading
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

from desktop_hooks import (
    register_after_build_ui_hook,
    register_desktop_presenter,
    registered_after_build_ui_hooks,
    show_desktop_presenter,
)

TRAY_NAME = "GalaxyLocalEngine"
TRAY_ACTIONS = ("show", "hide", "downloads", "open-downloads", "pause-all", "exit")
_SKIP_START_FLAGS = {"--self-test", "--ui-smoke-test", "--version"}


def tray_platform_supported(platform: str | None = None) -> bool:
    """Return whether this release enables a tested native tray backend.

    Windows and macOS both use pystray's native operating-system backends.
    Linux intentionally remains fail-closed because AppIndicator/GTK/XOrg
    availability and Wayland behavior depend on the target desktop session.
    """
    value = str(platform or sys.platform).lower()
    return value.startswith("win") or value == "darwin"


def tray_dependency_available() -> bool:
    return importlib.util.find_spec("pystray") is not None and importlib.util.find_spec("PIL") is not None


def tray_should_start(*, platform: str | None = None, argv: tuple[str, ...] | None = None) -> bool:
    args = tuple(sys.argv[1:] if argv is None else argv)
    if any(flag in args for flag in _SKIP_START_FLAGS):
        return False
    if "--no-tray" in args:
        return False
    return tray_platform_supported(platform) and tray_dependency_available()


def _schedule(window, callback: Callable[[], None]) -> bool:
    try:
        window.after(0, callback)
        return True
    except Exception:
        return False


def _show_window(window) -> None:
    try:
        window.deiconify()
        window.lift()
        window.focus_force()
    except Exception:
        pass


def _hide_window(window) -> None:
    try:
        window.withdraw()
    except Exception:
        pass


def _show_downloads(window) -> None:
    """Open the existing task-center/download surface without creating another UI."""
    _show_window(window)
    try:
        show_desktop_presenter(window, "history")
    except Exception:
        # Lightweight tests and partially composed embedders may not install the
        # task-center presenter. Showing the main window is still a safe fallback.
        pass


def _open_download_folder(window) -> None:
    opener = getattr(window, "open_folder", None)
    if callable(opener):
        try:
            opener()
        except Exception:
            pass


def _pause_all_downloads(window) -> bool:
    """Pause the waiting queue first, then stop the active job resumably.

    Queue pause must happen before ``pause_active_job`` so that pause/resume state
    records the user's explicit Pause All intent and does not auto-release the
    queue when the active item is resumed later.
    """
    changed = False
    pause_queue = getattr(window, "set_queue_paused", None)
    if callable(pause_queue):
        try:
            pause_queue(True)
            changed = True
        except Exception:
            pass
    elif hasattr(window, "queue_paused"):
        try:
            window.queue_paused = True
            changed = True
        except Exception:
            pass

    pause_active = getattr(window, "pause_active_job", None)
    if callable(pause_active):
        try:
            changed = bool(pause_active()) or changed
        except Exception:
            pass
    return changed


def _exit_application(window) -> None:
    closer = getattr(window, "close_app", None)
    if callable(closer):
        closer()


def _tray_image():
    # Lazy imports keep Linux/headless policy tests from initializing a GUI
    # backend merely because the desktop module is imported.
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (8, 12, 20, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 60, 60), radius=15, fill=(20, 30, 48, 255), outline=(54, 215, 196, 255), width=3)
    draw.ellipse((14, 14, 50, 50), outline=(124, 108, 255, 255), width=5)
    draw.arc((20, 20, 44, 44), start=32, end=315, fill=(246, 248, 252, 255), width=5)
    draw.polygon(((39, 19), (50, 24), (42, 32)), fill=(54, 215, 196, 255))
    return image


def _pystray_icon_kwargs(platform: str) -> dict[str, object]:
    if platform != "darwin":
        return {}
    # pystray's Darwin detached integration must share the NSApplication that
    # drives the host GUI loop. macOS has one shared NSApplication per process;
    # resolving it after Tk has created the root binds pystray to that same app.
    from AppKit import NSApplication

    application = NSApplication.sharedApplication()
    if application is None:
        raise RuntimeError("macOS NSApplication is unavailable")
    return {"darwin_nsapplication": application}


@dataclass
class TrayState:
    available: bool
    active: bool = False
    error: str = ""


class WindowsPystrayProvider:
    """Small native-pystray adapter while Tk remains Galaxy's main loop.

    The historical class name is retained to avoid breaking external imports;
    the provider now owns both the tested Windows and macOS native backends.
    """

    def __init__(self, window, app_name: str, *, platform: str | None = None) -> None:
        self.window = window
        self.app_name = app_name
        self.platform = str(platform or sys.platform).lower()
        self.icon = None
        self.state = TrayState(available=True)
        self._stop_lock = threading.Lock()

    def _menu_callback(self, callback: Callable[[], None]) -> Callable[..., None]:
        def action(*_args: object) -> None:
            _schedule(self.window, callback)

        return action

    def _build_menu(self, pystray):
        return pystray.Menu(
            pystray.MenuItem(
                "打开 Galaxy",
                self._menu_callback(lambda: _show_window(self.window)),
                default=self.platform.startswith("win"),
            ),
            pystray.MenuItem("隐藏窗口", self._menu_callback(lambda: _hide_window(self.window))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("下载任务", self._menu_callback(lambda: _show_downloads(self.window))),
            pystray.MenuItem(
                "打开下载目录",
                self._menu_callback(lambda: _open_download_folder(self.window)),
            ),
            pystray.MenuItem("全部暂停", self._menu_callback(lambda: _pause_all_downloads(self.window))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出 Galaxy", self._menu_callback(self._request_exit)),
        )

    def start(self) -> bool:
        if self.state.active:
            return True
        try:
            import pystray

            self.icon = pystray.Icon(
                TRAY_NAME,
                _tray_image(),
                self.app_name,
                self._build_menu(pystray),
                **_pystray_icon_kwargs(self.platform),
            )
            # run_detached() is the supported integration path when another GUI
            # framework owns the main loop. On Darwin the shared NSApplication is
            # passed above; tray callbacks still enqueue all Tk mutations via
            # window.after() so UI work remains on the Tk thread.
            self.icon.run_detached()
            self.state.active = True
            self.state.error = ""
            return True
        except Exception as exc:  # noqa: BLE001
            self.icon = None
            self.state.active = False
            self.state.error = str(exc)[:240]
            return False

    def _request_exit(self) -> None:
        self.stop()
        _exit_application(self.window)

    def stop(self) -> None:
        with self._stop_lock:
            icon = self.icon
            self.icon = None
            self.state.active = False
        if icon is None:
            return
        try:
            icon.stop()
        except Exception:
            pass


class NullTrayProvider:
    def __init__(self, *, available: bool = False, error: str = "") -> None:
        self.state = TrayState(available=available, active=False, error=error)

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        self.state.active = False


def create_tray_provider(window, engine_module):
    if not tray_platform_supported():
        return NullTrayProvider(error="System tray backend is not enabled for this packaged platform")
    if not tray_dependency_available():
        return NullTrayProvider(error="pystray/Pillow are unavailable")
    return WindowsPystrayProvider(
        window,
        str(getattr(engine_module, "APP_NAME", "Galaxy Local Engine")),
        platform=sys.platform,
    )


def _install_tray_for_window(window, engine_module) -> None:
    provider = create_tray_provider(window, engine_module)
    window._galaxy_tray_provider = provider
    window._galaxy_tray_active = False

    if tray_should_start():
        window._galaxy_tray_active = bool(provider.start())

    def on_destroy(event) -> None:
        if getattr(event, "widget", None) is not window:
            return
        try:
            provider.stop()
        finally:
            window._galaxy_tray_active = False

    try:
        window.bind("<Destroy>", on_destroy, add="+")
    except Exception:
        pass


def install_desktop_tray(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_tray_installed", False):
        return window_cls

    register_after_build_ui_hook(
        window_cls,
        "desktop-system-tray",
        lambda window: _install_tray_for_window(window, engine_module),
        order=55,
    )

    original_bridge_status = window_cls.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        provider = getattr(window, "_galaxy_tray_provider", None)
        state = getattr(provider, "state", None)
        payload["systemTrayAvailable"] = bool(getattr(state, "available", False))
        payload["systemTrayActive"] = bool(getattr(state, "active", False))
        return payload

    window_cls.bridge_status = bridge_status
    window_cls._galaxy_desktop_tray_installed = True
    engine_module._galaxy_desktop_tray_installed = True
    return window_cls


def verify_windows_tray_dependencies() -> bool:
    """Import dependencies required by every currently enabled tray backend."""
    if not tray_platform_supported():
        return True
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
        if sys.platform == "darwin":
            from AppKit import NSApplication  # noqa: F401
    except Exception:
        return False
    return True


def run_desktop_tray_self_test() -> None:
    assert tray_platform_supported("win32") is True
    assert tray_platform_supported("darwin") is True
    assert tray_platform_supported("linux") is False
    assert TRAY_ACTIONS == ("show", "hide", "downloads", "open-downloads", "pause-all", "exit")
    assert tray_should_start(platform="win32", argv=("--self-test",)) is False
    assert tray_should_start(platform="darwin", argv=("--self-test",)) is False
    assert tray_should_start(platform="win32", argv=("--ui-smoke-test",)) is False
    assert tray_should_start(platform="darwin", argv=("--ui-smoke-test",)) is False
    assert tray_should_start(platform="win32", argv=("--no-tray",)) is False
    assert tray_should_start(platform="darwin", argv=("--no-tray",)) is False

    class Window:
        @staticmethod
        def bridge_status(_window=None):
            return {}

    engine = SimpleNamespace(EngineWindow=Window)
    install_desktop_tray(engine)
    assert "desktop-system-tray" in registered_after_build_ui_hooks(Window)
    assert Window._galaxy_desktop_tray_installed is True

    class ActionWindow:
        def __init__(self) -> None:
            self.shown = 0
            self.withdrawn = 0
            self.downloads_opened = 0
            self.folder_opened = 0
            self.queue_paused = False
            self.pause_active_calls = 0
            self.closed = 0

        def deiconify(self) -> None:
            self.shown += 1

        def lift(self) -> None:
            pass

        def focus_force(self) -> None:
            pass

        def withdraw(self) -> None:
            self.withdrawn += 1

        def open_folder(self) -> None:
            self.folder_opened += 1

        def set_queue_paused(self, paused: bool) -> bool:
            self.queue_paused = bool(paused)
            return self.queue_paused

        def pause_active_job(self) -> bool:
            assert self.queue_paused is True
            self.pause_active_calls += 1
            return True

        def close_app(self) -> None:
            self.closed += 1

    register_desktop_presenter(
        ActionWindow,
        "history",
        "tray-self-test",
        lambda window: setattr(window, "downloads_opened", window.downloads_opened + 1),
        order=1,
    )
    action_window = ActionWindow()
    _show_window(action_window)
    _hide_window(action_window)
    _show_downloads(action_window)
    _open_download_folder(action_window)
    assert _pause_all_downloads(action_window) is True
    _exit_application(action_window)
    assert action_window.shown == 2
    assert action_window.withdrawn == 1
    assert action_window.downloads_opened == 1
    assert action_window.folder_opened == 1
    assert action_window.queue_paused is True
    assert action_window.pause_active_calls == 1
    assert action_window.closed == 1
