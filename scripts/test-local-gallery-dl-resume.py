#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import gallery_dl_executor as executor_module  # noqa: E402
from gallery_dl_executor import (  # noqa: E402
    GalleryDlExecutor,
    GalleryDlExecutorError,
    GalleryDlRunResult,
    _run_managed_gallery_dl,
    _task_directory,
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


class GalleryDlResumeContractTests(unittest.TestCase):
    def engine(self, root: Path):
        return SimpleNamespace(
            default_download_dir=lambda: root / "downloads",
            state_dir=lambda: root / "state",
        )

    def test_resume_requires_strict_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executor = GalleryDlExecutor(
                self.engine(root),
                runner=lambda *_args: GalleryDlRunResult(0, 1, 1),
                validator=lambda value: value,
            )
            for value in ("true", 1, 0, None, [], {}):
                with self.subTest(value=value), self.assertRaises(GalleryDlExecutorError):
                    executor.submit(
                        "https://example.com/gallery",
                        resume_enabled=value,  # type: ignore[arg-type]
                    )

    def test_default_retry_still_uses_distinct_attempt_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_dirs: list[Path] = []

            def runner(_url, task_dir, _max_files, _archive, _after, _before, _cancel, _progress):
                task_dirs.append(task_dir)
                if len(task_dirs) == 1:
                    return GalleryDlRunResult(4, 1, 0)
                return GalleryDlRunResult(0, 1, 1)

            executor = GalleryDlExecutor(self.engine(root), runner=runner, validator=lambda value: value)
            task_id = executor.submit("https://example.com/gallery")
            wait_state(executor, task_id, {"failed"})
            self.assertTrue(executor.retry(task_id).ok)
            wait_state(executor, task_id, {"completed"})

            self.assertEqual(len(task_dirs), 2)
            self.assertNotEqual(task_dirs[0], task_dirs[1])
            self.assertEqual(task_dirs[0].name, f"{task_id}-a1")
            self.assertEqual(task_dirs[1].name, f"{task_id}-a2")

    def test_resume_initial_zero_files_is_still_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executor = GalleryDlExecutor(
                self.engine(root),
                runner=lambda *_args: GalleryDlRunResult(0, 0, 0),
                validator=lambda value: value,
            )
            task_id = executor.submit("https://example.com/gallery", resume_enabled=True)
            failed = wait_state(executor, task_id, {"failed"})
            self.assertIn("没有保存任何可下载文件", failed.detail)
            self.assertIn("retry", failed.actions)

    def test_resume_retry_reuses_directory_and_preserves_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_dirs: list[Path] = []
            partial = b"partial-download-bytes"

            def runner(_url, task_dir, _max_files, _archive, _after, _before, _cancel, progress):
                task_dirs.append(task_dir)
                part_path = task_dir / "image.jpg.part"
                if len(task_dirs) == 1:
                    part_path.write_bytes(partial)
                    progress("image.jpg", 1, 0)
                    return GalleryDlRunResult(4, 1, 0)
                self.assertEqual(part_path.read_bytes(), partial)
                (task_dir / "image.jpg").write_bytes(partial + b"-completed")
                progress("image.jpg", 1, 1)
                return GalleryDlRunResult(0, 1, 1)

            executor = GalleryDlExecutor(self.engine(root), runner=runner, validator=lambda value: value)
            task_id = executor.submit("https://example.com/gallery", resume_enabled=True)
            failed = wait_state(executor, task_id, {"failed"})
            self.assertIn("Resume", failed.advice)
            self.assertIn(".part", failed.advice)
            self.assertTrue(executor.retry(task_id).ok)
            completed = wait_state(executor, task_id, {"completed"})

            self.assertEqual(task_dirs, [task_dirs[0], task_dirs[0]])
            self.assertEqual(task_dirs[0].name, f"{task_id}-resume")
            self.assertIn("Resume", completed.detail)
            self.assertIn("Resume", completed.advice)
            self.assertNotIn(str(root), completed.detail)
            self.assertNotIn(str(root), completed.advice)
            managed_dirs = list((root / "downloads" / "gallery-dl").iterdir())
            self.assertEqual(len(managed_dirs), 1)
            self.assertTrue(managed_dirs[0].samefile(task_dirs[0]))

    def test_resume_zero_new_files_can_complete_after_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = {"count": 0}

            def runner(_url, _task_dir, _max_files, _archive, _after, _before, _cancel, _progress):
                calls["count"] += 1
                if calls["count"] == 1:
                    return GalleryDlRunResult(4, 1, 0)
                return GalleryDlRunResult(0, 0, 0)

            executor = GalleryDlExecutor(self.engine(root), runner=runner, validator=lambda value: value)
            task_id = executor.submit("https://example.com/gallery", resume_enabled=True)
            wait_state(executor, task_id, {"failed"})
            self.assertTrue(executor.retry(task_id).ok)
            completed = wait_state(executor, task_id, {"completed"})
            self.assertIn("Resume 重试", completed.detail)
            self.assertIn("没有新增文件", completed.detail)

    def test_resume_task_directory_rejects_symlink_leaf(self) -> None:
        if not hasattr(Path, "symlink_to"):
            self.skipTest("symlink not supported")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_root = root / "downloads"
            gallery_root = output_root / "gallery-dl"
            gallery_root.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            leaf = gallery_root / "gdl-fixed-resume"
            try:
                leaf.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation is not permitted")
            with self.assertRaises(GalleryDlExecutorError):
                _task_directory(output_root, "gdl-fixed", 1, resume_enabled=True)
            self.assertTrue(outside.is_dir())

    def test_resume_task_directory_rejects_non_directory_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_root = root / "downloads"
            leaf = output_root / "gallery-dl" / "gdl-fixed-resume"
            leaf.parent.mkdir(parents=True)
            leaf.write_bytes(b"not-a-directory")
            with self.assertRaises(GalleryDlExecutorError):
                _task_directory(output_root, "gdl-fixed", 1, resume_enabled=True)
            self.assertTrue(leaf.is_file())

    def test_managed_embedding_explicitly_keeps_gallery_dl_part_files_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            values: list[tuple[tuple[str, ...], str, object]] = []

            class FakeConfig:
                @staticmethod
                def clear() -> None:
                    values.clear()

                @staticmethod
                def set(path, key, value) -> None:
                    values.append((tuple(path), key, value))

            class StopExtraction(Exception):
                pass

            class FakeDownloadJob:
                def __init__(self, _url, parent=None) -> None:
                    self.pathfmt = None
                    self.metadata_http = None
                    self.parent = parent

                def run(self) -> int:
                    return 0

                def handle_directory(self, _kwdict) -> None:
                    return

                def handle_url(self, _url, _kwdict) -> None:
                    return

            @contextlib.contextmanager
            def fake_modules(_engine):
                yield (
                    FakeConfig,
                    SimpleNamespace(DownloadJob=FakeDownloadJob),
                    SimpleNamespace(StopExtraction=StopExtraction),
                )

            with patch.object(executor_module, "managed_gallery_dl_modules", fake_modules):
                result = _run_managed_gallery_dl(
                    object(),
                    "https://example.com/gallery",
                    root,
                    10,
                    None,
                    None,
                    None,
                    threading.Event(),
                    lambda *_args: None,
                )

            self.assertEqual(result.status_code, 0)
            self.assertIn((("downloader",), "part", True), values)
            self.assertNotIn((("downloader",), "part-directory", str(root)), values)


if __name__ == "__main__":
    unittest.main(verbosity=2)
