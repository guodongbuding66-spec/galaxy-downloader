#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import managed_tool_actions as managed_actions  # noqa: E402
import task_center  # noqa: E402
from desktop_gallery_dl import install_desktop_gallery_dl, run_desktop_gallery_dl_self_test  # noqa: E402
from desktop_hooks import registered_after_build_ui_hooks  # noqa: E402
from gallery_dl_executor import (  # noqa: E402
    GalleryDlRunResult,
    install_gallery_dl_executor,
    run_gallery_dl_executor_self_test,
)
from gallery_dl_runtime import GALLERY_DL_RUNTIME_LOCK  # noqa: E402
from local_task_provider import (  # noqa: E402
    local_task_provider_names,
    local_task_rows,
    unregister_local_task_provider,
)
from managed_tool_actions import (  # noqa: E402
    ManagedToolActionAdapters,
    ManagedToolActionRequest,
    perform_managed_tool_action,
)


class GalleryDlProductTests(unittest.TestCase):
    def test_runtime_busy_blocks_mutation_before_adapter(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        mutation_calls: list[str] = []
        check_calls: list[str] = []

        def hold_runtime() -> None:
            with GALLERY_DL_RUNTIME_LOCK:
                entered.set()
                release.wait(3)

        holder = threading.Thread(target=hold_runtime, name="GalleryDlRuntimeHolder")
        holder.start()
        self.assertTrue(entered.wait(1), "runtime lock was not acquired")

        def forbidden_install(*_args, **_kwargs):
            mutation_calls.append("install")
            raise AssertionError("gallery-dl install/update adapter must not run while runtime is busy")

        def forbidden_remove(*_args, **_kwargs):
            mutation_calls.append("remove")
            raise AssertionError("gallery-dl remove adapter must not run while runtime is busy")

        def allowed_check(*_args, **_kwargs):
            check_calls.append("check")
            return SimpleNamespace(
                ok=True,
                state="current",
                current_source="managed",
                current_version="1.2.3",
                available_version="1.2.3",
                available_release_tag="1.2.3",
                update_available=False,
                message="current",
            )

        adapters = ManagedToolActionAdapters(
            gallery_dl_check=allowed_check,
            gallery_dl_install=forbidden_install,
            gallery_dl_remove=forbidden_remove,
        )
        try:
            for action in ("install", "update", "remove"):
                result = perform_managed_tool_action(
                    object(),
                    ManagedToolActionRequest("gallery-dl", action, True),
                    adapters=adapters,
                )
                self.assertFalse(result.ok)
                self.assertEqual(result.state, "runtime-busy")
                self.assertFalse(result.network_action)
                self.assertIn("正在执行本机任务", result.message)
            self.assertEqual(mutation_calls, [])

            check = perform_managed_tool_action(
                object(),
                ManagedToolActionRequest("gallery-dl", "check", True),
                adapters=adapters,
            )
            self.assertTrue(check.ok)
            self.assertEqual(check.state, "current")
            self.assertTrue(check.network_action)
            self.assertEqual(check_calls, ["check"])
        finally:
            release.set()
            holder.join(2)
        self.assertFalse(holder.is_alive())

    def test_desktop_install_registers_provider_bridge_and_workbench_hook(self) -> None:
        unregister_local_task_provider("gallery-dl") if "gallery-dl" in local_task_provider_names() else None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            class Window:
                pass

            engine = SimpleNamespace(
                EngineWindow=Window,
                default_download_dir=lambda: root / "downloads",
            )
            executor = install_desktop_gallery_dl(engine)
            self.assertIs(executor, Window)
            self.assertIn("desktop-gallery-dl", registered_after_build_ui_hooks(Window))
            self.assertTrue(getattr(Window, "_galaxy_gallery_dl_executor_installed", False))
            self.assertTrue(getattr(Window, "_galaxy_desktop_gallery_dl_installed", False))
            self.assertTrue(getattr(task_center, "_galaxy_local_task_provider_rows_installed", False))
            self.assertIn("gallery-dl", local_task_provider_names())
            self.assertTrue(callable(getattr(Window, "submit_gallery_dl_task", None)))
        unregister_local_task_provider("gallery-dl")

    def test_provider_snapshot_is_safe_and_task_center_compatible(self) -> None:
        unregister_local_task_provider("gallery-dl") if "gallery-dl" in local_task_provider_names() else None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            started = threading.Event()
            release = threading.Event()

            class Window:
                pass

            engine = SimpleNamespace(
                EngineWindow=Window,
                default_download_dir=lambda: root / "downloads",
            )
            executor = install_gallery_dl_executor(engine)
            executor._validator = lambda value: value

            def runner(
                _url,
                _task_dir,
                _max_files,
                _archive_path,
                _date_after,
                _date_before,
                cancel_event,
                progress,
            ):
                started.set()
                progress("visible.jpg", 1, 0)
                release.wait(2)
                return GalleryDlRunResult(0, 1, 0, cancelled=cancel_event.is_set())

            executor._runner = runner
            task_id = executor.submit("https://example.com/gallery?token=must-not-leak")
            self.assertTrue(started.wait(1))
            rows = local_task_rows()
            row = next(item for item in rows if item.get("providerTaskId") == task_id)
            self.assertEqual(row.get("kind"), "provider")
            self.assertEqual(row.get("sourceUrl"), "")
            self.assertEqual(row.get("providerName"), "gallery-dl")
            self.assertIn("cancel", tuple(row.get("providerActions") or ()))
            serialized = repr(row)
            self.assertNotIn("must-not-leak", serialized)
            self.assertNotIn(str(root), serialized)
            release.set()
        unregister_local_task_provider("gallery-dl")

    def test_pure_product_self_tests(self) -> None:
        run_gallery_dl_executor_self_test()
        run_desktop_gallery_dl_self_test()
        task_center.run_task_center_self_test()
        managed_actions.run_managed_tool_actions_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
