from __future__ import annotations

import asyncio
import importlib.util
import secrets
import threading
from dataclasses import dataclass
from typing import Any, Callable

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"
SESSION_INTERFACE = "org.freedesktop.portal.Session"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
DBUS_BUS_NAME = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
DBUS_INTERFACE = "org.freedesktop.DBus"
SHORTCUT_ID = "show-workbench"
SHORTCUT_DESCRIPTION = "Show Galaxy Local Engine"
PORTAL_REQUEST_TIMEOUT_SECONDS = 10.0

_XDG_MODIFIERS = {
    "Ctrl": "CTRL",
    "Alt": "ALT",
    "Shift": "SHIFT",
    "Super": "LOGO",
}
_XDG_KEYS = {
    "Space": "space",
    "Tab": "Tab",
    "Enter": "Return",
    "Escape": "Escape",
    "Home": "Home",
    "End": "End",
    "PageUp": "Prior",
    "PageDown": "Next",
    "Insert": "Insert",
    "Delete": "Delete",
    "Left": "Left",
    "Right": "Right",
    "Up": "Up",
    "Down": "Down",
}


@dataclass
class PortalHotkeyState:
    available: bool = False
    active: bool = False
    shortcut: str = ""
    error: str = ""


def linux_portal_dependencies_available() -> bool:
    return importlib.util.find_spec("dbus_fast") is not None


def linux_shortcut_to_xdg_trigger(shortcut: str) -> str:
    """Convert the normalized desktop preference to the XDG shortcut syntax.

    The preference layer owns validation. This converter deliberately accepts
    only its canonical modifier and key vocabulary so malformed values can never
    be widened while crossing the D-Bus boundary.
    """
    parts = [part.strip() for part in str(shortcut or "").split("+") if part.strip()]
    if len(parts) < 2:
        raise ValueError("Linux global shortcut is not configured")

    main_key = parts[-1]
    modifiers: list[str] = []
    for modifier in parts[:-1]:
        mapped = _XDG_MODIFIERS.get(modifier)
        if mapped is None:
            raise ValueError(f"Unsupported Linux shortcut modifier: {modifier}")
        modifiers.append(mapped)

    if len(main_key) == 1 and main_key.isascii() and main_key.isalpha():
        key = main_key.lower()
    elif len(main_key) == 1 and main_key.isascii() and main_key.isdigit():
        key = main_key
    elif main_key.startswith("F") and main_key[1:].isdigit() and 1 <= int(main_key[1:]) <= 24:
        key = main_key
    else:
        key = _XDG_KEYS.get(main_key, "")
    if not key:
        raise ValueError(f"Unsupported Linux shortcut key: {main_key}")
    return "+".join([*modifiers, key])


def _variant_value(value: Any) -> Any:
    return getattr(value, "value", value)


