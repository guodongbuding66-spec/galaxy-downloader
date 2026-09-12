from __future__ import annotations

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
    def __init__(self, output_root: Path | None) -> None:
        self._quick_url_var = _Var("https://example.com/gallery")
        self._quick_state_var = _Var("")
        self._gallery_dl_archive_supported = True
        self._gallery_dl_archive_var = _Var(False)
        self._gallery_dl_resume_var = _Var(False)
        self._gallery_dl_date_after_var = _Var("")
        self._gallery_dl_date_before_var = _Var("")
        self._gallery_dl_rate_var = _Var("")
        self._gallery_dl_output_root = output_root
        self._gallery_dl_output_var = _Var(str(output_root) if output_root is not None else "")
        self._gallery_dl_fallback_button = _Button()
        self._gallery_dl_archive_check = _Control()
        self._gallery_dl_resume_check = _Control()
        self._gallery_dl_rate_entry = _Control()
        self._gallery_dl_output_entry = _Control()
        self._gallery_dl_output_browse_button = _Button()
        self._gallery_dl_output_reset_button = _Button()
        self._gallery_dl_date_after_entry = _Control()
        self._gallery_dl_date_before_entry = _Control()
        self.submissions: list[dict[str, object]] = []

    def submit_gallery_dl_task(self, source_url: str, **kwargs) -> str:
        self.submissions.append({"source_url": source_url, **kwargs})
        return "gallery-output-test-1"

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


class DesktopGalleryDlOutputDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        _DeferredThread.latest = None

    def test_output_root_capture_is_plain_absolute_path_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            absolute = type("Window", (), {"_gallery_dl_output_root": root})()
            relative = type("Window", (), {"_gallery_dl_output_root": Path("relative")})()
            self.assertEqual(desktop_gallery_dl.gallery_output_root(absolute), root)
            self.assertIsNone(desktop_gallery_dl.gallery_output_root(relative))
            self.assertIsNone(desktop_gallery_dl.gallery_output_root(object()))

    def test_directory_picker_updates_plain_path_on_ui_thread_and_cancel_preserves_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            window = _Window(None)
            with patch.object(desktop_gallery_dl.filedialog, "askdirectory", return_value=str(root)) as picker:
                changed = desktop_gallery_dl._choose_gallery_output_root(window, _Engine())
            self.assertTrue(changed)
            self.assertEqual(window._gallery_dl_output_root, root)
            self.assertEqual(window._gallery_dl_output_var.value, str(root))
            picker.assert_called_once()
            self.assertIs(picker.call_args.kwargs["mustexist"], True)
            self.assertIs(picker.call_args.kwargs["parent"], window)
            self.assertIn("自定义输出目录", str(window._quick_state_var.value))

            with patch.object(desktop_gallery_dl.filedialog, "askdirectory", return_value=""):
                changed = desktop_gallery_dl._choose_gallery_output_root(window, _Engine())
            self.assertFalse(changed)
            self.assertEqual(window._gallery_dl_output_root, root)

            desktop_gallery_dl._reset_gallery_output_root(window)
            self.assertIsNone(window._gallery_dl_output_root)
            self.assertEqual(window._gallery_dl_output_var.value, "")
            self.assertIn("默认下载目录", str(window._quick_state_var.value))

    def test_submit_captures_output_root_before_background_worker_and_forwards_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            other = root / "other"
            window = _Window(root)
            with (
                patch.object(desktop_gallery_dl, "tool_inventory", return_value={"galleryDlReady": True}),
                patch.object(desktop_gallery_dl.threading, "Thread", _DeferredThread),
            ):
                desktop_gallery_dl._submit_gallery_fallback(window, _Engine())

            thread = _DeferredThread.latest
            self.assertIsNotNone(thread)
            assert thread is not None
            self.assertTrue(thread.started)
            self.assertEqual(window._gallery_dl_output_entry.configs[-1]["state"], "disabled")
            self.assertEqual(window._gallery_dl_output_browse_button.states[-1], ("disabled",))
            self.assertEqual(window._gallery_dl_output_reset_button.states[-1], ("disabled",))

            # Changing the UI-side plain attribute after scheduling must not change this task.
            window._gallery_dl_output_root = other
            window._gallery_dl_output_var.fail = True
            thread.target()

            self.assertEqual(len(window.submissions), 1)
            submission = window.submissions[0]
            self.assertEqual(submission["output_root"], root)
            self.assertIsInstance(submission["output_root"], Path)
            self.assertEqual(window._gallery_dl_output_entry.configs[-1]["state"], "readonly")
            self.assertEqual(window._gallery_dl_output_browse_button.states[-1], ("!disabled",))
            self.assertEqual(window._gallery_dl_output_reset_button.states[-1], ("!disabled",))
            self.assertIn("自定义目录", str(window._quick_state_var.value))

    def test_default_output_preserves_legacy_submission_shape(self) -> None:
        window = _Window(None)
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
        self.assertNotIn("output_root", window.submissions[0])
        self.assertNotIn("自定义目录", str(window._quick_state_var.value))

    def test_desktop_bridge_forwards_selected_root_to_shared_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()

            class FakeExecutor:
                def __init__(self) -> None:
                    self.calls: list[tuple[str, dict[str, object]]] = []

                def submit(self, source_url: str, **kwargs) -> str:
                    self.calls.append((source_url, dict(kwargs)))
                    return "gdl-0123456789abcdef"

            executor = FakeExecutor()

            class EngineWindow:
                pass

            class Engine:
                pass

            Engine.EngineWindow = EngineWindow
            with (
                patch.object(desktop_gallery_dl, "install_gallery_dl_executor", return_value=executor),
                patch.object(desktop_gallery_dl, "register_after_build_ui_hook") as hook,
            ):
                desktop_gallery_dl.install_desktop_gallery_dl(Engine)

            window = EngineWindow()
            task_id = window.submit_gallery_dl_task(
                "https://example.com/gallery",
                output_root=root,
                max_files=17,
                archive_enabled=True,
                resume_enabled=True,
                date_after="2026-01-01",
                date_before="2026-02-01",
                rate_limit_mib=3.25,
            )
            self.assertEqual(task_id, "gdl-0123456789abcdef")
            self.assertEqual(len(executor.calls), 1)
            source, kwargs = executor.calls[0]
            self.assertEqual(source, "https://example.com/gallery")
            self.assertEqual(kwargs["output_root"], root)
            self.assertEqual(kwargs["max_files"], 17)
            self.assertTrue(kwargs["archive_enabled"])
            self.assertTrue(kwargs["resume_enabled"])
            self.assertEqual(kwargs["rate_limit_mib"], 3.25)
            hook.assert_called_once()

    def test_output_ui_uses_system_picker_readonly_field_and_accessible_44px_controls(self) -> None:
        source = (LOCAL_ENGINE / "desktop_gallery_dl.py").read_text(encoding="utf-8")
        for marker in (
            "from tkinter import filedialog",
            '"Output directory（可选）"',
            'text="选择文件夹"',
            'text="使用默认"',
            'state="readonly"',
            "readonlybackground=ui.PANEL_3",
            "takefocus=True",
            "height=44",
            "filedialog.askdirectory(",
            'submit_kwargs["output_root"] = output_root',
            "executor.submit(",
            "output_root=output_root",
        ):
            self.assertIn(marker, source)

        for forbidden in (
            "askopenfilename",
            "output_path",
            "gallery_dl_config",
            "cookie_file",
            "http_headers",
        ):
            self.assertNotIn(forbidden, source.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
