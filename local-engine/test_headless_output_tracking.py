from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import headless_service
from headless_browser_cookies import install_headless_browser_cookie_support
from headless_output_tracking import (
    HeadlessOutputTrackingError,
    clear_output_tracking,
    install_headless_output_tracking,
    new_output_tracking_id,
    tracked_output_paths,
)


class HeadlessOutputTrackingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_headless_browser_cookie_support()
        install_headless_output_tracking()

    def test_tracking_id_is_bounded_hex_identifier(self) -> None:
        first = new_output_tracking_id()
        second = new_output_tracking_id()
        self.assertRegex(first, r"^[a-f0-9]{32}$")
        self.assertRegex(second, r"^[a-f0-9]{32}$")
        self.assertNotEqual(first, second)
        clear_output_tracking(first)
        clear_output_tracking(second)

    def test_invalid_tracking_id_is_rejected(self) -> None:
        with self.assertRaises(HeadlessOutputTrackingError):
            tracked_output_paths("../../outputs")

    def test_no_tracking_id_leaves_post_hooks_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            options = headless_service._download_options(
                {"browser": "none"},
                Path(directory),
                lambda _event: None,
            )
        self.assertNotIn("post_hooks", options)

    def test_final_post_hook_records_multiple_course_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first = root / "Lesson 01.mp4"
            second = root / "Lesson 02.mkv"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            tracking_id = new_output_tracking_id()
            try:
                options = headless_service._download_options(
                    {"browser": "chrome", "_outputTrackingId": tracking_id},
                    root,
                    lambda _event: None,
                )
                self.assertEqual(
                    options.get("cookiesfrombrowser"),
                    ("chrome", None, None, None),
                )
                hooks = options.get("post_hooks") or []
                self.assertEqual(len(hooks), 1)
                hooks[0](str(first))
                hooks[0](str(second))
                hooks[0](str(first))
                self.assertEqual(
                    tracked_output_paths(tracking_id),
                    [first.resolve(), second.resolve()],
                )
            finally:
                clear_output_tracking(tracking_id)

    def test_output_outside_download_root_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_directory:
            root = Path(directory).resolve()
            outside = Path(outside_directory).resolve() / "outside.mp4"
            outside.write_bytes(b"outside")
            tracking_id = new_output_tracking_id()
            try:
                options = headless_service._download_options(
                    {"_outputTrackingId": tracking_id},
                    root,
                    lambda _event: None,
                )
                hooks = options.get("post_hooks") or []
                self.assertEqual(len(hooks), 1)
                hooks[0](str(outside))
                self.assertEqual(tracked_output_paths(tracking_id), [])
            finally:
                clear_output_tracking(tracking_id)

    def test_existing_only_filters_removed_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "lesson.mp4"
            output.write_bytes(b"lesson")
            tracking_id = new_output_tracking_id()
            try:
                options = headless_service._download_options(
                    {"_outputTrackingId": tracking_id},
                    root,
                    lambda _event: None,
                )
                (options.get("post_hooks") or [])[0](str(output))
                output.unlink()
                self.assertEqual(tracked_output_paths(tracking_id), [])
                self.assertEqual(
                    tracked_output_paths(tracking_id, existing_only=False),
                    [output.resolve(strict=False)],
                )
            finally:
                clear_output_tracking(tracking_id)


if __name__ == "__main__":
    unittest.main()
