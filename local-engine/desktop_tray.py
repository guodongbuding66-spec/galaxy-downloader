from __future__ import annotations

import importlib.util
import os
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
LINUX_TRAY_BACKEND = "appindicator"
LINUX_TRAY_READY_TIMEOUT_SECONDS = 5.0
_SKIP_START_FLAGS = {"--self-test", "--ui-smoke-test", "--version"}


def _platform(value: str | None = None) -> str:
    return str(value or sys.platform).lower()


def _is_linux(platform: str | None = None) -> bool:
    return _platform(platform).startswith("linux")


def tray_platform_supported(platform: str | None = None) -> bool:
    """Return whether Galaxy has an implementation for this desktop platform."""
    value = _platform(platform)
    return value.startswith("win") or value == "darwin" or value.startswith("linux")


def _linux_appindicator_available() -> bool:
    """Check the GI/AppIndicator runtime without importing pystray itself.

    Importing pystray selects its backend exactly once. Keeping this probe on the
    GI layer lets the real Linux provider force AppIndicator before pystray is
    imported, so we never silently fall back to XOrg's menu-limited backend.
    """
    try:
        if importlib.util.find_spec("gi") is None:
            return False
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401

        try:
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3  # noqa: F401
        except (ImportError, ValueError):
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3  # noqa: F401
    except Exception:
        return False
    return True


def tray_dependency_available(platform: str | None = None) -> bool:
    try:
        common = importlib.util.find_spec("pystray") is not None and importlib.util.find_spec("PIL") is not None
    except (ImportError, ValueError):
        return False
    if not common:
        return False
    return _linux_appindicator_available() if _is_linux(platform) else True


def tray_should_start(*, platform: str | None = None, argv: tuple[str, ...] | None = None) -> bool:
    args = tuple(sys.argv[1:] if argv is None else argv)
    if any(flag in args for flag in _SKIP_START_FLAGS):
        return False
    if "--no-tray" in args:
        return False
    return tray_platform_supported(platform) and tray_dependency_available(platform)


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
            # Tray callbacks are optional convenience controls; a queue-control
            # failure must not crash the UI thread or prevent active-job pause.
            pass
    elif hasattr(window, "queue_paused"):
        try:
            window.queue_paused = True
            changed = True
        except Exception:
            # A foreign/partial EngineWindow may expose a read-only compatibility
            # attribute. Continue so the independently available active pause runs.
            pass

    pause_active = getattr(window, "pause_active_job", None)
    if callable(pause_active):
        try:
            changed = bool(pause_active()) or changed
        except Exception:
            # Active pause is intentionally fail-soft from the tray boundary;
            # download-policy code owns error/status reporting for the real job.
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


def _import_pystray(platform: str):
    if _is_linux(platform):
        # AppIndicator is the only Linux backend with the complete menu contract
        # needed by Galaxy. Do not permit pystray to fall back to XOrg, whose
        # backend supports only a default action and would make Pause All/Exit lie.
        os.environ["PYSTRAY_BACKEND"] = LINUX_TRAY_BACKEND
    import pystray

    return pystray


@dataclass
class TrayState:
    available: bool
    active: bool = False
    error: str = ""


class WindowsPystrayProvider:
    """Native pystray adapter for Windows and macOS while Tk owns the main loop.

    The historical class name is retained to avoid breaking external imports.
    Linux uses ``LinuxAppIndicatorProvider`` because its GObject loop cannot be
    detached into Tk in the same way.
    """

    def __init__(self, window, app_name: str, *, platform: str | None = None) -> None:
        self.window = window
        self.app_name = app_name
        self.platform = _platform(platform)
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
            pystray = _import_pystray(self.platform)
            self.icon = pystray.Icon(
                TRAY_NAME,
                _tray_image(),
                self.app_name,
                self._build_menu(pystray),
                **_pystray_icon_kwargs(self.platform),
            )
            # run_detached() is the supported integration path when another GUI
            # framework owns a compatible native main loop. On Darwin the shared
            # NSApplication is passed above; callbacks still enqueue Tk mutations.
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


