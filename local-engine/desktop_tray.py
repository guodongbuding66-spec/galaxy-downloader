from __future__ import annotations

import importlib.util
import sys
import threading
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

from desktop_hooks import register_after_build_ui_hook, registered_after_build_ui_hooks

TRAY_NAME = "GalaxyLocalEngine"
_SKIP_START_FLAGS = {"--self-test", "--ui-smoke-test", "--version"}


def tray_platform_supported(platform: str | None = None) -> bool:
    """Return whether this release enables a tested native tray backend.

    The abstraction is deliberately platform-neutral, but the first shipping
    backend is Windows-only because Galaxy currently only publishes a signed-off
    Windows desktop package. macOS/Linux activation stays fail-closed until their
    packaging/main-loop gates are added.
    """
    value = str(platform or sys.platform).lower()
    return value.startswith("win")


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


def _open_download_folder(window) -> None:
    opener = getattr(window, "open_folder", None)
    if callable(opener):
        try:
            opener()
        except Exception:
            pass


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


@dataclass
class TrayState:
    available: bool
    active: bool = False
    error: str = ""


class WindowsPystrayProvider:
    """Small adapter that owns pystray while Tk remains Galaxy's main loop."""

    def __init__(self, window, app_name: str) -> None:
        self.window = window
        self.app_name = app_name
        self.icon = None
        self.state = TrayState(available=True)
        self._stop_lock = threading.Lock()

    def _menu_callback(self, callback: Callable[[], None]) -> Callable[..., None]:
        def action(*_args: object) -> None:
            _schedule(self.window, callback)

        return action

    def start(self) -> bool:
        if self.state.active:
            return True
        try:
            import pystray

            menu = pystray.Menu(
                pystray.MenuItem(
                    "打开 Galaxy",
                    self._menu_callback(lambda: _show_window(self.window)),
                    default=True,
                ),
                pystray.MenuItem("隐藏窗口", self._menu_callback(lambda: _hide_window(self.window))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "打开下载目录",
                    self._menu_callback(lambda: _open_download_folder(self.window)),
                ),
                pystray.MenuItem("退出 Galaxy", self._menu_callback(self._request_exit)),
            )
            self.icon = pystray.Icon(TRAY_NAME, _tray_image(), self.app_name, menu)
            # On Windows pystray explicitly supports detached integration with a
            # GUI framework main loop. Tk remains authoritative for all window
            # mutations; tray callbacks only enqueue work onto Tk via after().
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
    return WindowsPystrayProvider(window, str(getattr(engine_module, "APP_NAME", "Galaxy Local Engine")))


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
    """Import the actual packaged dependencies in Windows self-test mode."""
    if not tray_platform_supported():
        return True
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    return True


def run_desktop_tray_self_test() -> None:
    assert tray_platform_supported("win32") is True
    assert tray_platform_supported("linux") is False
    assert tray_platform_supported("darwin") is False
    assert tray_should_start(platform="win32", argv=("--self-test",)) is False
    assert tray_should_start(platform="win32", argv=("--ui-smoke-test",)) is False
    assert tray_should_start(platform="win32", argv=("--no-tray",)) is False

    class Window:
        @staticmethod
        def bridge_status(_window=None):
            return {}

    engine = SimpleNamespace(EngineWindow=Window)
    install_desktop_tray(engine)
    assert "desktop-system-tray" in registered_after_build_ui_hooks(Window)
    assert Window._galaxy_desktop_tray_installed is True