class LinuxPortalGlobalHotkeyProvider:
    """Register a configurable shortcut through XDG Desktop Portal.

    D-Bus and asyncio live on a dedicated daemon thread. The provider only marks
    itself available after the GlobalShortcuts portal answers its version query,
    and only marks itself active after BindShortcuts returns this shortcut in the
    bound subset. UI work is delegated to ``on_activate`` so Tk mutations remain
    scheduled by the desktop hotkey layer.
    """

    def __init__(self, window, shortcut: str, on_activate: Callable[[], None]) -> None:
        self.window = window
        self.shortcut = str(shortcut or "")
        self.on_activate = on_activate
        self.state = PortalHotkeyState(shortcut=self.shortcut)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._ready = threading.Event()
        self._stop_lock = threading.Lock()
        self._session_handle = ""
        self._request_waiters: dict[str, asyncio.Future] = {}
        self._request_backlog: dict[str, tuple[int, dict[str, Any]]] = {}

    def start(self, timeout: float = 12.0) -> bool:
        if self.state.active:
            return True
        if not self.shortcut:
            self.state.error = "Linux global hotkey is not configured"
            return False
        try:
            linux_shortcut_to_xdg_trigger(self.shortcut)
        except ValueError as exc:
            self.state.error = str(exc)[:240]
            return False
        if not linux_portal_dependencies_available():
            self.state.error = "dbus-fast is not installed"
            return False
        if self._thread is not None and self._thread.is_alive():
            return False

        self.state.available = False
        self.state.active = False
        self.state.error = ""
        self._session_handle = ""
        self._request_waiters.clear()
        self._request_backlog.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._thread_main, name="GalaxyLinuxPortalHotkey", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=max(0.5, timeout)):
            self.state.error = "Timed out while registering Linux portal hotkey"
            self.stop()
            return False
        return bool(self.state.active)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run_portal_session())
        except Exception as exc:  # noqa: BLE001
            if not self.state.error:
                self.state.error = str(exc)[:240]
            self.state.active = False
            self._ready.set()
        finally:
            self._loop = None
            self._stop_event = None
            self.state.active = False

    async def _call(self, bus, message):
        from dbus_fast.message import MessageType

        reply = await bus.call(message)
        if reply.message_type == MessageType.ERROR:
            detail = str(reply.body[0]) if reply.body else str(reply.error_name or "D-Bus call failed")
            raise RuntimeError(detail)
        return reply

    async def _add_match(self, bus, rule: str) -> None:
        from dbus_fast.message import Message

        await self._call(
            bus,
            Message(
                destination=DBUS_BUS_NAME,
                path=DBUS_PATH,
                interface=DBUS_INTERFACE,
                member="AddMatch",
                signature="s",
                body=[rule],
            ),
        )

    def _message_handler(self, message):
        from dbus_fast.message import MessageType

        if message.message_type != MessageType.SIGNAL:
            return False
        if message.interface == REQUEST_INTERFACE and message.member == "Response":
            code = int(message.body[0]) if message.body else 2
            results = message.body[1] if len(message.body) > 1 and isinstance(message.body[1], dict) else {}
            path = str(message.path or "")
            waiter = self._request_waiters.pop(path, None)
            if waiter is not None and not waiter.done():
                waiter.set_result((code, results))
            else:
                self._request_backlog[path] = (code, results)
            return False
        if message.interface == PORTAL_INTERFACE and message.member == "Activated":
            if len(message.body) >= 2:
                session_handle = str(message.body[0] or "")
                shortcut_id = str(message.body[1] or "")
                if session_handle == self._session_handle and shortcut_id == SHORTCUT_ID:
                    try:
                        self.on_activate()
                    except Exception:
                        # A UI teardown race must not terminate the D-Bus session.
                        return False
            return False
        return False

    async def _wait_for_request(self, request_path: str) -> tuple[int, dict[str, Any]]:
        cached = self._request_backlog.pop(request_path, None)
        if cached is not None:
            return cached
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        self._request_waiters[request_path] = waiter
        try:
            return await asyncio.wait_for(waiter, timeout=PORTAL_REQUEST_TIMEOUT_SECONDS)
        finally:
            self._request_waiters.pop(request_path, None)

    @staticmethod
    def _token(prefix: str) -> str:
        return f"{prefix}_{secrets.token_hex(8)}"

    async def _portal_version(self, bus) -> int:
        from dbus_fast.message import Message

        reply = await self._call(
            bus,
            Message(
                destination=PORTAL_BUS_NAME,
                path=PORTAL_PATH,
                interface=PROPERTIES_INTERFACE,
                member="Get",
                signature="ss",
                body=[PORTAL_INTERFACE, "version"],
            ),
        )
        if not reply.body:
            raise RuntimeError("GlobalShortcuts portal did not report a version")
        return int(_variant_value(reply.body[0]))

    async def _create_session(self, bus) -> str:
        from dbus_fast import Variant
        from dbus_fast.message import Message

        handle_token = self._token("galaxy_req")
        session_token = self._token("galaxy_session")
        reply = await self._call(
            bus,
            Message(
                destination=PORTAL_BUS_NAME,
                path=PORTAL_PATH,
                interface=PORTAL_INTERFACE,
                member="CreateSession",
                signature="a{sv}",
                body=[
                    {
                        "handle_token": Variant("s", handle_token),
                        "session_handle_token": Variant("s", session_token),
                    }
                ],
            ),
        )
        if not reply.body:
            raise RuntimeError("GlobalShortcuts CreateSession returned no request handle")
        request_path = str(reply.body[0])
        code, results = await self._wait_for_request(request_path)
        if code != 0:
            raise RuntimeError(f"GlobalShortcuts session request was denied ({code})")
        session_handle = str(_variant_value(results.get("session_handle", "")) or "")
        if not session_handle.startswith("/"):
            raise RuntimeError("GlobalShortcuts session response had no session handle")
        return session_handle

    async def _bind_shortcut(self, bus, session_handle: str) -> str:
        from dbus_fast import Variant
        from dbus_fast.message import Message

        preferred_trigger = linux_shortcut_to_xdg_trigger(self.shortcut)
        reply = await self._call(
            bus,
            Message(
                destination=PORTAL_BUS_NAME,
                path=PORTAL_PATH,
                interface=PORTAL_INTERFACE,
                member="BindShortcuts",
                signature="oa(sa{sv})sa{sv}",
                body=[
                    session_handle,
                    [
                        (
                            SHORTCUT_ID,
                            {
                                "description": Variant("s", SHORTCUT_DESCRIPTION),
                                "preferred_trigger": Variant("s", preferred_trigger),
                            },
                        )
                    ],
                    "",
                    {"handle_token": Variant("s", self._token("galaxy_bind"))},
                ],
            ),
        )
        if not reply.body:
            raise RuntimeError("GlobalShortcuts BindShortcuts returned no request handle")
        request_path = str(reply.body[0])
        code, results = await self._wait_for_request(request_path)
        if code != 0:
            raise RuntimeError(f"GlobalShortcuts binding was denied ({code})")

        shortcuts_value = _variant_value(results.get("shortcuts", []))
        for item in shortcuts_value if isinstance(shortcuts_value, (list, tuple)) else ():
            if not isinstance(item, (list, tuple)) or len(item) < 2 or str(item[0]) != SHORTCUT_ID:
                continue
            properties = item[1] if isinstance(item[1], dict) else {}
            description = str(_variant_value(properties.get("trigger_description", "")) or "").strip()
            return description or self.shortcut
        raise RuntimeError("GlobalShortcuts portal did not bind the requested shortcut")

    async def _close_session(self, bus) -> None:
        if not self._session_handle:
            return
        from dbus_fast.message import Message

        try:
            await self._call(
                bus,
                Message(
                    destination=PORTAL_BUS_NAME,
                    path=self._session_handle,
                    interface=SESSION_INTERFACE,
                    member="Close",
                ),
            )
        except Exception:
            # Session teardown is best-effort during desktop logout or portal exit.
            pass
        self._session_handle = ""

    async def _run_portal_session(self) -> None:
        from dbus_fast.aio import MessageBus

        bus = await MessageBus().connect()
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        bus.add_message_handler(self._message_handler)
        try:
            await self._add_match(bus, f"type='signal',interface='{REQUEST_INTERFACE}',member='Response'")
            await self._add_match(
                bus,
                f"type='signal',interface='{PORTAL_INTERFACE}',member='Activated',path='{PORTAL_PATH}'",
            )
            version = await self._portal_version(bus)
            if version < 1:
                raise RuntimeError(f"GlobalShortcuts portal version {version} is unsupported")
            self.state.available = True

            self._session_handle = await self._create_session(bus)
            actual_shortcut = await self._bind_shortcut(bus, self._session_handle)
            self.state.shortcut = actual_shortcut
            self.state.active = True
            self.state.error = ""
            self._ready.set()
            await self._stop_event.wait()
        finally:
            await self._close_session(bus)
            try:
                bus.disconnect()
            except Exception:
                pass
            self.state.active = False
            self._ready.set()

    def stop(self) -> None:
        with self._stop_lock:
            thread = self._thread
            loop = self._loop
            stop_event = self._stop_event
            self._thread = None
        if loop is not None and stop_event is not None:
            try:
                loop.call_soon_threadsafe(stop_event.set)
            except RuntimeError:
                pass
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=2.0)
        self.state.active = False


def run_linux_portal_hotkey_self_test() -> None:
    assert linux_shortcut_to_xdg_trigger("Ctrl+Shift+G") == "CTRL+SHIFT+g"
    assert linux_shortcut_to_xdg_trigger("Alt+Super+F12") == "ALT+LOGO+F12"
    assert linux_shortcut_to_xdg_trigger("Ctrl+PageDown") == "CTRL+Next"
    assert linux_shortcut_to_xdg_trigger("Super+1") == "LOGO+1"

    for invalid in ("", "G", "Control+G", "Ctrl+Mouse1"):
        rejected = False
        try:
            linux_shortcut_to_xdg_trigger(invalid)
        except ValueError:
            rejected = True
        assert rejected, f"Invalid XDG trigger input accepted: {invalid}"
