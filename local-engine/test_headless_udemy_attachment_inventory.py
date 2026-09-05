from __future__ import annotations

import unittest

from headless_udemy_attachment_inventory import (
    _attach_inventory_tokens,
    _consume_inventory,
    _inventory_by_lecture,
)
from yt_dlp.utils import smuggle_url


class HeadlessUdemyAttachmentInventoryTests(unittest.TestCase):
    def test_curriculum_inventory_drops_urls_secrets_and_invalid_assets(self) -> None:
        response = {
            "results": [
                {
                    "_class": "lecture",
                    "id": 123,
                    "supplementary_assets": [
                        {
                            "id": 501,
                            "title": "Starter Files",
                            "filename": "../../starter.zip",
                            "asset_type": "File",
                            "download_urls": {
                                "File": [{"file": "https://cdn.example/starter.zip?token=SECRET"}]
                            },
                            "external_url": "https://evil.example/?secret=SECRET",
                        },
                        {
                            "id": "not-numeric",
                            "title": "Ignored",
                            "filename": "ignored.txt",
                            "asset_type": "File",
                        },
                    ],
                },
                {"_class": "chapter", "id": 9, "title": "Chapter"},
            ]
        }
        inventory = _inventory_by_lecture(response)
        self.assertEqual(
            inventory,
            {
                "123": [
                    {
                        "providerAttachmentId": "udemy:asset:501",
                        "title": "Starter Files",
                        "fileName": "starter.zip",
                        "assetType": "File",
                    }
                ]
            },
        )
        rendered = str(inventory)
        self.assertNotIn("SECRET", rendered)
        self.assertNotIn("download_urls", rendered)
        self.assertNotIn("external_url", rendered)
        self.assertNotIn("https://", rendered)

    def test_inventory_token_is_short_one_shot_and_preserves_course_smuggle_data(self) -> None:
        lecture_url = smuggle_url(
            "https://www.udemy.com/python/learn/v4/t/lecture/123",
            {"course_id": "456"},
        )
        entries = [{"_type": "url_transparent", "url": lecture_url, "title": "Lesson"}]
        inventory = {
            "123": [
                {
                    "providerAttachmentId": "udemy:asset:501",
                    "title": "Starter Files",
                    "fileName": "starter.zip",
                    "assetType": "File",
                }
            ]
        }
        updated = _attach_inventory_tokens(entries, inventory)
        self.assertEqual(len(updated), 1)
        self.assertNotEqual(updated[0]["url"], lecture_url)
        self.assertNotIn("Starter Files", updated[0]["url"])
        self.assertNotIn("starter.zip", updated[0]["url"])

        result = _consume_inventory(
            updated[0]["url"],
            {"id": "9001", "title": "Lesson", "extractor_key": "Udemy"},
        )
        self.assertEqual(
            result["_galaxyCourseAttachmentInventory"],
            {
                "provider": "udemy",
                "providerLectureId": "udemy:lecture:123",
                "attachments": inventory["123"],
            },
        )
        repeated = _consume_inventory(
            updated[0]["url"],
            {"id": "9001", "title": "Lesson", "extractor_key": "Udemy"},
        )
        self.assertNotIn("_galaxyCourseAttachmentInventory", repeated)

    def test_empty_authorized_inventory_is_preserved_for_stale_clear(self) -> None:
        entries = [{
            "_type": "url_transparent",
            "url": smuggle_url(
                "https://www.udemy.com/python/learn/v4/t/lecture/321",
                {"course_id": "654"},
            ),
        }]
        updated = _attach_inventory_tokens(entries, {"321": []})
        result = _consume_inventory(updated[0]["url"], {"id": "10", "extractor_key": "Udemy"})
        self.assertEqual(result["_galaxyCourseAttachmentInventory"]["attachments"], [])
        self.assertEqual(
            result["_galaxyCourseAttachmentInventory"]["providerLectureId"],
            "udemy:lecture:321",
        )


if __name__ == "__main__":
    unittest.main()
