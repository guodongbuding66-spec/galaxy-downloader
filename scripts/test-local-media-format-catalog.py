from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from media_format_catalog import (  # noqa: E402
    MediaFormatError,
    build_media_format_catalog,
    exact_format_selector,
    public_media_format_catalog,
    run_media_format_catalog_self_test,
    validate_format_id,
)


class MediaFormatCatalogTests(unittest.TestCase):
    def formats(self):
        return [
            {
                "format_id": "399",
                "url": "https://cdn.example/1080-av1",
                "vcodec": "av01.0.08M.08",
                "acodec": "none",
                "width": 1920,
                "height": 1080,
                "fps": 60,
                "ext": "mp4",
                "vbr": 2800,
                "tbr": 2820,
                "filesize_approx": 101_000_000,
                "dynamic_range": "SDR",
                "protocol": "https",
            },
            {
                "format_id": "137",
                "url": "https://cdn.example/1080-avc",
                "vcodec": "avc1.640028",
                "acodec": "none",
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "ext": "mp4",
                "vbr": 4500,
                "filesize": 140_000_000,
                "dynamic_range": "SDR",
            },
            {
                "format_id": "22",
                "url": "https://cdn.example/720-muxed",
                "vcodec": "avc1.64001F",
                "acodec": "mp4a.40.2",
                "width": 1280,
                "height": 720,
                "fps": 30,
                "ext": "mp4",
                "tbr": 1800,
            },
            {
                "format_id": "251",
                "url": "https://cdn.example/audio-opus",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 160,
                "asr": 48000,
                "audio_channels": 2,
                "ext": "webm",
                "language": "en",
            },
            {
                "format_id": "140",
                "url": "https://cdn.example/audio-aac",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "abr": 128,
                "asr": 44100,
                "audio_channels": 2,
                "ext": "m4a",
            },
        ]

    def test_builds_real_video_and_audio_options_without_urls(self) -> None:
        catalog = build_media_format_catalog(self.formats())
        self.assertEqual([item.format_id for item in catalog.video_options], ["399", "137", "22"])
        self.assertEqual([item.format_id for item in catalog.audio_options], ["251", "140"])
        self.assertEqual(catalog.video_options[0].stream_type, "video-only")
        self.assertEqual(catalog.video_options[-1].stream_type, "muxed")
        self.assertEqual(catalog.audio_options[0].stream_type, "audio-only")
        public = public_media_format_catalog(catalog)
        self.assertEqual(public["defaultVideoId"], "video:399")
        self.assertEqual(public["defaultAudioId"], "audio:251")
        rendered = repr(public)
        self.assertNotIn("cdn.example", rendered)
        self.assertNotIn("downloadUrl", rendered)

    def test_keeps_real_stream_metadata(self) -> None:
        catalog = build_media_format_catalog(self.formats())
        video = public_media_format_catalog(catalog)["videoOptions"][0]
        self.assertEqual(video["formatId"], "399")
        self.assertEqual(video["height"], 1080)
        self.assertEqual(video["fps"], 60.0)
        self.assertEqual(video["videoCodec"], "av01.0.08M.08")
        self.assertEqual(video["videoBitrate"], 2800.0)
        self.assertEqual(video["dynamicRange"], "SDR")
        self.assertEqual(video["filesizeApprox"], 101_000_000)
        self.assertEqual(video["featureTags"], [])
        self.assertIsNone(video["formatNote"])

        audio = public_media_format_catalog(catalog)["audioOptions"][0]
        self.assertEqual(audio["formatId"], "251")
        self.assertEqual(audio["audioCodec"], "opus")
        self.assertEqual(audio["audioBitrate"], 160.0)
        self.assertEqual(audio["audioChannels"], 2)
        self.assertEqual(audio["sampleRate"], 48000)
        self.assertEqual(audio["language"], "en")
        self.assertEqual(audio["featureTags"], [])

    def test_bilibili_premium_video_capabilities_are_metadata_driven(self) -> None:
        catalog = build_media_format_catalog(
            [
                {
                    "format_id": "bili-8k-dv",
                    "url": "https://cdn.example/bili-8k-dv",
                    "vcodec": "hev1.08.09",
                    "acodec": "none",
                    "width": 7680,
                    "height": 4320,
                    "fps": 60,
                    "dynamic_range": "DV",
                    "format_note": "8K 超高清 杜比视界",
                    "ext": "mp4",
                },
                {
                    "format_id": "bili-4k-hdr",
                    "url": "https://cdn.example/bili-4k-hdr",
                    "vcodec": "hev1",
                    "acodec": "none",
                    "width": 3840,
                    "height": 2160,
                    "dynamic_range": "HDR10",
                    "format_note": "4K 超清 HDR 真彩",
                    "ext": "mp4",
                },
            ]
        )
        public = public_media_format_catalog(catalog)
        eight_k = public["videoOptions"][0]
        four_k = public["videoOptions"][1]
        self.assertEqual(eight_k["featureTags"], ["8k", "dolby-vision", "hdr"])
        self.assertEqual(eight_k["formatNote"], "8K 超高清 杜比视界")
        self.assertIn("8K", eight_k["label"])
        self.assertIn("DOLBY VISION", eight_k["label"])
        self.assertEqual(four_k["featureTags"], ["4k", "hdr"])
        self.assertIn("HDR10", four_k["label"])

    def test_bilibili_premium_audio_requires_explicit_metadata(self) -> None:
        catalog = build_media_format_catalog(
            [
                {
                    "format_id": "bili-hires",
                    "url": "https://cdn.example/bili-hires",
                    "vcodec": "none",
                    "acodec": "flac",
                    "abr": 1500,
                    "asr": 96000,
                    "format_note": "Hi-Res无损",
                    "ext": "flac",
                },
                {
                    "format_id": "bili-atmos",
                    "url": "https://cdn.example/bili-atmos",
                    "vcodec": "none",
                    "acodec": "ec-3",
                    "abr": 768,
                    "format_note": "杜比全景声 Dolby Atmos",
                    "ext": "m4a",
                },
                {
                    "format_id": "generic-eac3",
                    "url": "https://cdn.example/generic-eac3",
                    "vcodec": "none",
                    "acodec": "ec-3",
                    "abr": 640,
                    "asr": 96000,
                    "ext": "m4a",
                },
            ]
        )
        public = public_media_format_catalog(catalog)
        by_id = {item["formatId"]: item for item in public["audioOptions"]}
        self.assertEqual(by_id["bili-hires"]["featureTags"], ["hi-res"])
        self.assertIn("HI-RES", by_id["bili-hires"]["label"])
        self.assertEqual(by_id["bili-atmos"]["featureTags"], ["dolby-atmos"])
        self.assertIn("DOLBY ATMOS", by_id["bili-atmos"]["label"])
        # High sample-rate/E-AC-3 alone is not enough evidence for either flag.
        self.assertEqual(by_id["generic-eac3"]["featureTags"], [])

    def test_deduplicates_format_ids_after_sorting(self) -> None:
        formats = self.formats()
        formats.append(
            {
                "format_id": "137",
                "url": "https://cdn.example/duplicate-low",
                "vcodec": "avc1",
                "acodec": "none",
                "height": 360,
                "fps": 30,
                "ext": "mp4",
            }
        )
        catalog = build_media_format_catalog(formats)
        ids = [item.format_id for item in catalog.video_options]
        self.assertEqual(ids.count("137"), 1)
        selected = next(item for item in catalog.video_options if item.format_id == "137")
        self.assertEqual(selected.height, 1080)

    def test_ignores_non_downloadable_and_unsafe_format_ids(self) -> None:
        formats = self.formats() + [
            {
                "format_id": "missing-url",
                "vcodec": "avc1",
                "acodec": "none",
                "height": 2160,
            },
            {
                "format_id": "137+251/best",
                "url": "https://cdn.example/injection",
                "vcodec": "avc1",
                "acodec": "none",
                "height": 4320,
            },
        ]
        catalog = build_media_format_catalog(formats)
        ids = {item.format_id for item in catalog.video_options}
        self.assertNotIn("missing-url", ids)
        self.assertNotIn("137+251/best", ids)

    def test_exact_selector_uses_only_validated_ids(self) -> None:
        self.assertEqual(
            exact_format_selector(video_format_id="399", audio_format_id="251"),
            "399+251",
        )
        self.assertEqual(
            exact_format_selector(video_format_id="22", audio_format_id="251", selected_video_has_audio=True),
            "22",
        )
        self.assertEqual(
            exact_format_selector(video_format_id="399", audio_format_id="251", include_audio=False),
            "399",
        )
        self.assertEqual(exact_format_selector(audio_format_id="251"), "251")
        for malicious in ("", "../137", "137+251", "best[height<=1080]", "137/22", "137,22"):
            with self.subTest(malicious=malicious):
                with self.assertRaises(MediaFormatError):
                    validate_format_id(malicious)

    def test_empty_catalog_and_limits_fail_closed(self) -> None:
        catalog = build_media_format_catalog(None)
        self.assertEqual(catalog.video_options, ())
        self.assertEqual(catalog.audio_options, ())
        self.assertIsNone(catalog.default_video_id)
        self.assertIsNone(catalog.default_audio_id)
        with self.assertRaises(MediaFormatError):
            build_media_format_catalog([], max_video_options=0)
        with self.assertRaises(MediaFormatError):
            exact_format_selector()

    def test_option_limits_are_bounded(self) -> None:
        formats = []
        for index in range(100):
            formats.append(
                {
                    "format_id": f"v{index}",
                    "url": f"https://cdn.example/v{index}",
                    "vcodec": "avc1",
                    "acodec": "none",
                    "height": 360 + index,
                }
            )
            formats.append(
                {
                    "format_id": f"a{index}",
                    "url": f"https://cdn.example/a{index}",
                    "vcodec": "none",
                    "acodec": "opus",
                    "abr": 64 + index,
                }
            )
        catalog = build_media_format_catalog(formats)
        self.assertEqual(len(catalog.video_options), 40)
        self.assertEqual(len(catalog.audio_options), 30)

    def test_embedded_self_test(self) -> None:
        run_media_format_catalog_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
