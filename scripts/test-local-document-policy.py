from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import document_policy  # noqa: E402
import url_policy  # noqa: E402
from document_markdown import extract_document_markdown  # noqa: E402


document_policy.install_document_policy()


class LocalPublicUrlPolicyTests(unittest.TestCase):
    def test_literal_local_private_and_credentialed_urls_are_blocked(self):
        blocked = (
            "http://localhost:8080/video.mp4",
            "http://127.0.0.1/video.mp4",
            "http://10.0.0.5/video.mp4",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.20/video.mp4",
            "http://[::1]/video.mp4",
            "http://[fe80::1%25Ethernet]/video.mp4",
            "https://user:secret@example.com/video.mp4",
            "file:///tmp/video.mp4",
        )
        for value in blocked:
            with self.subTest(value=value):
                self.assertFalse(url_policy.is_public_http_url(value))

    def test_dns_must_resolve_only_to_public_addresses(self):
        public_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0)),
        ]
        with mock.patch.object(url_policy.socket, "getaddrinfo", return_value=public_answer):
            self.assertTrue(url_policy.is_public_http_url("https://media.example/video.mp4"))
            self.assertEqual(
                url_policy.validated_public_http_url("  https://media.example/video.mp4  "),
                "https://media.example/video.mp4",
            )

        mixed_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 443)),
        ]
        with mock.patch.object(url_policy.socket, "getaddrinfo", return_value=mixed_answer):
            self.assertFalse(url_policy.is_public_http_url("https://mixed.example/video.mp4"))

    def test_dns_resolution_failure_is_fail_closed(self):
        with mock.patch.object(url_policy.socket, "getaddrinfo", side_effect=socket.gaierror("no dns")):
            self.assertFalse(url_policy.is_public_http_url("https://unresolved.example/video.mp4"))
            with self.assertRaises(url_policy.PublicUrlError):
                url_policy.validated_public_http_url("https://unresolved.example/video.mp4")


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

    def test_challenge_pages_are_not_reported_as_articles(self):
        payload = document_policy._document_payload(
            "https://mp.weixin.qq.com/s/demo",
            '<html><iframe src="https://captcha.gtimg.com/static/template/drag.html"></iframe></html>',
            "https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?target_url=test",
            "none",
        )
        self.assertIsInstance(payload, dict)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["code"], "AUTH_REQUIRED")
        self.assertTrue(payload["details"]["documentChallenge"])

    def test_empty_product_shell_falls_through_to_cdp(self):
        payload = document_policy._document_payload(
            "https://www.amazon.com/dp/B000000001",
            "<html><head><title>Amazon</title></head><body><div id='root'></div></body></html>",
            "https://www.amazon.com/dp/B000000001",
            "none",
        )
        self.assertIsNone(payload)

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
