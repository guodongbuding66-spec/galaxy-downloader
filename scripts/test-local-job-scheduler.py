from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from job_scheduler import JobScheduler, run_job_scheduler_self_test  # noqa: E402


class JobSchedulerTests(unittest.TestCase):
    def test_constructor_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            JobScheduler[object](max_waiting=0)
        with self.assertRaises(ValueError):
            JobScheduler[object](max_waiting=1, concurrency_limit=0)

    def test_fifo_and_capacity(self):
        scheduler = JobScheduler[str](max_waiting=2, concurrency_limit=1)
        self.assertEqual(scheduler.enqueue("first"), 1)
        self.assertEqual(scheduler.enqueue("second"), 2)
        self.assertIsNone(scheduler.enqueue("overflow"))
        self.assertEqual(scheduler.waiting_count, 2)
        self.assertEqual(scheduler.pop_next(), "first")
        self.assertEqual(scheduler.pop_next(), "second")
        self.assertIsNone(scheduler.pop_next())

    def test_remove_preserves_remaining_order(self):
        scheduler = JobScheduler[str](max_waiting=4)
        for value in ("a", "b", "c", "d"):
            scheduler.enqueue(value)
        removed = scheduler.remove_first(lambda item: item == "c")
        self.assertEqual(removed, "c")
        self.assertEqual(scheduler.waiting, ["a", "b", "d"])
        self.assertIsNone(scheduler.remove_first(lambda item: item == "missing"))

    def test_clear_keeps_waiting_list_identity_for_compatibility_aliases(self):
        scheduler = JobScheduler[str](max_waiting=3)
        alias = scheduler.waiting
        scheduler.enqueue("a")
        scheduler.enqueue("b")
        self.assertEqual(scheduler.clear(), 2)
        self.assertIs(scheduler.waiting, alias)
        self.assertEqual(alias, [])

    def test_concurrency_contract_is_configurable_without_starting_workers(self):
        scheduler = JobScheduler[int](max_waiting=5, concurrency_limit=3)
        self.assertEqual(scheduler.concurrency_limit, 3)
        self.assertEqual(scheduler.available_start_slots(0), 3)
        self.assertEqual(scheduler.available_start_slots(1), 2)
        self.assertEqual(scheduler.available_start_slots(2), 1)
        self.assertEqual(scheduler.available_start_slots(3), 0)
        self.assertEqual(scheduler.available_start_slots(99), 0)
        self.assertTrue(scheduler.can_start(2))
        self.assertFalse(scheduler.can_start(3))

    def test_embedded_self_test(self):
        run_job_scheduler_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