class LinuxAppIndicatorProvider(WindowsPystrayProvider):
    """Run pystray's AppIndicator/GObject loop beside Tk on Linux.

    pystray documents that GTK/AppIndicator ``run_detached`` only integrates with
    GObject-based GUI toolkits. Galaxy uses Tk, so the indicator owns a dedicated
    daemon thread while all tray callbacks continue to marshal back through
    ``window.after`` onto Tk's main thread.
    """

    def __init__(self, window, app_name: str) -> None:
        super().__init__(window, app_name, platform="linux")
        self._loop_thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._loop_error = ""

    def start(self) -> bool:
        if self.state.active:
            return True
        self._ready.clear()
        self._loop_error = ""
        try:
            pystray = _import_pystray(self.platform)
            if not bool(getattr(pystray.Icon, "HAS_MENU", False)):
                raise RuntimeError("Linux tray backend does not provide menus")
            self.icon = pystray.Icon(
                TRAY_NAME,
                _tray_image(),
                self.app_name,
                self._build_menu(pystray),
            )

            icon = self.icon

            def setup(ready_icon) -> None:
                try:
                    ready_icon.visible = True
                except Exception as exc:  # noqa: BLE001
                    self._loop_error = str(exc)[:240]
                    try:
                        ready_icon.stop()
                    except Exception:
                        pass
                finally:
                    self._ready.set()

            def run_loop() -> None:
                try:
                    icon.run(setup=setup)
                except Exception as exc:  # noqa: BLE001
                    self._loop_error = str(exc)[:240]
                    self._ready.set()

            self._loop_thread = threading.Thread(
                target=run_loop,
                name="GalaxyTrayAppIndicator",
                daemon=True,
            )
            self._loop_thread.start()
            if not self._ready.wait(LINUX_TRAY_READY_TIMEOUT_SECONDS):
                raise RuntimeError("Linux AppIndicator backend did not become ready")
            if self._loop_error:
                raise RuntimeError(self._loop_error)
            if not bool(getattr(icon, "visible", False)):
                raise RuntimeError("Linux AppIndicator backend is not visible")
            self.state.active = True
            self.state.error = ""
            return True
        except Exception as exc:  # noqa: BLE001
            self.state.active = False
            self.state.error = str(exc)[:240]
            self.stop()
            return False

    def stop(self) -> None:
        thread = self._loop_thread
        self._loop_thread = None
        super().stop()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)


class NullTrayProvider:
    def __init__(self, *, available: bool = False, error: str = "") -> None:
        self.state = TrayState(available=available, active=False, error=error)

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        self.state.active = False


def create_tray_provider(window, engine_module):
    platform = _platform()
    if not tray_platform_supported(platform):
        return NullTrayProvider(error="System tray backend is not enabled for this packaged platform")
    if not tray_dependency_available(platform):
        error = "pystray/Pillow are unavailable"
        if _is_linux(platform):
            error = "Linux AppIndicator GI runtime is unavailable"
        return NullTrayProvider(error=error)
    app_name = str(getattr(engine_module, "APP_NAME", "Galaxy Local Engine"))
    if _is_linux(platform):
        return LinuxAppIndicatorProvider(window, app_name)
    return WindowsPystrayProvider(window, app_name, platform=platform)


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
    """Legacy source/package check for the Windows/macOS pystray dependencies."""
    try:
        if importlib.util.find_spec("pystray") is None or importlib.util.find_spec("PIL") is None:
            return False
        if sys.platform == "darwin":
            from AppKit import NSApplication  # noqa: F401
    except Exception:
        return False
    return True


def verify_linux_tray_dependencies() -> bool:
    """Verify the complete Linux AppIndicator backend, never the XOrg fallback."""
    if not _is_linux():
        return True
    if not tray_dependency_available("linux"):
        return False
    try:
        pystray = _import_pystray("linux")
        return bool(getattr(pystray.Icon, "HAS_MENU", False)) and "appindicator" in str(pystray.Icon.__module__).lower()
    except Exception:
        return False


def run_desktop_tray_self_test() -> None:
    assert tray_platform_supported("win32") is True
    assert tray_platform_supported("darwin") is True
    assert tray_platform_supported("linux") is True
    assert TRAY_ACTIONS == ("show", "hide", "downloads", "open-downloads", "pause-all", "exit")
    assert tray_should_start(platform="win32", argv=("--self-test",)) is False
    assert tray_should_start(platform="darwin", argv=("--self-test",)) is False
    assert tray_should_start(platform="linux", argv=("--self-test",)) is False
    assert tray_should_start(platform="win32", argv=("--ui-smoke-test",)) is False
    assert tray_should_start(platform="darwin", argv=("--ui-smoke-test",)) is False
    assert tray_should_start(platform="linux", argv=("--ui-smoke-test",)) is False
    assert tray_should_start(platform="win32", argv=("--no-tray",)) is False
    assert tray_should_start(platform="darwin", argv=("--no-tray",)) is False
    assert tray_should_start(platform="linux", argv=("--no-tray",)) is False

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
