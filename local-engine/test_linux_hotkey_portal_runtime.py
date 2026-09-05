from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from contextlib import suppress

from desktop_linux_hotkey import (
    PORTAL_BUS_NAME,
    PORTAL_INTERFACE,
    PORTAL_PATH,
    PROPERTIES_INTERFACE,
    REQUEST_INTERFACE,
    SESSION_INTERFACE,
    SHORTCUT_DESCRIPTION,
    SHORTCUT_ID,
    LinuxPortalGlobalHotkeyProvider,
)

REQUEST_ROOT = "/org/freedesktop/portal/desktop/request/fake"
SESSION_PATH = "/org/freedesktop/portal/desktop/session/fake/galaxy"


def _variant_value(value):
    return getattr(value, "value", value)


class FakeGlobalShortcutsPortal:
    def __init__(self) -> None:
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.activation_sent = threading.Event()
        self.preferred_trigger = ""
        self.description = ""
        self.error = ""
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._bus = None
        self._request_index = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._thread_main, name="FakeGlobalShortcutsPortal", daemon=True)
        self._thread.start()
        if not self.ready.wait(5.0):
            raise RuntimeError("fake portal did not start")
        if self.error:
            raise RuntimeError(self.error)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            self.ready.set()

    async def _run(self) -> None:
        from dbus_fast.aio import MessageBus

        bus = await MessageBus().connect()
        self._bus = bus
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        bus.add_message_handler(self._handle_message)
        await bus.request_name(PORTAL_BUS_NAME)
        self.ready.set()
        try:
            await self._stop_event.wait()
        finally:
            with suppress(Exception):
                bus.disconnect()

    def _next_request_path(self) -> str:
        self._request_index += 1
        return f"{REQUEST_ROOT}/request_{self._request_index}"

    async def _emit_response(self, request_path: str, results: dict) -> None:
        from dbus_fast.message import Message

        await asyncio.sleep(0.02)
        await self._bus.send(
            Message.new_signal(
                request_path,
                REQUEST_INTERFACE,
                "Response",
                "ua{sv}",
                [0, results],
            )
        )

    async def _emit_bind_success(self, request_path: str) -> None:
        from dbus_fast import Variant
        from dbus_fast.message import Message

        await self._emit_response(
            request_path,
            {
                "shortcuts": Variant(
                    "a(sa{sv})",
                    [
                        (
                            SHORTCUT_ID,
                            {
                                "description": Variant("s", SHORTCUT_DESCRIPTION),
                                "trigger_description": Variant("s", "Ctrl+Alt+H"),
                            },
                        )
                    ],
                )
            },
        )
        await asyncio.sleep(0.05)
        await self._bus.send(
            Message.new_signal(
                PORTAL_PATH,
                PORTAL_INTERFACE,
                "Activated",
                "osta{sv}",
                [SESSION_PATH, SHORTCUT_ID, 1, {}],
            )
        )
        self.activation_sent.set()

    def _handle_message(self, message):
        from dbus_fast import MessageType, Variant
        from dbus_fast.message import Message

        if message.message_type != MessageType.METHOD_CALL:
            return False

        if message.interface == PROPERTIES_INTERFACE and message.member == "Get":
            if list(message.body or []) != [PORTAL_INTERFACE, "version"]:
                return Message.new_error(message, "org.freedesktop.DBus.Error.InvalidArgs", "unexpected property")
            return Message.new_method_return(message, "v", [Variant("u", 2)])

        if message.interface == PORTAL_INTERFACE and message.member == "CreateSession":
            request_path = self._next_request_path()
            asyncio.create_task(
                self._emit_response(
                    request_path,
                    {"session_handle": Variant("s", SESSION_PATH)},
                )
            )
            return Message.new_method_return(message, "o", [request_path])

        if message.interface == PORTAL_INTERFACE and message.member == "BindShortcuts":
            if not message.body or str(message.body[0]) != SESSION_PATH:
                return Message.new_error(message, "org.freedesktop.DBus.Error.InvalidArgs", "unexpected session")
            shortcuts = message.body[1]
            if not shortcuts or str(shortcuts[0][0]) != SHORTCUT_ID:
                return Message.new_error(message, "org.freedesktop.DBus.Error.InvalidArgs", "unexpected shortcut")
            properties = shortcuts[0][1]
            self.description = str(_variant_value(properties.get("description", "")))
            self.preferred_trigger = str(_variant_value(properties.get("preferred_trigger", "")))
            request_path = self._next_request_path()
            asyncio.create_task(self._emit_bind_success(request_path))
            return Message.new_method_return(message, "o", [request_path])

        if message.interface == SESSION_INTERFACE and message.member == "Close" and message.path == SESSION_PATH:
            self.closed.set()
            return Message.new_method_return(message)

        return False

    def stop(self) -> None:
        loop = self._loop
        stop_event = self._stop_event
        if loop is not None and stop_event is not None:
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(stop_event.set)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)


class WindowProbe:
    def __init__(self) -> None:
        self.activated = threading.Event()

    def activate(self) -> None:
        self.activated.set()


def main() -> int:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Linux GlobalShortcuts portal smoke must run on Linux")
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise RuntimeError("Linux GlobalShortcuts portal smoke requires dbus-run-session")

    watchdog = threading.Timer(20.0, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()

    portal = FakeGlobalShortcutsPortal()
    provider = None
    try:
        portal.start()
        window = WindowProbe()
        provider = LinuxPortalGlobalHotkeyProvider(window, "Ctrl+Alt+H", window.activate)
        if not provider.start(timeout=5.0):
            raise RuntimeError(f"Linux portal hotkey failed to start: {provider.state.error}")
        if not provider.state.available or not provider.state.active:
            raise RuntimeError("Linux portal hotkey did not become available and active")
        if provider.state.shortcut != "Ctrl+Alt+H":
            raise RuntimeError(f"unexpected bound shortcut label: {provider.state.shortcut}")
        if portal.description != SHORTCUT_DESCRIPTION:
            raise RuntimeError(f"unexpected shortcut description: {portal.description}")
        if portal.preferred_trigger != "CTRL+ALT+h":
            raise RuntimeError(f"unexpected XDG preferred trigger: {portal.preferred_trigger}")
        if not portal.activation_sent.wait(3.0) or not window.activated.wait(3.0):
            raise RuntimeError("portal Activated signal did not reach the workbench callback")

        provider.stop()
        if provider.state.active:
            raise RuntimeError("Linux portal hotkey remained active after stop")
        if not portal.closed.wait(2.0):
            raise RuntimeError("Linux portal session was not closed during provider stop")
        return 0
    finally:
        if provider is not None:
            provider.stop()
        portal.stop()
        watchdog.cancel()
        # Allow daemon D-Bus callbacks to finish before interpreter teardown.
        time.sleep(0.05)


if __name__ == "__main__":
    raise SystemExit(main())
