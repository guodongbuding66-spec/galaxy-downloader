from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import document_policy  # noqa: E402
from document_markdown import extract_document_markdown  # noqa: E402


document_policy.install_document_policy()


class LocalDocumentPolicyTests(unittest.TestCase):
    def test_video_cdn_mp4_is_never_treated_as_image(self):
        self.assertFalse(document_policy._looks_like_image(
            "https://video.twimg.com/ext_tw_video/clip.mp4",
            "video_url",
        ))

    def test_social_document_routing_is_path_sensitive(self):
        self.assertTrue(document_policy.should_try_web_document("https://www.instagram.com/p/ABC123/"))
        self.assertFalse(document_policy.should_try_web_document("https://www.instagram.com/reel/ABC123/"))
        self.assertTrue(document_policy.should_try_web_document("https://www.tiktok.com/@demo/photo/123"))
        self.assertTrue(document_policy.should_try_web_document("https://x.com/demo/status/123"))
        self.assertFalse(document_policy.should_try_web_document("https://www.youtube.com/watch?v=abc"))

    def test_commerce_platform_labels_are_preserved(self):
        fixtures = {
            "https://www.amazon.com/dp/B000000001": "amazon",
            "https://www.ebay.com/itm/123456": "ebay",
            "https://www.aliexpress.com/item/100500000000.html": "aliexpress",
            "https://www.alibaba.com/product-detail/example_1600000000000.html": "alibaba",
        }
        for url, expected in fixtures.items():
            with self.subTest(url=url):
                platform, document_type = document_policy._classify(url, "")
                self.assertEqual(platform, expected)
                self.assertEqual(document_type, "product")

    def test_wechat_markdown_keeps_image_between_paragraphs(self):
        html = """
        <div id="js_content">
          <p>第一段</p>
          <img data-src="https://mmbiz.qpic.cn/mmbiz_jpg/demo/0" alt="示例图">
          <blockquote>注意事项</blockquote>
          <table><tr><th>规格</th><th>值</th></tr><tr><td>宽度</td><td>120</td></tr></table>
          <p>第二段</p>
        </div>
        <div id="js_toobar3">toolbar</div>
        """
        markdown = extract_document_markdown("https://mp.weixin.qq.com/s/demo", html, "wechat")
        self.assertIn("![示例图](https://mmbiz.qpic.cn/mmbiz_jpg/demo/0)", markdown)
        self.assertIn("> 注意事项", markdown)
        self.assertIn("| 规格 | 值 |", markdown)
        self.assertLess(markdown.index("第一段"), markdown.index("![示例图]"))
        self.assertLess(markdown.index("![示例图]"), markdown.index("第二段"))
        self.assertNotIn("toolbar", markdown)


if __name__ == "__main__":
    unittest.main(verbosity=2)
