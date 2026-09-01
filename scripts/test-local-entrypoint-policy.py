from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import entrypoint  # noqa: E402
import url_policy  # noqa: E402


class LocalEntrypointPolicyTests(unittest.TestCase):
    def test_production_modules_share_the_public_url_validator(self):
        self.assertIs(entrypoint.bridge._valid_source_url, url_policy.is_public_http_url)
        self.assertIs(entrypoint.web_document._safe_http_url, url_policy.is_public_http_url)
        self.assertIs(entrypoint.engine._validated_source_url, url_policy.validated_public_http_url)

    def test_private_urls_are_rejected_before_media_parser_or_download_job(self):
        private_url = "http://127.0.0.1:8080/private.mp4"

        with mock.patch.object(entrypoint, "_original_media_parse") as media_parse:
            payload = entrypoint._hybrid_parse(private_url, "none")
            self.assertFalse(payload["success"])
            self.assertEqual(payload["code"], "BAD_REQUEST")
            media_parse.assert_not_called()

        with self.assertRaises(url_policy.PublicUrlError):
            entrypoint.engine.job_from_payload({"sourceUrl": private_url})

        with self.assertRaises(url_policy.PublicUrlError):
            entrypoint.engine.parse_job(
                "galaxy-downloader://download?url=http%3A%2F%2F127.0.0.1%3A8080%2Fprivate.mp4"
            )

    def test_ambiguous_social_video_returns_media_before_document_scrape(self):
        url = "https://www.instagram.com/p/ABC123/"
        media = {"success": True, "data": {"kind": "video", "title": "video"}}
        with (
            mock.patch.object(entrypoint, "is_public_http_url", return_value=True),
            mock.patch.object(entrypoint, "prefer_media_first", return_value=True),
            mock.patch.object(entrypoint, "_original_media_parse", return_value=media) as media_parse,
            mock.patch.object(entrypoint, "parse_web_document") as document_parse,
            mock.patch.object(entrypoint, "parse_dynamic_web_document") as dynamic_parse,
        ):
            payload = entrypoint._hybrid_parse(url, "none")
        self.assertEqual(payload, media)
        media_parse.assert_called_once_with(url, "none")
        document_parse.assert_not_called()
        dynamic_parse.assert_not_called()

    def test_ambiguous_social_photo_falls_back_to_document_after_media_failure(self):
        url = "https://x.com/demo/status/123"
        media_failure = {"success": False, "code": "PARSE_FAILED", "error": "no playable media"}
        document = {"success": True, "data": {"kind": "image", "images": ["https://img.example/1.jpg"]}}
        with (
            mock.patch.object(entrypoint, "is_public_http_url", return_value=True),
            mock.patch.object(entrypoint, "prefer_media_first", return_value=True),
            mock.patch.object(entrypoint, "should_try_web_document", return_value=True),
            mock.patch.object(entrypoint, "_original_media_parse", return_value=media_failure),
            mock.patch.object(entrypoint, "parse_web_document", return_value=document),
            mock.patch.object(entrypoint, "parse_dynamic_web_document") as dynamic_parse,
        ):
            payload = entrypoint._hybrid_parse(url, "none")
        self.assertEqual(payload, document)
        dynamic_parse.assert_not_called()

    def test_desktop_close_handler_uses_graceful_shutdown_policy(self):
        self.assertIs(entrypoint.engine.EngineWindow.close_app, entrypoint._graceful_close_app)

    def test_non_gui_exit_requests_image_cancel_before_waiting(self):
        fake_lock = mock.Mock()
        fake_lock.locked.side_effect = [True, False]
        with (
            mock.patch.object(entrypoint, "_IMAGE_JOB_LOCK", fake_lock),
            mock.patch.object(entrypoint, "cancel_image_download_job") as cancel,
            mock.patch.object(entrypoint.time, "sleep") as sleep,
        ):
            entrypoint._cancel_image_worker_before_exit(timeout_seconds=1)
        cancel.assert_called_once_with()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
