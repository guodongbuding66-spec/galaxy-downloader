#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import gallery_dl_executor as gallery_executor  # noqa: E402
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


class _Config:
    def __init__(self) -> None:
        self.values: dict[tuple[tuple[str, ...], str], object] = {}
        self.clear_calls = 0

    def clear(self) -> None:
        self.clear_calls += 1
        self.values.clear()

    def set(self, path, key, value) -> None:
        self.values[(tuple(path), str(key))] = value


class _StopExtraction(Exception):
    pass


class _DownloadJob:
    def __init__(self, _url, parent=None) -> None:
        self.parent = parent

    def run(self) -> int:
        return 0


class GalleryDlRateContractTests(unittest.TestCase):
    def engine(self, root: Path):
        return SimpleNamespace(default_download_dir=lambda: root / "downloads")

    def test_rate_is_numeric_bounded_and_normalized_to_integer_bytes_per_second(self) -> None:
        self.assertIsNone(gallery_executor._validate_gallery_rate_mib(None))
        self.assertEqual(gallery_executor._validate_gallery_rate_mib(1), 1_048_576)
        self.assertEqual(gallery_executor._validate_gallery_rate_mib(2.5), 2_621_440)
        self.assertEqual(gallery_executor._validate_gallery_rate_mib(0.1), 104_858)
        self.assertEqual(gallery_executor._validate_gallery_rate_mib(1024), 1_073_741_824)

        invalid = (
            True,
            False,
            "2.5",
            "500k",
            0,
            -1,
            0.099,
            1024.001,
            math.nan,
            math.inf,
            -math.inf,
            [],
            {},
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(GalleryDlExecutorError):
                gallery_executor._validate_gallery_rate_mib(value)

    def test_managed_runtime_sets_only_deterministic_single_value_rate(self) -> None:
        config = _Config()
        job_module = SimpleNamespace(DownloadJob=_DownloadJob)
        exception = SimpleNamespace(StopExtraction=_StopExtraction)

        @contextlib.contextmanager
        def managed_modules(_engine):
            yield config, job_module, exception

        with tempfile.TemporaryDirectory() as directory, patch.object(
            gallery_executor, "managed_gallery_dl_modules", managed_modules
        ):
            root = Path(directory).resolve()
            result = gallery_executor._run_managed_gallery_dl(
                object(),
                "https://example.com/gallery",
                root,
                10,
                None,
                None,
                None,
                2_621_440,
                gallery_executor.threading.Event(),
                lambda *_args: None,
            )

        self.assertEqual(result.status_code, 0)
        self.assertEqual(config.clear_calls, 1)
        self.assertEqual(config.values[(("downloader",), "rate")], "2621440")
        self.assertNotIn("-", str(config.values[(("downloader",), "rate")]))

    def test_unlimited_runtime_omits_rate_instead_of_setting_zero(self) -> None:
        config = _Config()
        job_module = SimpleNamespace(DownloadJob=_DownloadJob)
        exception = SimpleNamespace(StopExtraction=_StopExtraction)

        @contextlib.contextmanager
        def managed_modules(_engine):
            yield config, job_module, exception

        with tempfile.TemporaryDirectory() as directory, patch.object(
            gallery_executor, "managed_gallery_dl_modules", managed_modules
        ):
            gallery_executor._run_managed_gallery_dl(
                object(),
                "https://example.com/gallery",
                Path(directory).resolve(),
                10,
                None,
                None,
                None,
                None,
                gallery_executor.threading.Event(),
                lambda *_args: None,
            )

        self.assertNotIn((("downloader",), "rate"), config.values)

    def test_default_executor_forwards_rate_and_retry_preserves_same_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls: list[int | None] = []

            def managed_run(
                _engine,
                _url,
                _task_dir,
                _max_files,
                _archive_path,
                _date_after,
                _date_before,
                rate_limit_bps,
                _cancel_event,
                progress,
            ):
                calls.append(rate_limit_bps)
                if len(calls) == 1:
                    return GalleryDlRunResult(4, 0, 0)
                progress("retry.jpg", 1, 1)
                return GalleryDlRunResult(0, 1, 1)

            executor = GalleryDlExecutor(self.engine(root), validator=lambda value: value)
            with patch.object(gallery_executor, "_run_managed_gallery_dl", side_effect=managed_run):
                task_id = executor.submit("https://example.com/gallery", rate_limit_mib=2.5)
                failed = wait_state(executor, task_id, {"failed"})
                self.assertIn("retry", failed.actions)
                self.assertTrue(executor.retry(task_id).ok)
                completed = wait_state(executor, task_id, {"completed"})

            self.assertEqual(calls, [2_621_440, 2_621_440])
            self.assertIn("2.5 MiB/s", completed.detail)
            self.assertNotIn(str(root), completed.detail)

    def test_custom_runner_contract_remains_backward_compatible_when_rate_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = 0

            def legacy_runner(_url, _task_dir, _max_files, _archive, _after, _before, _cancel, progress):
                nonlocal calls
                calls += 1
                progress("legacy.jpg", 1, 1)
                return GalleryDlRunResult(0, 1, 1)

            executor = GalleryDlExecutor(self.engine(root), runner=legacy_runner, validator=lambda value: value)
            task_id = executor.submit("https://example.com/gallery")
            self.assertEqual(wait_state(executor, task_id, {"completed"}).state, "completed")
            self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
