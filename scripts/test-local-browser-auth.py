from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import browser_auth  # noqa: E402


class YuanbaoBrowserAuthTests(unittest.TestCase):
    def test_cookie_header_does_not_require_legacy_cookie_names(self):
        header = browser_auth._cookies_to_header([
            {"domain": ".tencent.com", "name": "new_session_cookie", "value": "abc"},
            {"domain": "yuanbao.tencent.com", "name": "another_auth_cookie", "value": "xyz"},
            {"domain": "example.com", "name": "ignore", "value": "nope"},
        ])
        self.assertIn("new_session_cookie=abc", header)
        self.assertIn("another_auth_cookie=xyz", header)
        self.assertNotIn("ignore=nope", header)

    def test_existing_browser_auto_detection_tries_alternates_without_managed_popup(self):
        statuses: list[str] = []

        def existing(browser: str) -> str:
            if browser == "edge":
                raise OSError("cookie database locked")
            if browser == "chrome":
                return "session=working"
            return ""

        with (
            mock.patch.object(browser_auth, "_existing_browser_cookie_header", side_effect=existing) as existing_cookie,
            mock.patch.object(browser_auth, "_managed_chromium_cookie_header") as managed,
        ):
            header = browser_auth.get_yuanbao_cookie_header("edge", on_status=statuses.append)

        self.assertEqual(header, "session=working")
        self.assertEqual(existing_cookie.call_args_list[:2], [mock.call("edge"), mock.call("chrome")])
        managed.assert_not_called()
        self.assertTrue(any("Chrome" in status for status in statuses))


if __name__ == "__main__":
    unittest.main(verbosity=2)
