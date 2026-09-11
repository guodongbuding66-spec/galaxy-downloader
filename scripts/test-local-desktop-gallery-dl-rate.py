from __future__ import annotations

import math
import sys
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import desktop_gallery_dl  # noqa: E402


class _Var:
    def __init__(self, value) -> None:
        self.value = value
        self.calls = 0
        self.fail = False

    def get(self):
        self.calls += 1
        if self.fail:
            raise AssertionError("Tk variable was read after work left the UI thread")
        return self.value

    def set(self, value) -> None:
        self.value = value


class _Button:
    def __init__(self) -> None:
        self.states: list[tuple[str, ...]] = []

    def state(self, spec) -> tuple[str, ...]:
        value = tuple(spec)
        self.states.append(value)
        return value


class _Control:
    def __init__(self) -> None:
        self.configs: list[dict[str, object]] = []

    def configure(self, **kwargs) -> None:
        self.configs.append(dict(kwargs))


class _Window:
    def __init__(self, rate_value: object) -> None:
        self._quick_url_var = _Var("https://example.com/gallery")
        self._quick_state_var = _Var("")
        self._gallery_dl_archive_supported = True
        self._gallery_dl_archive_var = _Var(False)
        self._gallery_dl_resume_var = _Var(False)
        self._gallery_dl_date_after_var = _Var("")
        self._gallery_dl_date_before_var = _Var("")
        self._gallery_dl_rate_var = _Var(rate_value)
        self._gallery_dl_fallback_button = _Button()
        self._gallery_dl_archive_check = _Control()
        self._gallery_dl_resume_check = _Control()
        self._gallery_dl_rate_entry = _Control()
        self._gallery_dl_date_after_entry = _Control()
        self._gallery_dl_date_before_entry = _Control()
        self.submissions: list[dict[str, object]] = []

    def submit_gallery_dl_task(self, source_url: str, **kwargs) -> str:
        self.submissions.append({"source_url": source_url, **kwargs})
        return "gallery-rate-test-1"

    def winfo_exists(self) -> int:
        return 1

    def after(self, _delay: int, callback) -> None:
        callback()


class _DeferredThread:
    latest: "_DeferredThread | None" = None

    def __init__(self, *, target, name: str, daemon: bool) -> None:
        self.target = target
        self.name = name
        self.daemon = daemon
        self.started = False
        _DeferredThread.latest = self

    def start(self) -> None:
        self.started = True


class _Engine:
    @staticmethod
    def _validated_source_url(url: str) -> str:
        return url


