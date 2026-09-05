from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import headless_service
from headless_browser_cookies import (
    HeadlessBrowserCookieError,
    browser_cookie_source,
    install_headless_browser_cookie_support,
)


class HeadlessBrowserCookieTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_headless_browser_cookie_support()

    def test_browser_source_is_normalized(self) -> None:
        self.assertEqual(browser_cookie_source(" Chrome "), "chrome")
        self.assertEqual(browser_cookie_source("FIREFOX"), "firefox")
        self.assertEqual(browser_cookie_source(None), "none")

    def test_invalid_browser_source_is_rejected(self) -> None:
        for value in ("safari", "opera", "../cookies.txt", "chrome:Default"):
            with self.subTest(value=value):
                with self.assertRaises(HeadlessBrowserCookieError):
                    browser_cookie_source(value)

    def test_none_does_not_add_cookie_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            options = headless_service._download_options(
                {"browser": "none"},
                Path(directory),
                lambda _event: None,
            )
        self.assertNotIn("cookiesfrombrowser", options)

    def test_supported_browser_uses_ytdlp_native_cookie_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for browser in ("edge", "chrome", "firefox", "brave"):
                with self.subTest(browser=browser):
                    options = headless_service._download_options(
                        {"browser": browser},
                        Path(directory),
                        lambda _event: None,
                    )
                    self.assertEqual(
                        options.get("cookiesfrombrowser"),
                        (browser, None, None, None),
                    )

    def test_invalid_browser_fails_before_queue_submission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = headless_service.HeadlessRuntime(Path(directory), max_queue_size=1)
            try:
                with patch(
                    "headless_service.validated_public_http_url",
                    side_effect=lambda value: str(value or "").strip(),
                ):
                    with self.assertRaises(HeadlessBrowserCookieError):
                        runtime.submit(
                            {
                                "sourceUrl": "https://example.com/video",
                                "browser": "safari",
                            }
                        )
                self.assertEqual(runtime.list_jobs(), [])
            finally:
                runtime.stop()

    def test_public_job_payload_does_not_expose_browser_or_cookie_data(self) -> None:
        job = headless_service.HeadlessJob(
            job_id="a" * 32,
            source_host="www.udemy.com",
        )
        payload = job.public_payload()
        self.assertNotIn("browser", payload)
        self.assertNotIn("cookiesfrombrowser", payload)
        self.assertNotIn("cookie", " ".join(payload.keys()).lower())


if __name__ == "__main__":
    unittest.main()
