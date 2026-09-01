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


if __name__ == "__main__":
    unittest.main(verbosity=2)
