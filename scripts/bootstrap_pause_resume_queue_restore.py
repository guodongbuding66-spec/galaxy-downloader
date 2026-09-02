from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one {label} target, got {count}: {old[:160]!r}")
    return text.replace(old, new, 1)


def patch_policy() -> None:
    path = Path("local-engine/pause_resume_policy.py")
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''        window._resume_queue_was_paused = False
        window._resume_last_persist_at = 0.0
''',
        '''        window._resume_queue_was_paused = False
        window._pause_queue_holder_id = ""
        window._resume_last_persist_at = 0.0
''',
        "queue holder init",
    )

    helper = '''

    def restore_queue_after_pause(window, job_id: str, *, start_if_idle: bool) -> bool:
        """Release only the temporary queue hold created by this paused job."""
        holder = str(getattr(window, "_pause_queue_holder_id", "") or "")
        if not holder or holder != str(job_id or ""):
            return False
        window.queue_paused = bool(getattr(window, "_resume_queue_was_paused", False))
        window._pause_queue_holder_id = ""
        if start_if_idle and not window.queue_paused and not bool(getattr(window, "running", False)):
            starter = getattr(window, "_start_next_queued_job", None)
            if callable(starter):
                starter()
        return True
'''
    text = replace_once(
        text,
        "\n\n    def pause_active_job(window) -> bool:\n",
        helper + "\n\n    def pause_active_job(window) -> bool:\n",
        "queue restore helper",
    )

    text = replace_once(
        text,
        '''        window._resume_queue_was_paused = bool(getattr(window, "queue_paused", False))
        # Prevent the single-active-job scheduler from immediately starting the
''',
        '''        window._resume_queue_was_paused = bool(getattr(window, "queue_paused", False))
        window._pause_queue_holder_id = str(getattr(window, "_active_resume_job_id", "") or "")
        # Prevent the single-active-job scheduler from immediately starting the
''',
        "queue holder claim",
    )

    text = replace_once(
        text,
        '''        window._resume_queue_was_paused = bool(selected.get("queueWasPaused", False))
        window.queue_paused = window._resume_queue_was_paused
        window.cancel_event.clear()
''',
        '''        window._resume_queue_was_paused = bool(selected.get("queueWasPaused", False))
        if not restore_queue_after_pause(window, str(selected["id"]), start_if_idle=False):
            # After an application restart there is no in-memory queue hold to
            # release, but preserve the recorded queue preference for the new run.
            window.queue_paused = window._resume_queue_was_paused
        window.cancel_event.clear()
''',
        "resume queue restore",
    )

    text = replace_once(
        text,
        '''    def discard_resume_job(window, job_id: str) -> bool:
        if str(job_id or "") == str(getattr(window, "_active_resume_job_id", "") or "") and bool(getattr(window, "running", False)):
            return False
        return window._resume_store.remove(str(job_id or ""))

    def cancel(window) -> None:
        # Explicit Cancel means "do not offer this job for restart recovery".
        window.pause_event.clear()
        original_cancel(window)
''',
        '''    def discard_resume_job(window, job_id: str) -> bool:
        wanted = str(job_id or "")
        if wanted == str(getattr(window, "_active_resume_job_id", "") or "") and bool(getattr(window, "running", False)):
            return False
        removed = window._resume_store.remove(wanted)
        if removed:
            restore_queue_after_pause(window, wanted, start_if_idle=True)
        return removed

    def cancel(window) -> None:
        # Explicit Cancel means "do not offer this job for restart recovery".
        if window.pause_event.is_set():
            restore_queue_after_pause(
                window,
                str(getattr(window, "_active_resume_job_id", "") or ""),
                start_if_idle=False,
            )
        window.pause_event.clear()
        original_cancel(window)
''',
        "discard and cancel queue restoration",
    )

    # Strengthen the embedded packaged self-test fake with a next-queue hook.
    text = replace_once(
        text,
        '''                self.deiconified = False

            def bridge_status(self) -> dict[str, Any]:
''',
        '''                self.deiconified = False
                self.started_next = 0

            def bridge_status(self) -> dict[str, Any]:
''',
        "embedded fake next counter",
    )
    text = replace_once(
        text,
        '''            def focus_force(self) -> None:
                return

        class FakeEngine:
''',
        '''            def focus_force(self) -> None:
                return

            def _start_next_queued_job(self) -> None:
                if not self.running and not self.queue_paused:
                    self.started_next += 1

        class FakeEngine:
''',
        "embedded fake queue starter",
    )

    addition = '''

        # Discarding a paused task must release only the queue hold that task made.
        discard_window = FakeEngine.EngineWindow(FakeJob("https://media.example.com/video/discard"))
        discard_window.start_job()
        discard_id = discard_window.bridge_status()["activeJobId"]
        assert discard_window.pause_active_job() is True
        discard_window._run_job()
        assert discard_window.queue_paused is True
        assert discard_window.discard_resume_job(discard_id) is True
        assert discard_window.queue_paused is False
        assert discard_window.started_next == 1

        # If Cancel is pressed while Pausing, it becomes a true terminal cancel
        # and the temporary queue hold is released before the worker exits.
        cancel_window = FakeEngine.EngineWindow(FakeJob("https://media.example.com/video/cancel-during-pause"))
        cancel_window.start_job()
        cancel_id = cancel_window.bridge_status()["activeJobId"]
        assert cancel_window.pause_active_job() is True
        assert cancel_window.queue_paused is True
        cancel_window.cancel()
        assert cancel_window.pause_event.is_set() is False
        assert cancel_window.queue_paused is False
        cancel_window._run_job()
        assert cancel_window._resume_store.get(cancel_id) is None
'''
    anchor = '''        assert wechat_records[0]["resumeMode"] == "restart"
        assert wechat_records[0]["progress"] == 63.0
'''
    text = replace_once(text, anchor, anchor + addition, "embedded queue restore assertions")

    path.write_text(text, encoding="utf-8")


def patch_standalone_test() -> None:
    path = Path("scripts/test-local-pause-resume.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''                self.deiconified = False

            def bridge_status(self) -> dict[str, Any]:
''',
        '''                self.deiconified = False
                self.started_next = 0

            def bridge_status(self) -> dict[str, Any]:
''',
        "standalone fake next counter",
    )
    text = replace_once(
        text,
        '''            def focus_force(self) -> None:
                return

        class FakeEngine:
''',
        '''            def focus_force(self) -> None:
                return

            def _start_next_queued_job(self) -> None:
                if not self.running and not self.queue_paused:
                    self.started_next += 1

        class FakeEngine:
''',
        "standalone fake queue starter",
    )

    tests = '''

    def test_discarding_paused_job_releases_temporary_queue_hold(self) -> None:
        window = self.engine.EngineWindow(FakeJob("https://media.example.com/video/discard"))
        window.start_job()
        job_id = window.bridge_status()["activeJobId"]
        self.assertTrue(window.pause_active_job())
        window._run_job()
        self.assertTrue(window.queue_paused)
        self.assertTrue(window.discard_resume_job(job_id))
        self.assertFalse(window.queue_paused)
        self.assertEqual(window.started_next, 1)

    def test_cancel_during_pausing_is_terminal_and_releases_queue_hold(self) -> None:
        window = self.engine.EngineWindow(FakeJob("https://media.example.com/video/cancel-during-pause"))
        window.start_job()
        job_id = window.bridge_status()["activeJobId"]
        self.assertTrue(window.pause_active_job())
        self.assertTrue(window.queue_paused)
        window.cancel()
        self.assertFalse(window.pause_event.is_set())
        self.assertFalse(window.queue_paused)
        window._run_job()
        self.assertIsNone(window._resume_store.get(job_id))
'''
    text = replace_once(
        text,
        "\n\nif __name__ == \"__main__\":\n    unittest.main(verbosity=2)\n",
        tests + "\n\nif __name__ == \"__main__\":\n    unittest.main(verbosity=2)\n",
        "standalone queue restore tests",
    )
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_policy()
    patch_standalone_test()
