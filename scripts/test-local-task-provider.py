from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_hooks import run_history_button_hooks  # noqa: E402
from local_task_provider import (  # noqa: E402
    LocalTaskActionResult,
    LocalTaskProviderError,
    LocalTaskProviderRegistry,
    LocalTaskSnapshot,
    install_local_task_provider_bridge,
    local_task_rows,
    perform_local_task_action,
    register_local_task_provider,
    run_local_task_provider_self_test,
    unregister_local_task_provider,
)


class LocalTaskProviderTests(unittest.TestCase):
    def test_registry_normalizes_rows_and_redacts_private_runtime_data(self) -> None:
        registry = LocalTaskProviderRegistry()
        registry.register(
            "gallery-dl",
            label="gallery-dl",
            snapshot=lambda: [
                LocalTaskSnapshot(
                    task_id="g:abc123",
                    state="running",
                    title="Download album",
                    provider_label="gallery-dl",
                    task_type="图集",
                    progress_percent=37.125,
                    detail=r"writing C:\Users\demo\Pictures\secret.jpg Authorization: Bearer supersecrettoken12345",
                    advice="temp /home/demo/private/work.bin Cookie: session=secret",
                    actions=("cancel", "cancel"),
                )
            ],
        )
        rows = registry.rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["key"], "x:gallery-dl:g:abc123")
        self.assertEqual(row["kind"], "provider")
        self.assertEqual(row["state"], "active")
        self.assertEqual(row["when"], "37.1%")
        self.assertEqual(row["providerActions"], ("cancel",))
        serialized = json.dumps(row, ensure_ascii=False)
        self.assertNotIn("C:\\Users", serialized)
        self.assertNotIn("/home/demo", serialized)
        self.assertNotIn("supersecrettoken", serialized)
        self.assertNotIn("session=secret", serialized)
        self.assertNotIn("callback", serialized.lower())
        self.assertEqual(row["sourceUrl"], "")

    def test_registration_is_duplicate_guarded_and_identifiers_are_bounded(self) -> None:
        registry = LocalTaskProviderRegistry()

        def snapshot():
            return []

        registry.register("demo", label="Demo", snapshot=snapshot)
        registry.register("demo", label="Demo", snapshot=snapshot)
        with self.assertRaises(LocalTaskProviderError):
            registry.register("demo", label="Other", snapshot=snapshot)
        with self.assertRaises(LocalTaskProviderError):
            registry.register("../escape", label="Bad", snapshot=snapshot)
        with self.assertRaises(LocalTaskProviderError):
            registry.register("ok", label="OK", snapshot=lambda: [LocalTaskSnapshot("../bad", "active", "x", "OK")])
            registry.rows()

    def test_invalid_provider_snapshot_fails_closed_without_breaking_other_providers(self) -> None:
        registry = LocalTaskProviderRegistry()
        registry.register(
            "broken",
            label="Broken",
            snapshot=lambda: (_ for _ in ()).throw(RuntimeError(r"C:\private\stack.txt")),
        )
        registry.register(
            "good",
            label="Good",
            snapshot=lambda: [LocalTaskSnapshot("task-1", "completed", "Finished", "Good")],
        )
        rows = registry.rows()
        self.assertEqual([row["providerName"] for row in rows], ["good"])

    def test_duplicate_task_ids_fail_closed_for_that_provider(self) -> None:
        registry = LocalTaskProviderRegistry()
        registry.register(
            "dup",
            label="Dup",
            snapshot=lambda: [
                LocalTaskSnapshot("same", "active", "One", "Dup"),
                LocalTaskSnapshot("same", "queued", "Two", "Dup"),
            ],
        )
        self.assertEqual(registry.rows(), [])

    def test_action_must_be_advertised_and_internal_exceptions_are_hidden(self) -> None:
        calls: list[tuple[str, str]] = []

        def snapshot():
            return [
                LocalTaskSnapshot(
                    "task-1",
                    "active",
                    "Running",
                    "Demo",
                    actions=("cancel",),
                )
            ]

        def action(task_id: str, action_name: str) -> LocalTaskActionResult:
            calls.append((task_id, action_name))
            if action_name == "cancel":
                raise RuntimeError(r"failed at C:\Users\demo\secret.py Authorization: Bearer private123456")
            return LocalTaskActionResult(True, True, "ok")

        registry = LocalTaskProviderRegistry()
        registry.register("demo", label="Demo", snapshot=snapshot, action=action)
        rejected = registry.perform_action("demo", "task-1", "retry")
        self.assertFalse(rejected.ok)
        self.assertEqual(calls, [])
        failed = registry.perform_action("demo", "task-1", "cancel")
        self.assertFalse(failed.ok)
        self.assertEqual(failed.message, "本机任务操作失败。")
        self.assertEqual(calls, [("task-1", "cancel")])

    def test_action_result_is_bounded_and_redacted(self) -> None:
        registry = LocalTaskProviderRegistry()
        registry.register(
            "demo",
            label="Demo",
            snapshot=lambda: [LocalTaskSnapshot("task-1", "failed", "Failed", "Demo", actions=("retry",))],
            action=lambda _task, _action: LocalTaskActionResult(
                True,
                True,
                r"restarted from C:\Users\demo\private.part Cookie: session=topsecret",
            ),
        )
        result = registry.perform_action("demo", "task-1", "retry")
        self.assertTrue(result.ok)
        self.assertNotIn("C:\\Users", result.message)
        self.assertNotIn("session=topsecret", result.message)

    def test_bridge_appends_provider_rows_without_replacing_legacy_task_center(self) -> None:
        provider = "bridge-test"
        register_local_task_provider(
            provider,
            label="Bridge Test",
            snapshot=lambda: [LocalTaskSnapshot("task-1", "queued", "Queued local task", "Bridge Test")],
        )
        try:
            fake_task_center = SimpleNamespace(
                _task_rows=lambda _window, _engine: [
                    {
                        "key": "legacy",
                        "kind": "history",
                        "state": "completed",
                        "label": "Legacy download",
                    }
                ]
            )

            class EngineWindow:
                pass

            class Engine:
                pass

            Engine.EngineWindow = EngineWindow
            install_local_task_provider_bridge(Engine, task_center_module=fake_task_center)
            rows = fake_task_center._task_rows(object(), Engine)
            self.assertEqual([row["key"] for row in rows], ["legacy", "x:bridge-test:task-1"])
            self.assertTrue(getattr(fake_task_center, "_galaxy_local_task_provider_rows_installed", False))
            self.assertTrue(getattr(EngineWindow, "_galaxy_local_task_provider_bridge_installed", False))
            text = run_history_button_hooks(object.__new__(EngineWindow), Engine, 1, "任务 1")
            self.assertEqual(text, "任务 2")
        finally:
            unregister_local_task_provider(provider)

    def test_global_action_contract_uses_only_registered_task_and_action(self) -> None:
        provider = "global-test"
        register_local_task_provider(
            provider,
            label="Global",
            snapshot=lambda: [LocalTaskSnapshot("job-1", "failed", "Failed", "Global", actions=("retry",))],
            action=lambda task_id, action: LocalTaskActionResult(task_id == "job-1" and action == "retry", True, "retried"),
        )
        try:
            self.assertEqual(len([row for row in local_task_rows() if row.get("providerName") == provider]), 1)
            result = perform_local_task_action(provider, "job-1", "retry")
            self.assertTrue(result.ok)
            self.assertEqual(result.message, "retried")
        finally:
            unregister_local_task_provider(provider)

    def test_embedded_self_test(self) -> None:
        run_local_task_provider_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
