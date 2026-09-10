from __future__ import annotations

import ast
import sys
import tempfile
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
    def __init__(self, value):
        self.value = value
        self.calls = 0
        self.fail = False

    def get(self):
        self.calls += 1
        if self.fail:
            raise AssertionError("Tk variable was read after submission left the UI thread")
        return self.value

    def set(self, value) -> None:
        self.value = value


class _Button:
    def __init__(self) -> None:
        self.states: list[tuple[str, ...]] = []

    def state(self, spec) -> tuple[str, ...]:
        self.states.append(tuple(spec))
        return tuple(spec)


class _Check:
    def __init__(self) -> None:
        self.configs: list[dict[str, object]] = []

    def configure(self, **kwargs) -> None:
        self.configs.append(dict(kwargs))


class _Window:
    def __init__(
        self,
        *,
        archive_supported: bool,
        archive_value: bool,
        resume_value: bool = True,
        date_after: str = " 2026-01-01 ",
        date_before: str = " 2026-02-01 ",
    ) -> None:
        self._quick_url_var = _Var("https://example.com/gallery")
        self._quick_state_var = _Var("")
        self._gallery_dl_archive_var = _Var(archive_value)
        self._gallery_dl_archive_supported = archive_supported
        self._gallery_dl_resume_var = _Var(resume_value)
        self._gallery_dl_date_after_var = _Var(date_after)
        self._gallery_dl_date_before_var = _Var(date_before)
        self._gallery_dl_fallback_button = _Button()
        self._gallery_dl_archive_check = _Check()
        self._gallery_dl_resume_check = _Check()
        self._gallery_dl_date_after_entry = _Check()
        self._gallery_dl_date_before_entry = _Check()
        self.submissions: list[dict[str, object]] = []

    def submit_gallery_dl_task(self, source_url: str, **kwargs) -> str:
        self.submissions.append({"source_url": source_url, **kwargs})
        return "gallery-test-1"

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


