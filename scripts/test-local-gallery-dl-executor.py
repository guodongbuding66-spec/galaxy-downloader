#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import threading
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
    _run_managed_gallery_dl,
)
from url_policy import PublicUrlError  # noqa: E402


def wait_state(executor: GalleryDlExecutor, task_id: str, states: set[str], timeout: float = 4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = next((item for item in executor.snapshots() if item.task_id == task_id), None)
        if current is not None and current.state in states:
            return current
        time.sleep(0.02)
    current = next((item for item in executor.snapshots() if item.task_id == task_id), None)
    raise AssertionError(f"task did not reach {states}: {current}")


class GalleryDlExecutorTests(unittest.TestCase):
    def engine(self, root: Path):
        return SimpleNamespace(default_download_dir=lambda: root / "downloads")

    def test_fifo_queued_cancel_and_safe_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            started = threading.Event()
            release = threading.Event()

            def runner(_url, _task_dir, _max_files, cancel_event, progress):
                started.set()
                progress("first.jpg", 1, 0)
                release.wait(2)
                if cancel_event.is_set():
                    return GalleryDlRunResult(0, 1, 0, cancelled=True)
                progress("", 1, 1)
                return GalleryDlRunResult(0, 1, 1)

            executor = GalleryDlExecutor(self.engine(root), runner=runner, validator=lambda value: value)
            first = executor.submit("https://example.com/gallery?token=supersecret")
            self.assertTrue(started.wait(1))
            second = executor.submit("https://example.org/queued")
            queued = wait_state(executor, second, {"queued"})
            self.assertIn("cancel", queued.actions)
            cancelled = executor.cancel(second)
            self.assertTrue(cancelled.ok and cancelled.changed)
            self.assertEqual(wait_state(executor, second, {"cancelled"}).state, "cancelled")
            serialized = json.dumps([item.__dict__ for item in executor.snapshots()], ensure_ascii=False)
            self.assertNotIn("supersecret", serialized)
            self.assertNotIn(str(root), serialized)
            release.set()
            self.assertEqual(wait_state(executor, first, {"completed"}).state, "completed")

    def test_active_cancel_is_safe_point_and_retry_uses_new_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            started = threading.Event()
            calls = {"count": 0}

            def runner(_url, _task_dir, _max_files, cancel_event, progress):
                calls["count"] += 1
                if calls["count"] == 1:
                    started.set()
                    progress("large-file.jpg", 1, 0)
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline and not cancel_event.is_set():
                        time.sleep(0.01)
                    return GalleryDlRunResult(0, 1, 0, cancelled=cancel_event.is_set())
                progress("retry.jpg", 1, 1)
                return GalleryDlRunResult(0, 1, 1)

            executor = GalleryDlExecutor(self.engine(root), runner=runner, validator=lambda value: value)
            task_id = executor.submit("https://example.com/gallery")
            self.assertTrue(started.wait(1))
            action = executor.cancel(task_id)
            self.assertTrue(action.ok and action.changed)
            cancelled = wait_state(executor, task_id, {"cancelled"})
            self.assertIn("retry", cancelled.actions)
            retried = executor.retry(task_id)
            self.assertTrue(retried.ok and retried.changed)
            completed = wait_state(executor, task_id, {"completed"})
            self.assertEqual(completed.state, "completed")
            attempts = sorted((root / "downloads" / "gallery-dl").glob(f"{task_id}-a*"))
            self.assertEqual(len(attempts), 2)

    def test_failure_retry_and_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = {"count": 0}

            def runner(_url, _task_dir, _max_files, _cancel, progress):
                calls["count"] += 1
                if calls["count"] == 1:
                    return GalleryDlRunResult(4, 1, 0)
                progress("ok.jpg", 1, 1)
                return GalleryDlRunResult(0, 1, 1)

            executor = GalleryDlExecutor(self.engine(root), runner=runner, validator=lambda value: value)
            with self.assertRaises(GalleryDlExecutorError):
                executor.submit("https://example.com/x", max_files=0)
            with self.assertRaises(GalleryDlExecutorError):
                executor.submit("https://example.com/x", max_files=501)
            task_id = executor.submit("https://example.com/x", max_files=3)
            failed = wait_state(executor, task_id, {"failed"})
            self.assertIn("retry", failed.actions)
            self.assertNotIn(str(root), failed.detail)
            self.assertTrue(executor.retry(task_id).ok)
            self.assertEqual(wait_state(executor, task_id, {"completed"}).state, "completed")

    def test_public_url_boundary_rejects_private_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executor = GalleryDlExecutor(self.engine(Path(directory)), runner=lambda *_args: None)
            with self.assertRaises(PublicUrlError):
                executor.submit("http://127.0.0.1/private")
            with self.assertRaises(PublicUrlError):
                executor.submit("file:///etc/passwd")

    def test_symlink_output_root_is_rejected(self) -> None:
        if not hasattr(Path, "symlink_to"):
            self.skipTest("symlink not supported")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            link = root / "link"
            try:
                link.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation is not permitted")
            executor = GalleryDlExecutor(self.engine(root), runner=lambda *_args: None, validator=lambda value: value)
            with self.assertRaises(GalleryDlExecutorError):
                executor.submit("https://example.com/gallery", output_root=link)

    def test_managed_embedding_clears_config_uses_memory_cache_and_cleans_modules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            managed = tools / "gallery-dl"
            package = managed / "gallery_dl"
            package.mkdir(parents=True)
            (managed / "gallery_dl-9.9.9.dist-info").mkdir()
            (managed / "gallery_dl-9.9.9.dist-info" / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: gallery-dl\nVersion: 9.9.9\n\n",
                encoding="utf-8",
            )
            (package / "__init__.py").write_text("__version__ = '9.9.9'\n", encoding="utf-8")
            (package / "config.py").write_text(
                "_c = {}\n"
                "def clear(): _c.clear()\n"
                "def set(path, key, value):\n"
                "    d = _c\n"
                "    for p in path: d = d.setdefault(p, {})\n"
                "    d[key] = value\n"
                "def get(path, key, default=None):\n"
                "    d = _c\n"
                "    try:\n"
                "        for p in path: d = d[p]\n"
                "        return d.get(key, default)\n"
                "    except Exception: return default\n",
                encoding="utf-8",
            )
            (package / "exception.py").write_text(
                "class StopExtraction(Exception):\n"
                "    def __init__(self):\n"
                "        self.depth = 1; self.target = None\n",
                encoding="utf-8",
            )
            (package / "job.py").write_text(
                "from pathlib import Path\n"
                "from . import config\n"
                "from .exception import StopExtraction\n"
                "class PF:\n"
                "    def __init__(self, root): self.directory=str(root); self.path=''; self.extension='jpg'\n"
                "    def set_filename(self, kw): self.path=str(Path(self.directory)/(str(kw.get('filename','one'))+'.'+str(kw.get('extension','jpg'))))\n"
                "    def build_path(self): return self.path\n"
                "class DownloadJob:\n"
                "    def __init__(self, url, parent=None): self.url=url; self.pathfmt=PF(config.get((), 'base-directory')); self.metadata_http=None\n"
                "    def handle_directory(self, kw): Path(self.pathfmt.directory).mkdir(parents=True, exist_ok=True)\n"
                "    def handle_url(self, url, kw): self.pathfmt.set_filename(kw); self.pathfmt.build_path(); Path(self.pathfmt.path).write_bytes(b'ok')\n"
                "    def run(self):\n"
                "        assert config.get(('cache',), 'file') == ':memory:'\n"
                "        assert config.get(('output',), 'mode') == 'null'\n"
                "        assert config.get((), 'actions') == ()\n"
                "        assert config.get((), 'postprocessors') == ()\n"
                "        try:\n"
                "            self.handle_directory({})\n"
                "            self.handle_url(self.url, {'filename':'one','extension':'jpg'})\n"
                "        except StopExtraction:\n"
                "            pass\n"
                "        return 0\n",
                encoding="utf-8",
            )

            engine = SimpleNamespace(tools_dir=lambda: tools)
            task_dir = root / "out" / "task"
            task_dir.mkdir(parents=True)
            result = _run_managed_gallery_dl(
                engine,
                "https://example.com/gallery",
                task_dir,
                10,
                threading.Event(),
                lambda *_args: None,
            )
            self.assertEqual(result.status_code, 0)
            self.assertEqual(result.processed, 1)
            self.assertEqual(result.downloaded, 1)
            self.assertTrue((task_dir / "one.jpg").is_file())
            self.assertFalse(any(name == "gallery_dl" or name.startswith("gallery_dl.") for name in sys.modules))


if __name__ == "__main__":
    unittest.main(verbosity=2)
