from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-engine"))

import nfo_sidecar as nfo  # noqa: E402


class NfoSidecarTests(unittest.TestCase):
    def sample(self) -> dict[str, object]:
        return {
            "id": "BV1demo",
            "extractor_key": "BiliBili",
            "title": "Demo & <video>",
            "description": "First line & second line",
            "channel": "Demo Channel",
            "upload_date": "20260909",
            "duration": 125,
            "categories": ["Technology", "Technology", "Tutorial"],
            "tags": ["demo", "demo", "test"],
            "thumbnail": "https://i.example.test/cover.jpg?x=1&y=2",
        }

    def bangumi_sample(self) -> dict[str, object]:
        return {
            "id": "267851",
            "extractor_key": "BiliBiliBangumi",
            "title": "1 残酷",
            "description": "少年踏上旅程",
            "series": "鬼灭之刃",
            "series_id": "4358",
            "season": "立志篇",
            "season_id": "26801",
            "season_number": 1,
            "episode": "残酷",
            "episode_id": "267851",
            "episode_number": 1,
            "upload_date": "20190406",
            "duration": 1425.256,
            "thumbnail": "https://i.example.test/bangumi.jpg",
        }

    def test_parse_info_json_requires_bounded_utf8_object(self) -> None:
        parsed = nfo.parse_info_json(json.dumps(self.sample()).encode("utf-8"))
        self.assertEqual(parsed["id"], "BV1demo")

        for invalid in (b"", b"{", b"[]", b"\xff"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(nfo.NfoSidecarError):
                    nfo.parse_info_json(invalid)

        with patch.object(nfo, "MAX_INFO_JSON_BYTES", 8):
            with self.assertRaises(nfo.NfoSidecarError):
                nfo.parse_info_json(b'{"title":"too long"}')

    def test_render_nfo_is_deterministic_escaped_and_bounded(self) -> None:
        rendered = nfo.render_nfo(self.sample())
        self.assertTrue(rendered.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<movie>'))
        self.assertIn("<title>Demo &amp; &lt;video&gt;</title>", rendered)
        self.assertIn("<plot>First line &amp; second line</plot>", rendered)
        self.assertIn("<studio>Demo Channel</studio>", rendered)
        self.assertIn("<premiered>2026-09-09</premiered>", rendered)
        self.assertIn("<runtime>2</runtime>", rendered)
        self.assertIn('<uniqueid type="bilibili" default="true">BV1demo</uniqueid>', rendered)
        self.assertEqual(rendered.count("<genre>Technology</genre>"), 1)
        self.assertEqual(rendered.count("<tag>demo</tag>"), 1)
        self.assertIn("<tag>test</tag>", rendered)
        self.assertIn("<thumb>https://i.example.test/cover.jpg?x=1&amp;y=2</thumb>", rendered)
        self.assertEqual(rendered, nfo.render_nfo(self.sample()))
        self.assertEqual(nfo._bounded_list({"beta", "alpha", "beta"}), ("alpha", "beta"))

    def test_bilibili_bangumi_renders_episode_details(self) -> None:
        rendered = nfo.render_nfo(self.bangumi_sample())
        self.assertTrue(rendered.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<episodedetails>'))
        self.assertIn("<title>残酷</title>", rendered)
        self.assertNotIn("<title>1 残酷</title>", rendered)
        self.assertIn("<showtitle>鬼灭之刃</showtitle>", rendered)
        self.assertIn("<season>1</season>", rendered)
        self.assertIn("<episode>1</episode>", rendered)
        self.assertIn("<aired>2019-04-06</aired>", rendered)
        self.assertNotIn("<premiered>", rendered)
        self.assertIn("<runtime>24</runtime>", rendered)
        self.assertIn('<uniqueid type="bilibili" default="true">267851</uniqueid>', rendered)
        self.assertTrue(rendered.rstrip().endswith("</episodedetails>"))

    def test_episode_detection_is_fail_closed_and_numbers_are_bounded(self) -> None:
        series_only = self.sample() | {"series": "A collection"}
        rendered = nfo.render_nfo(series_only)
        self.assertIn("<movie>", rendered)
        self.assertNotIn("<episodedetails>", rendered)
        self.assertNotIn("<showtitle>", rendered)

        invalid_numbers = self.bangumi_sample() | {
            "season_number": -1,
            "episode_number": 1.5,
        }
        rendered_episode = nfo.render_nfo(invalid_numbers)
        self.assertIn("<episodedetails>", rendered_episode)
        self.assertNotIn("<season>", rendered_episode)
        self.assertNotIn("<episode>1.5</episode>", rendered_episode)
        self.assertNotIn("<episode>", rendered_episode)

        self.assertEqual(nfo._bounded_nonnegative_integer(0, 10), "0")
        self.assertEqual(nfo._bounded_nonnegative_integer("10", 10), "10")
        self.assertEqual(nfo._bounded_nonnegative_integer(True, 10), "")
        self.assertEqual(nfo._bounded_nonnegative_integer(1.25, 10), "")
        self.assertEqual(nfo._bounded_nonnegative_integer(11, 10), "")

    def test_render_nfo_rejects_missing_title_and_unsafe_thumbnail(self) -> None:
        with self.assertRaises(nfo.NfoSidecarError):
            nfo.render_nfo({"description": "no title"})

        rendered = nfo.render_nfo({
            "id": "id-1",
            "title": "Safe",
            "thumbnail": "file:///tmp/secret.jpg",
            "duration": float("inf"),
            "upload_date": "2026/09/09",
        })
        self.assertNotIn("<thumb>", rendered)
        self.assertNotIn("<runtime>", rendered)
        self.assertNotIn("<premiered>", rendered)

    def test_output_path_strips_info_json_suffix(self) -> None:
        self.assertEqual(
            nfo.nfo_output_path(Path("video [id].info.json")),
            Path("video [id].nfo"),
        )
        self.assertEqual(nfo.nfo_output_path(Path("metadata.json")), Path("metadata.nfo"))

    def test_file_conversion_is_atomic_and_can_remove_intermediate_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Demo [BV1demo].info.json"
            source.write_text(json.dumps(self.sample(), ensure_ascii=False), encoding="utf-8")

            target = nfo.convert_info_json_file(source, remove_source=True)
            self.assertEqual(target, root / "Demo [BV1demo].nfo")
            self.assertTrue(target.is_file())
            self.assertFalse(source.exists())
            self.assertIn("<title>Demo &amp; &lt;video&gt;</title>", target.read_text(encoding="utf-8"))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_file_conversion_preserves_source_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Demo.info.json"
            source.write_text(json.dumps(self.sample()), encoding="utf-8")
            target = nfo.convert_info_json_file(source)
            self.assertTrue(source.exists())
            self.assertTrue(target.exists())

    def test_refuses_symlinked_input_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_source = root / "real.info.json"
            real_source.write_text(json.dumps(self.sample()), encoding="utf-8")
            linked_source = root / "linked.info.json"
            try:
                linked_source.symlink_to(real_source.name)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this platform")
            with self.assertRaises(nfo.NfoSidecarError):
                nfo.convert_info_json_file(linked_source)

            target = root / "real.nfo"
            protected = root / "protected.txt"
            protected.write_text("do not replace", encoding="utf-8")
            target.symlink_to(protected.name)
            with self.assertRaises(nfo.NfoSidecarError):
                nfo.convert_info_json_file(real_source)
            self.assertEqual(protected.read_text(encoding="utf-8"), "do not replace")

    def test_self_test(self) -> None:
        nfo.run_nfo_sidecar_self_test()


if __name__ == "__main__":
    unittest.main()