class DesktopGalleryDlRateTests(unittest.TestCase):
    def setUp(self) -> None:
        _DeferredThread.latest = None

    def test_rate_parser_keeps_blank_unlimited_and_accepts_managed_bounds(self) -> None:
        for raw, expected in (
            ("", None),
            ("   ", None),
            ("0.1", 0.1),
            (" 3.25 ", 3.25),
            ("1024", 1024.0),
        ):
            window = type("Window", (), {"_gallery_dl_rate_var": _Var(raw)})()
            self.assertEqual(desktop_gallery_dl.gallery_rate_limit_mib(window), expected)
        self.assertIsNone(desktop_gallery_dl.gallery_rate_limit_mib(object()))

    def test_rate_parser_rejects_non_numeric_non_finite_and_out_of_range_values(self) -> None:
        invalid = (
            "500k",
            "1M-2M",
            "zero",
            "0",
            "-1",
            "0.0999",
            "1024.0001",
            str(math.nan),
            str(math.inf),
            "-Infinity",
        )
        for raw in invalid:
            window = type("Window", (), {"_gallery_dl_rate_var": _Var(raw)})()
            with self.subTest(rate=raw), self.assertRaises(ValueError):
                desktop_gallery_dl.gallery_rate_limit_mib(window)

    def test_rate_parser_fails_closed_when_tk_variable_disappears(self) -> None:
        class BrokenVar:
            @staticmethod
            def get():
                raise tk.TclError("gone")

        window = type("Window", (), {"_gallery_dl_rate_var": BrokenVar()})()
        self.assertIsNone(desktop_gallery_dl.gallery_rate_limit_mib(window))

    def test_submit_captures_numeric_rate_on_ui_thread_and_forwards_plain_number(self) -> None:
        window = _Window(" 3.25 ")
        with (
            patch.object(desktop_gallery_dl, "tool_inventory", return_value={"galleryDlReady": True}),
            patch.object(desktop_gallery_dl.threading, "Thread", _DeferredThread),
        ):
            desktop_gallery_dl._submit_gallery_fallback(window, _Engine())

        thread = _DeferredThread.latest
        self.assertIsNotNone(thread)
        assert thread is not None
        self.assertTrue(thread.started)
        self.assertEqual(window._gallery_dl_rate_var.calls, 1)
        self.assertEqual(window._gallery_dl_rate_entry.configs[-1]["state"], "disabled")

        window._gallery_dl_rate_var.fail = True
        thread.target()

        self.assertEqual(window._gallery_dl_rate_var.calls, 1)
        self.assertEqual(len(window.submissions), 1)
        submission = window.submissions[0]
        self.assertEqual(submission["source_url"], "https://example.com/gallery")
        self.assertEqual(submission["rate_limit_mib"], 3.25)
        self.assertIs(type(submission["rate_limit_mib"]), float)
        self.assertEqual(window._gallery_dl_rate_entry.configs[-1]["state"], "normal")
        self.assertIn("Rate ≤ 3.25 MiB/s", str(window._quick_state_var.value))

    def test_blank_rate_preserves_unlimited_submission_shape(self) -> None:
        window = _Window("  ")
        with (
            patch.object(desktop_gallery_dl, "tool_inventory", return_value={"galleryDlReady": True}),
            patch.object(desktop_gallery_dl.threading, "Thread", _DeferredThread),
        ):
            desktop_gallery_dl._submit_gallery_fallback(window, _Engine())

        thread = _DeferredThread.latest
        self.assertIsNotNone(thread)
        assert thread is not None
        thread.target()
        self.assertEqual(len(window.submissions), 1)
        self.assertNotIn("rate_limit_mib", window.submissions[0])
        self.assertNotIn("Rate ≤", str(window._quick_state_var.value))

    def test_invalid_rate_is_rejected_before_controls_disable_or_worker_start(self) -> None:
        window = _Window("500k")
        with (
            patch.object(desktop_gallery_dl, "tool_inventory", return_value={"galleryDlReady": True}),
            patch.object(desktop_gallery_dl.threading, "Thread", _DeferredThread),
        ):
            desktop_gallery_dl._submit_gallery_fallback(window, _Engine())

        self.assertIsNone(_DeferredThread.latest)
        self.assertEqual(window.submissions, [])
        self.assertEqual(window._gallery_dl_fallback_button.states, [])
        self.assertEqual(window._gallery_dl_rate_entry.configs, [])
        self.assertIn("Rate 设置无效", str(window._quick_state_var.value))

    def test_rate_ui_uses_native_accessible_input_and_no_raw_config_or_path_surface(self) -> None:
        source = (LOCAL_ENGINE / "desktop_gallery_dl.py").read_text(encoding="utf-8")
        for marker in (
            '"Rate · MiB/s（可选）"',
            "tk.StringVar(master=window, value=\"\")",
            "_gallery_dl_rate_var",
            "_gallery_dl_rate_entry",
            "height=44",
            "takefocus=True",
            "highlightcolor=ui.ACCENT",
            "0.1",
            "1024",
            "留空不限速",
            "rate_limit_mib",
        ):
            self.assertIn(marker, source)

        for forbidden in (
            "rate_path",
            "rate_config",
            "downloader_rate",
            "gallery_dl_config",
            "output_path",
        ):
            self.assertNotIn(forbidden, source.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
