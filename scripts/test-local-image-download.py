from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import image_download  # noqa: E402


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
