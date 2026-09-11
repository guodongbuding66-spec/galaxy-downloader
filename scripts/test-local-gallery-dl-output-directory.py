#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from gallery_dl_executor import (  # noqa: E402
    GalleryDlExecutor,
    GalleryDlExecutorError,
    GalleryDlRunResult,
)


def wait_state(executor: GalleryDlExecutor, task_id: str, states: set[str], timeout: float = 4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = next((item for item in executor.snapshots() if item.task_id == task_id), None)
        if current is not None and current.state in states:
            return current
        time.sleep(0.02)
    current = next((item for item in executor.snapshots() if item.task_id == task_id), None)
    raise AssertionError(f"task did not reach {states}: {current}")


class GalleryDlOutputDirectoryContractTests(unittest.TestCase):
    @staticmethod
    def engine(root: Path):
        return SimpleNamespace(
            default_download_dir=lambda: root / "downloads",
            state_dir=lambda: root / "state",
        )

    def test_default_output_root_remains_galaxy_download_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seen: list[Path] = []

            def runner(_url, task_dir, _max_files, _archive, _after, _before, _cancel, progress):
                seen.append(Path(task_dir))
                progress("saved.jpg", 1, 1)
                return GalleryDlRunResult(0, 1, 1)

            executor = GalleryDlExecutor(self.engine(root), runner=runner, validator=lambda value: value)
            task_id = executor.submit("https://example.com/gallery")
            completed = wait_state(executor, task_id, {"completed"})

            expected_root = (root / "downloads" / "gallery-dl").resolve()
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0].parent, expected_root)
            self.assertEqual(seen[0].name, f"{task_id}-a1")
            self.assertNotIn(str(root), json.dumps(completed.__dict__, ensure_ascii=False))

    def test_explicit_output_root_is_used_without_touching_default_download_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custom = root / "chosen-output" / "项目 A"
            seen: list[Path] = []

            def runner(_url, task_dir, _max_files, _archive, _after, _before, _cancel, progress):
                seen.append(Path(task_dir))
                progress("saved.jpg", 1, 1)
                return GalleryDlRunResult(0, 1, 1)

            executor = GalleryDlExecutor(self.engine(root), runner=runner, validator=lambda value: value)
            task_id = executor.submit("https://example.com/gallery", output_root=custom)
            completed = wait_state(executor, task_id, {"completed"})

            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0].parent, (custom / "gallery-dl").resolve())
            self.assertEqual(seen[0].name, f"{task_id}-a1")
            self.assertTrue(seen[0].is_dir())
            self.assertFalse((root / "downloads").exists())
            serialized = json.dumps(completed.__dict__, ensure_ascii=False)
            self.assertNotIn(str(custom.resolve()), serialized)
            self.assertNotIn("项目 A", serialized)

    def test_retry_keeps_original_custom_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custom = root / "chosen-output"
            seen: list[Path] = []
            calls = {"count": 0}

            def runner(_url, task_dir, _max_files, _archive, _after, _before, _cancel, progress):
                calls["count"] += 1
                seen.append(Path(task_dir))
                if calls["count"] == 1:
                    return GalleryDlRunResult(5, 0, 0)
                progress("retry.jpg", 1, 1)
                return GalleryDlRunResult(0, 1, 1)

            executor = GalleryDlExecutor(self.engine(root), runner=runner, validator=lambda value: value)
            task_id = executor.submit("https://example.com/gallery", output_root=custom)
            self.assertEqual(wait_state(executor, task_id, {"failed"}).state, "failed")
            self.assertTrue(executor.retry(task_id).ok)
            self.assertEqual(wait_state(executor, task_id, {"completed"}).state, "completed")

            managed_root = (custom / "gallery-dl").resolve()
            self.assertEqual([path.parent for path in seen], [managed_root, managed_root])
            self.assertEqual([path.name for path in seen], [f"{task_id}-a1", f"{task_id}-a2"])

    def test_resume_retry_reuses_same_custom_managed_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custom = root / "resume-output"
            seen: list[Path] = []
            calls = {"count": 0}

            def runner(_url, task_dir, _max_files, _archive, _after, _before, _cancel, progress):
                calls["count"] += 1
                seen.append(Path(task_dir))
                marker = Path(task_dir) / "partial.part"
                if calls["count"] == 1:
                    marker.write_text("partial", encoding="utf-8")
                    return GalleryDlRunResult(5, 0, 0)
                self.assertEqual(marker.read_text(encoding="utf-8"), "partial")
                progress("completed.jpg", 1, 1)
                return GalleryDlRunResult(0, 1, 1)

            executor = GalleryDlExecutor(self.engine(root), runner=runner, validator=lambda value: value)
            task_id = executor.submit(
                "https://example.com/gallery",
                output_root=custom,
                resume_enabled=True,
            )
            self.assertEqual(wait_state(executor, task_id, {"failed"}).state, "failed")
            self.assertTrue(executor.retry(task_id).ok)
            self.assertEqual(wait_state(executor, task_id, {"completed"}).state, "completed")

            expected = (custom / "gallery-dl" / f"{task_id}-resume").resolve()
            self.assertEqual(seen, [expected, expected])

    def test_non_directory_output_root_is_rejected_before_task_is_queued(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "not-a-directory"
            invalid.write_text("file", encoding="utf-8")
            executor = GalleryDlExecutor(self.engine(root), runner=lambda *_args: None, validator=lambda value: value)

            with self.assertRaises(GalleryDlExecutorError):
                executor.submit("https://example.com/gallery", output_root=invalid)
            self.assertEqual(executor.snapshots(), ())


if __name__ == "__main__":
    unittest.main(verbosity=2)
