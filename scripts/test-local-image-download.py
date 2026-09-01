from __future__ import annotations

import tempfile
import sys
import unittest
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import image_download  # noqa: E402


class _BrokenImageResponse:
    def __init__(self) -> None:
        self.headers = {"Content-Length": "0", "Content-Type": "image/png"}
        self._reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self) -> str:
        return "https://cdn.example.test/image.png"

    def read(self, _size: int) -> bytes:
        self._reads += 1
        if self._reads == 1:
            return b"\x89PNG\r\n\x1a\n" + b"x" * 16
        raise URLError("connection reset")


class _BrokenOpener:
    def __init__(self) -> None:
        self.calls = 0

    def open(self, _request, timeout: int):
        self.calls += 1
        self.timeout = timeout
        return _BrokenImageResponse()


class LocalImageDownloadPolicyTests(unittest.TestCase):
    def test_wechat_original_candidate_prefers_zero_dimension_and_removes_webp_hint(self):
        source = (
            "https://mmbiz.qpic.cn/sz_mmbiz_jpg/demo/640"
            "?wx_fmt=jpeg&tp=webp&wxfrom=5"
        )
        original = image_download._wechat_original_candidate(source)
        self.assertIsNotNone(original)
        self.assertIn("/0?", original)
        self.assertIn("wx_fmt=jpeg", original)
        self.assertIn("wxfrom=5", original)
        self.assertNotIn("tp=webp", original)

    def test_non_wechat_image_has_no_synthetic_original_candidate(self):
        self.assertIsNone(
            image_download._wechat_original_candidate("https://example.com/photo/640?format=jpeg")
        )

    def test_image_magic_detection_covers_common_and_modern_formats(self):
        fixtures = (
            (b"\xff\xd8\xff\xe0", "application/octet-stream", "https://x/photo", "jpg"),
            (b"\x89PNG\r\n\x1a\n", "", "https://x/photo", "png"),
            (b"GIF89a", "", "https://x/photo", "gif"),
            (b"RIFF\x00\x00\x00\x00WEBP", "", "https://x/photo", "webp"),
            (b"\x00\x00\x00\x1cftypavif", "", "https://x/photo", "avif"),
        )
        for body, content_type, url, expected in fixtures:
            with self.subTest(expected=expected):
                self.assertEqual(
                    image_download._sniff_extension(body, content_type, url),
                    expected,
                )

    def test_wechat_format_hint_recovers_jpeg_extension(self):
        source = "https://mmbiz.qpic.cn/demo/0?wx_fmt=jpeg"
        self.assertEqual(image_download._sniff_extension(b"unknown", "", source), "jpg")
        self.assertTrue(image_download._source_prefers_jpeg(source))

    def test_archive_markdown_rewrites_remote_image_urls_to_local_files(self):
        payload = {
            "title": "Example",
            "markdownContent": "# Example\n\nBefore\n\n![](https://cdn.example/a.webp)\n\nAfter",
        }
        files = [("https://cdn.example/a.webp", Path("Example-1.png"))]
        rendered = image_download._archive_markdown(payload, files)
        self.assertIn("![](Example-1.png)", rendered)
        self.assertNotIn("https://cdn.example/a.webp", rendered)
        self.assertLess(rendered.index("Before"), rendered.index("Example-1.png"))
        self.assertLess(rendered.index("Example-1.png"), rendered.index("After"))

    def test_batch_job_limits_are_finite(self):
        self.assertGreater(image_download.MAX_IMAGES_PER_JOB, 0)
        self.assertLessEqual(image_download.MAX_IMAGES_PER_JOB, 500)
        self.assertGreater(image_download.MAX_IMAGE_BYTES, 32 * 1024 * 1024)
        self.assertGreater(image_download.MAX_BATCH_BYTES, image_download.MAX_IMAGE_BYTES)
        self.assertGreater(image_download.MIN_FREE_BYTES, 0)

    def test_duplicate_image_urls_are_removed_without_reordering(self):
        values = ["https://a/1", " https://a/2 ", "https://a/1", "", None, "https://a/2", "https://a/3"]
        self.assertEqual(
            image_download._dedupe_images(values),
            ["https://a/1", "https://a/2", "https://a/3"],
        )

    def test_retry_policy_only_retries_transient_failures(self):
        headers = Message()
        headers["Retry-After"] = "2"
        throttled = HTTPError("https://x", 429, "Too Many Requests", headers, None)
        missing = HTTPError("https://x", 404, "Not Found", Message(), None)
        self.assertTrue(image_download._retryable_error(throttled))
        self.assertTrue(image_download._retryable_error(URLError("reset")))
        self.assertFalse(image_download._retryable_error(missing))
        self.assertEqual(image_download._retry_delay(throttled, 0), 2.0)
        self.assertLessEqual(image_download._retry_delay(URLError("reset"), 10), 4.0)

    def test_failed_stream_retries_and_removes_partial_files(self):
        original_validate = image_download.validated_public_http_url
        original_opener = image_download._OPENER
        original_wait = image_download._wait_for_retry
        fake_opener = _BrokenOpener()
        image_download.validated_public_http_url = lambda value: value
        image_download._OPENER = fake_opener
        image_download._wait_for_retry = lambda _seconds: None
        image_download._IMAGE_JOB_CANCEL.clear()
        try:
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory)
                with self.assertRaises(URLError):
                    image_download._download_one(
                        "https://cdn.example.test/image.png",
                        target,
                        "test-image",
                        None,
                    )
                self.assertEqual(fake_opener.calls, image_download.MAX_DOWNLOAD_ATTEMPTS)
                self.assertEqual(list(target.glob("*.part")), [])
                self.assertEqual(list(target.glob("*.png")), [])
        finally:
            image_download.validated_public_http_url = original_validate
            image_download._OPENER = original_opener
            image_download._wait_for_retry = original_wait
            image_download._IMAGE_JOB_CANCEL.clear()

    def test_cancel_without_running_job_is_not_reported_as_success(self):
        if image_download._IMAGE_JOB_LOCK.locked():
            self.skipTest("Unexpected image job is running in this isolated test process")
        cancelled, message = image_download.cancel_image_download_job()
        self.assertFalse(cancelled)
        self.assertIn("No image download job", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
