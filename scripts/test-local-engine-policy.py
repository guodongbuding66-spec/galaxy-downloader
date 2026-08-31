from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


external_ytdlp = load_module(
    "galaxy_external_ytdlp_test",
    ROOT / "local-engine" / "external_ytdlp.py",
)
bridge = load_module(
    "galaxy_bridge_test",
    ROOT / "local-engine" / "bridge.py",
)


class ExternalDownloadPolicyTests(unittest.TestCase):
    def command(self, **overrides):
        options = {
            "format_selector": "bv+ba/b",
            "output_template": "downloads/%(title)s.%(ext)s",
            "ffmpeg_location": Path("ffmpeg/bin"),
            "browser": "none",
            "playlist": False,
            "include_subtitle": False,
            "subtitle_language": None,
            "include_cover": False,
            "collection_mode": "single",
            "selected_items": None,
        }
        options.update(overrides)
        return external_ytdlp.build_external_command(
            Path("yt-dlp.exe"),
            "https://www.instagram.com/p/example/",
            **options,
        )

    def test_default_is_one_final_media_item_without_sidecars(self):
        command = self.command()
        self.assertIn("--ignore-config", command)
        self.assertIn("--no-playlist", command)
        playlist_index = command.index("--playlist-items")
        self.assertEqual(command[playlist_index + 1], "1")
        self.assertIn("--no-write-thumbnail", command)
        self.assertIn("--no-embed-thumbnail", command)
        self.assertNotIn("--write-thumbnail", command)
        self.assertIn("--no-write-info-json", command)
        self.assertIn("--no-write-description", command)
        self.assertIn("--no-write-playlist-metafiles", command)
        self.assertIn("--no-keep-video", command)
        self.assertIn("--no-write-subs", command)

    def test_cover_is_embedded_but_never_kept_as_a_jpg_sidecar(self):
        command = self.command(include_cover=True)
        self.assertIn("--embed-thumbnail", command)
        self.assertNotIn("--write-thumbnail", command)

    def test_entire_collection_is_explicit_opt_in(self):
        command = self.command(collection_mode="all", playlist=True)
        self.assertIn("--yes-playlist", command)
        self.assertNotIn("--no-playlist", command)
        self.assertNotIn("--playlist-items", command)

    def test_selected_collection_items_are_deduplicated_and_scoped(self):
        command = self.command(
            collection_mode="selected",
            selected_items=[3, 1, 3, 0, -2, 2],
        )
        self.assertIn("--yes-playlist", command)
        playlist_index = command.index("--playlist-items")
        self.assertEqual(command[playlist_index + 1], "3,1,2")


class CollectionMetadataTests(unittest.TestCase):
    @staticmethod
    def instagram_carousel_fixture():
        def entry(index: int):
            return {
                "id": f"media-{index}",
                "title": f"Carousel item {index}",
                "duration": 10 + index,
                "thumbnail": f"https://cdn.example/cover-{index}.jpg",
                "formats": [
                    {
                        "format_id": f"muxed-{index}",
                        "url": f"https://cdn.example/video-{index}.mp4?sig=test",
                        "ext": "mp4",
                        "height": 1080,
                        "width": 1080,
                        "fps": 30,
                        "vcodec": "h264",
                        "acodec": "aac",
                        "tbr": 2200,
                    }
                ],
            }

        return {
            "_type": "playlist",
            "id": "instagram-carousel",
            "title": "Instagram carousel",
            "extractor_key": "Instagram",
            "entries": [entry(1), entry(2), entry(3)],
        }

    def test_instagram_style_playlist_is_exposed_as_collection_pages(self):
        raw = self.instagram_carousel_fixture()
        pages = bridge._collection_pages(raw)
        self.assertEqual(len(pages), 3)
        self.assertEqual([page["page"] for page in pages], [1, 2, 3])
        self.assertEqual(pages[1]["cid"], "media-2")
        self.assertEqual(pages[1]["videoAudioMode"], "muxed")
        self.assertTrue(pages[1]["downloadVideoUrl"].endswith("sig=test"))

    def test_normalized_parse_result_keeps_collection_count_and_first_item(self):
        raw = self.instagram_carousel_fixture()
        completed = subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=json.dumps(raw),
            stderr="",
        )
        payload = bridge._success_payload(
            completed,
            "https://www.instagram.com/p/example/",
            "none",
        )
        self.assertTrue(payload["success"])
        data = payload["data"]
        self.assertTrue(data["isMultiPart"])
        self.assertEqual(data["collectionCount"], 3)
        self.assertEqual(data["currentPage"], 1)
        self.assertEqual(len(data["pages"]), 3)
        self.assertEqual(data["platform"], "instagram")


if __name__ == "__main__":
    unittest.main(verbosity=2)
