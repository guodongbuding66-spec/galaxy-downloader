from __future__ import annotations

import unittest

from desktop_hooks import (
    install_before_close_support,
    register_before_close_hook,
    registered_before_close_hooks,
)


class DesktopBeforeCloseHookTests(unittest.TestCase):
    def test_close_hooks_run_in_order_and_fail_best_effort(self) -> None:
        events: list[str] = []

        class Window:
            def close_app(self):
                events.append("original")

        def first(window):
            events.append("first")
            raise RuntimeError("cleanup failed")

        def second(window):
            events.append("second")

        register_before_close_hook(Window, "second", second, order=20)
        register_before_close_hook(Window, "first", first, order=10)
        install_before_close_support(Window)
        install_before_close_support(Window)

        window = Window()
        window.close_app()
        self.assertEqual(events, ["first", "second", "original"])
        self.assertEqual(registered_before_close_hooks(Window), ("first", "second"))
        self.assertEqual(window._galaxy_before_close_errors, (("first", "cleanup failed"),))

    def test_duplicate_registration_is_idempotent_for_same_callback(self) -> None:
        class Window:
            def close_app(self):
                return None

        def callback(window):
            return None

        register_before_close_hook(Window, "cleanup", callback, order=10)
        register_before_close_hook(Window, "cleanup", callback, order=10)
        self.assertEqual(registered_before_close_hooks(Window), ("cleanup",))


if __name__ == "__main__":
    unittest.main()
