from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from bridge import _success_payload  # noqa: E402


class BridgeFormatCatalogTests(unittest.TestCase):
    @staticmethod
    def completed(payload: dict) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    @staticmethod
    def formats(prefix: str = "") -> list[dict]:
        return [
            {
                "format_id": f"{prefix}399" if prefix else "399",
                "url": f"https://signed.example/{prefix}video-1080",
                "vcodec": "av01.0.08M.08",
                "acodec": "none",
                "width": 1920,
                "height": 1080,
                "fps": 60,
                "vbr": 2800,
                "ext": "mp4",
                "dynamic_range": "HDR10",
                "filesize_approx": 100_000_000,
            },
            {
                "format_id": f"{prefix}22" if prefix else "22",
                "url": f"https://signed.example/{prefix}video-720",
                "vcodec": "avc1.64001F",
                "acodec": "mp4a.40.2",
                "width": 1280,
                "height": 720,
                "fps": 30,
                "tbr": 1800,
                "ext": "mp4",
            },
            {
                "format_id": f"{prefix}251" if prefix else "251",
                "url": f"https://signed.example/{prefix}audio",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 160,
                "asr": 48000,
                "audio_channels": 2,
                "ext": "webm",
            },
        ]

    def test_single_item_exposes_real_catalog_and_preserves_legacy_fields(self) -> None:
        result = _success_payload(
            self.completed(
                {
                    "id": "video-1",
                    "title": "Test video",
                    "extractor_key": "Youtube",
                    "duration": 120,
                    "formats": self.formats(),
                }
            ),
            "https://example.com/watch?v=1",
            "none",
        )
        self.assertTrue(result["success"])
        data = result["data"]

        catalog = data["formatCatalog"]
        self.assertEqual(catalog["defaultVideoId"], "video:399")
        self.assertEqual(catalog["defaultAudioId"], "audio:251")
        self.assertEqual(catalog["videoOptions"][0]["formatId"], "399")
        self.assertEqual(catalog["videoOptions"][0]["height"], 1080)
        self.assertEqual(catalog["videoOptions"][0]["dynamicRange"], "HDR10")
        self.assertEqual(catalog["audioOptions"][0]["formatId"], "251")

        self.assertIn("qualityOptions", data)
        self.assertGreater(len(data["qualityOptions"]), 0)
        self.assertIn("downloadVideoUrl", data)
        self.assertIn("downloadAudioUrl", data)
        self.assertTrue(str(data["downloadVideoUrl"]).startswith("https://signed.example/"))

        rendered_catalog = json.dumps(catalog)
        self.assertNotIn("signed.example", rendered_catalog)
        self.assertNotIn("downloadUrl", rendered_catalog)

    def test_collection_pages_each_receive_their_own_catalog(self) -> None:
        result = _success_payload(
            self.completed(
                {
                    "id": "collection",
                    "title": "Series",
                    "extractor_key": "Bilibili",
                    "entries": [
                        {
                            "id": "p1",
                            "title": "Part 1",
                            "formats": self.formats("p1-"),
                        },
                        {
                            "id": "p2",
                            "title": "Part 2",
                            "formats": self.formats("p2-"),
                        },
                    ],
                }
            ),
            "https://example.com/collection",
            "none",
        )
        data = result["data"]
        self.assertTrue(data["isMultiPart"])
        self.assertEqual(len(data["pages"]), 2)
        self.assertEqual(data["pages"][0]["formatCatalog"]["defaultVideoId"], "video:p1-399")
        self.assertEqual(data["pages"][0]["formatCatalog"]["defaultAudioId"], "audio:p1-251")
        self.assertEqual(data["pages"][1]["formatCatalog"]["defaultVideoId"], "video:p2-399")
        self.assertEqual(data["pages"][1]["formatCatalog"]["defaultAudioId"], "audio:p2-251")
        for page in data["pages"]:
            self.assertIn("qualityOptions", page)
            catalog_text = json.dumps(page["formatCatalog"])
            self.assertNotIn("signed.example", catalog_text)
            self.assertNotIn("downloadUrl", catalog_text)

    def test_empty_formats_return_stable_empty_catalog(self) -> None:
        result = _success_payload(
            self.completed(
                {
                    "id": "no-formats",
                    "title": "No formats",
                    "url": "https://signed.example/fallback",
                }
            ),
            "https://example.com/no-formats",
            "none",
        )
        catalog = result["data"]["formatCatalog"]
        self.assertEqual(catalog["videoOptions"], [])
        self.assertEqual(catalog["audioOptions"], [])
        self.assertIsNone(catalog["defaultVideoId"])
        self.assertIsNone(catalog["defaultAudioId"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