class DesktopGalleryDlTests(unittest.TestCase):
    def test_module_contract(self) -> None:
        desktop_gallery_dl.run_desktop_gallery_dl_self_test()

    def test_archive_capability_requires_valid_absolute_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()

            class GoodEngine:
                @staticmethod
                def state_dir() -> Path:
                    return root

            class MissingEngine:
                pass

            class NoneEngine:
                @staticmethod
                def state_dir():
                    return None

            class EmptyEngine:
                @staticmethod
                def state_dir() -> str:
                    return "  "

            class RelativeEngine:
                @staticmethod
                def state_dir() -> Path:
                    return Path("relative-state")

            class BrokenEngine:
                @staticmethod
                def state_dir():
                    raise RuntimeError("broken")

            self.assertTrue(desktop_gallery_dl.gallery_archive_ready(GoodEngine()))
            self.assertFalse(desktop_gallery_dl.gallery_archive_ready(MissingEngine()))
            self.assertFalse(desktop_gallery_dl.gallery_archive_ready(NoneEngine()))
            self.assertFalse(desktop_gallery_dl.gallery_archive_ready(EmptyEngine()))
            self.assertFalse(desktop_gallery_dl.gallery_archive_ready(RelativeEngine()))
            self.assertFalse(desktop_gallery_dl.gallery_archive_ready(BrokenEngine()))

    def test_archive_and_resume_requests_fail_closed_when_tk_variable_is_unavailable(self) -> None:
        class BrokenVar:
            @staticmethod
            def get():
                raise tk.TclError("gone")

        class BrokenWindow:
            _gallery_dl_archive_var = BrokenVar()
            _gallery_dl_resume_var = BrokenVar()

        self.assertFalse(desktop_gallery_dl.gallery_archive_requested(object()))
        self.assertFalse(desktop_gallery_dl.gallery_archive_requested(BrokenWindow()))
        self.assertFalse(desktop_gallery_dl.gallery_resume_requested(object()))
        self.assertFalse(desktop_gallery_dl.gallery_resume_requested(BrokenWindow()))

    def test_date_request_fails_closed_when_tk_variable_is_unavailable(self) -> None:
        class GoodVar:
            @staticmethod
            def get() -> str:
                return "2026-01-01"

        class BrokenVar:
            @staticmethod
            def get():
                raise tk.TclError("gone")

        class BrokenWindow:
            _gallery_dl_date_after_var = GoodVar()
            _gallery_dl_date_before_var = BrokenVar()

        self.assertEqual(desktop_gallery_dl.gallery_date_values(object()), (None, None))
        self.assertEqual(desktop_gallery_dl.gallery_date_values(BrokenWindow()), (None, None))

    def test_submit_captures_archive_resume_and_date_values_before_background_worker(self) -> None:
        window = _Window(archive_supported=True, archive_value=True, resume_value=True)

        class Engine:
            @staticmethod
            def _validated_source_url(url: str) -> str:
                return url

        with (
            patch.object(desktop_gallery_dl, "tool_inventory", return_value={"galleryDlReady": True}),
            patch.object(desktop_gallery_dl.threading, "Thread", _DeferredThread),
        ):
            desktop_gallery_dl._submit_gallery_fallback(window, Engine())

        thread = _DeferredThread.latest
        self.assertIsNotNone(thread)
        assert thread is not None
        self.assertTrue(thread.started)
        self.assertEqual(window._gallery_dl_archive_var.calls, 1)
        self.assertEqual(window._gallery_dl_resume_var.calls, 1)
        self.assertEqual(window._gallery_dl_date_after_var.calls, 1)
        self.assertEqual(window._gallery_dl_date_before_var.calls, 1)
        self.assertIn(("disabled",), window._gallery_dl_fallback_button.states)
        self.assertEqual(window._gallery_dl_archive_check.configs[-1]["state"], "disabled")
        self.assertEqual(window._gallery_dl_resume_check.configs[-1]["state"], "disabled")
        self.assertEqual(window._gallery_dl_date_after_entry.configs[-1]["state"], "disabled")
        self.assertEqual(window._gallery_dl_date_before_entry.configs[-1]["state"], "disabled")

        window._gallery_dl_archive_var.fail = True
        window._gallery_dl_resume_var.fail = True
        window._gallery_dl_date_after_var.fail = True
        window._gallery_dl_date_before_var.fail = True
        thread.target()

        self.assertEqual(len(window.submissions), 1)
        submission = window.submissions[0]
        self.assertEqual(submission["source_url"], "https://example.com/gallery")
        self.assertEqual(submission["max_files"], desktop_gallery_dl.MAX_GALLERY_DL_FILES)
        self.assertIs(type(submission["archive_enabled"]), bool)
        self.assertTrue(submission["archive_enabled"])
        self.assertIs(type(submission["resume_enabled"]), bool)
        self.assertTrue(submission["resume_enabled"])
        self.assertEqual(submission["date_after"], "2026-01-01")
        self.assertEqual(submission["date_before"], "2026-02-01")
        self.assertEqual(window._gallery_dl_archive_var.calls, 1)
        self.assertEqual(window._gallery_dl_resume_var.calls, 1)
        self.assertEqual(window._gallery_dl_date_after_var.calls, 1)
        self.assertEqual(window._gallery_dl_date_before_var.calls, 1)
        self.assertIn(("!disabled",), window._gallery_dl_fallback_button.states)
        self.assertEqual(window._gallery_dl_archive_check.configs[-1]["state"], "normal")
        self.assertEqual(window._gallery_dl_resume_check.configs[-1]["state"], "normal")
        self.assertEqual(window._gallery_dl_date_after_entry.configs[-1]["state"], "normal")
        self.assertEqual(window._gallery_dl_date_before_entry.configs[-1]["state"], "normal")
        self.assertIn("Archive 已启用", str(window._quick_state_var.value))
        self.assertIn("Resume 已启用", str(window._quick_state_var.value))
        self.assertIn("日期过滤已启用", str(window._quick_state_var.value))

    def test_submit_forces_archive_off_and_preserves_resume_off_and_empty_dates(self) -> None:
        window = _Window(
            archive_supported=False,
            archive_value=True,
            resume_value=False,
            date_after="  ",
            date_before="",
        )

        class Engine:
            @staticmethod
            def _validated_source_url(url: str) -> str:
                return url

        _DeferredThread.latest = None
        with (
            patch.object(desktop_gallery_dl, "tool_inventory", return_value={"galleryDlReady": True}),
            patch.object(desktop_gallery_dl.threading, "Thread", _DeferredThread),
        ):
            desktop_gallery_dl._submit_gallery_fallback(window, Engine())

        thread = _DeferredThread.latest
        self.assertIsNotNone(thread)
        assert thread is not None
        self.assertEqual(window._gallery_dl_archive_var.calls, 0)
        self.assertEqual(window._gallery_dl_resume_var.calls, 1)
        self.assertEqual(window._gallery_dl_date_after_var.calls, 1)
        self.assertEqual(window._gallery_dl_date_before_var.calls, 1)
        thread.target()
        self.assertEqual(len(window.submissions), 1)
        self.assertIs(type(window.submissions[0]["archive_enabled"]), bool)
        self.assertFalse(window.submissions[0]["archive_enabled"])
        self.assertIs(type(window.submissions[0]["resume_enabled"]), bool)
        self.assertFalse(window.submissions[0]["resume_enabled"])
        self.assertIsNone(window.submissions[0]["date_after"])
        self.assertIsNone(window.submissions[0]["date_before"])
        self.assertEqual(window._gallery_dl_archive_check.configs[-1]["state"], "disabled")
        self.assertEqual(window._gallery_dl_resume_check.configs[-1]["state"], "normal")
        self.assertEqual(window._gallery_dl_date_after_entry.configs[-1]["state"], "normal")
        self.assertEqual(window._gallery_dl_date_before_entry.configs[-1]["state"], "normal")
        self.assertNotIn("Resume 已启用", str(window._quick_state_var.value))
        self.assertNotIn("日期过滤已启用", str(window._quick_state_var.value))

    def test_archive_resume_and_date_ui_are_default_off_or_empty_and_accessible(self) -> None:
        source = (LOCAL_ENGINE / "desktop_gallery_dl.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("tk.BooleanVar(master=window, value=False)"), 2)
        self.assertGreaterEqual(source.count('tk.StringVar(master=window, value="")'), 2)
        self.assertGreaterEqual(source.count("tk.Checkbutton("), 2)
        self.assertIn("tk.Entry(", source)
        self.assertIn('text="Archive · 跳过已记录项"', source)
        self.assertIn('text="Resume · 重试复用断点"', source)
        self.assertIn('label="After"', source)
        self.assertIn('label="Before"', source)
        self.assertIn("takefocus=True", source)
        self.assertIn("height=44", source)
        self.assertIn("highlightcolor=ui.ACCENT", source)
        self.assertIn("archive_enabled=bool(archive_enabled)", source)
        self.assertIn("resume_enabled=bool(resume_enabled)", source)
        self.assertIn("date_after=date_after", source)
        self.assertIn("date_before=date_before", source)
        self.assertIn("HTTP Range", source)
        self.assertIn(".part", source)
        self.assertIn("YYYY-MM-DD", source)
        self.assertNotIn("archive_path", source.lower())
        self.assertNotIn("date_path", source.lower())
        self.assertNotIn("date_config", source.lower())
        self.assertNotIn("resume_path", source.lower())
        self.assertNotIn("part_directory", source.lower())
        self.assertNotIn("range_header", source.lower())

    def test_production_entrypoint_installs_desktop_gallery_dl(self) -> None:
        source = (LOCAL_ENGINE / "entrypoint.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        imported_names: set[str] = set()
        called_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "desktop_gallery_dl":
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called_names.append(node.func.id)

        self.assertIn("install_desktop_gallery_dl", imported_names)
        self.assertIn("run_desktop_gallery_dl_self_test", imported_names)
        self.assertEqual(called_names.count("install_desktop_gallery_dl"), 1)
        self.assertEqual(called_names.count("run_desktop_gallery_dl_self_test"), 1)
        self.assertIn("_galaxy_desktop_gallery_dl_installed", source)

    def test_hook_runs_after_quick_download_panel(self) -> None:
        gallery_source = (LOCAL_ENGINE / "desktop_gallery_dl.py").read_text(encoding="utf-8")
        quick_source = (LOCAL_ENGINE / "desktop_quick_download.py").read_text(encoding="utf-8")
        self.assertIn('"desktop-gallery-dl"', gallery_source)
        self.assertIn("order=47", gallery_source)
        self.assertIn('"desktop-quick-download"', quick_source)
        self.assertIn("order=40", quick_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
