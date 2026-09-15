from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import headless_service
import hotmart_course_provider as hotmart


class HotmartCourseProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch(
            "hotmart_course_provider.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_signed_query_is_preserved_and_candidates_are_deduplicated(self) -> None:
        signed = "https://cdn.example.com/master.m3u8?Policy=abc&Signature=xyz&Key-Pair-Id=123"
        ranked = hotmart.rank_hotmart_candidates(
            [
                hotmart.HotmartMediaCandidate(signed, "application/vnd.apple.mpegurl", "network", "req-1"),
                hotmart.HotmartMediaCandidate(signed, "application/vnd.apple.mpegurl", "performance", ""),
                hotmart.HotmartMediaCandidate("https://cdn.example.com/video.mp4?token=1", "video/mp4", "dom", ""),
            ]
        )
        self.assertEqual(ranked[0].url, signed)
        self.assertEqual(sum(item.url == signed for item in ranked), 1)
        self.assertIn("Signature=xyz", ranked[0].url)

    def test_blob_and_non_http_candidates_are_not_ranked(self) -> None:
        ranked = hotmart.rank_hotmart_candidates(
            [
                hotmart.HotmartMediaCandidate("blob:https://cdn.example.com/abc", "video/mp4", "dom", ""),
                hotmart.HotmartMediaCandidate("file:///tmp/video.mp4", "video/mp4", "dom", ""),
                hotmart.HotmartMediaCandidate("https://cdn.example.com/video.mp4", "video/mp4", "dom", ""),
            ]
        )
        self.assertEqual([item.url for item in ranked], ["https://cdn.example.com/video.mp4"])

    def test_drm_manifests_fail_detection(self) -> None:
        self.assertTrue(
            hotmart.manifest_uses_drm(
                "<MPD><ContentProtection schemeIdUri='urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed'/></MPD>",
                kind="dash",
            )
        )
        self.assertTrue(
            hotmart.manifest_uses_drm(
                '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://key"',
                kind="hls",
            )
        )
        self.assertFalse(hotmart.manifest_uses_drm("#EXTM3U\n#EXTINF:6,\nsegment.ts", kind="hls"))

    def test_hotmart_member_url_rejects_plain_club_login_host(self) -> None:
        with self.assertRaises(hotmart.HotmartCourseError):
            hotmart.register_hotmart_download_authorization(
                browser="chrome",
                referer="https://club.hotmart.com/oauth/login",
            )

    def test_authorization_token_is_random_process_local_and_forgery_fails(self) -> None:
        first = hotmart.register_hotmart_download_authorization(
            browser="chrome",
            referer="https://my-course.club.hotmart.com/lesson/abc/start",
        )
        second = hotmart.register_hotmart_download_authorization(
            browser="chrome",
            referer="https://my-course.club.hotmart.com/lesson/abc/start",
        )
        self.addCleanup(hotmart.revoke_hotmart_download_authorization, first)
        self.addCleanup(hotmart.revoke_hotmart_download_authorization, second)
        self.assertNotEqual(first, second)
        self.assertGreater(len(first), 30)
        with self.assertRaisesRegex(hotmart.HotmartCourseError, "无效或已过期"):
            hotmart._authorization_context("forged-public-token")

    def test_trusted_auth_layer_adds_only_browser_cookie_source_and_referer(self) -> None:
        hotmart.install_headless_hotmart_authorization()
        token = hotmart.register_hotmart_download_authorization(
            browser="edge",
            referer="https://my-course.club.hotmart.com/lesson/abc/start?lesson=1",
        )
        self.addCleanup(hotmart.revoke_hotmart_download_authorization, token)
        with tempfile.TemporaryDirectory() as directory:
            options = headless_service._download_options(
                {
                    "sourceUrl": "https://cdn.example.com/video.mp4?Signature=abc",
                    "_hotmartAuthorizationToken": token,
                    "cookie": "must-not-be-used",
                    "cookieFile": "../../cookies.txt",
                    "httpHeaders": {"Authorization": "must-not-be-used"},
                },
                Path(directory),
                lambda _event: None,
            )
        self.assertEqual(options["cookiesfrombrowser"][0], "edge")
        self.assertEqual(
            options["http_headers"]["Referer"],
            "https://my-course.club.hotmart.com/lesson/abc/start?lesson=1",
        )
        self.assertNotIn("Authorization", options["http_headers"])
        self.assertNotIn("cookiefile", options)

    def test_forged_internal_token_fails_closed_in_download_options(self) -> None:
        hotmart.install_headless_hotmart_authorization()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(hotmart.HotmartCourseError, "无效或已过期"):
                headless_service._download_options(
                    {
                        "sourceUrl": "https://cdn.example.com/video.mp4",
                        "_hotmartAuthorizationToken": "forged-public-token",
                    },
                    Path(directory),
                    lambda _event: None,
                )


if __name__ == "__main__":
    unittest.main()
