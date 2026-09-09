from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import bilibili_danmaku_convert as convert  # noqa: E402


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<i>
  <d p="1.25,1,25,16711680,1700000000,0,user-a,row-a">Hello &amp; world</d>
  <d p="2.50,5,30,255,1700000001,0,user-b,row-b">Top {brace}\\path</d>
  <d p="3.75,4,28,65280,1700000002,0,user-c,row-c">Bottom</d>
  <d p="4.00,6,24,16777215,1700000003,0,user-d,row-d">Reverse</d>
  <d p="bad,1,25,16777215">Malformed time</d>
  <d p="5.00,1,25,99999999">Bad color</d>
  <d p="6.00,1">Missing fields</d>
</i>
"""


class BilibiliDanmakuConvertTests(unittest.TestCase):
    def test_parser_normalizes_valid_comments_and_skips_bad_rows(self) -> None:
        comments = convert.parse_bilibili_danmaku_xml(SAMPLE_XML)
        self.assertEqual(len(comments), 4)
        self.assertEqual(comments[0].time, 1.25)
        self.assertEqual(comments[0].mode, 1)
        self.assertEqual(comments[0].color, 0xFF0000)
        self.assertEqual(comments[0].timestamp, 1700000000)
        self.assertEqual(comments[0].user_hash, "user-a")
        self.assertEqual(comments[0].row_id, "row-a")
        self.assertEqual(comments[0].text, "Hello & world")

    def test_parser_clamps_font_and_text_lengths(self) -> None:
        xml = f'<i><d p="0,1,999,1">{"x" * (convert.MAX_TEXT_CHARS + 50)}</d></i>'
        comment = convert.parse_bilibili_danmaku_xml(xml)[0]
        self.assertEqual(comment.font_size, convert.MAX_FONT_SIZE)
        self.assertEqual(len(comment.text), convert.MAX_TEXT_CHARS)

    def test_dangerous_and_invalid_xml_fail_closed(self) -> None:
        with self.assertRaises(convert.BilibiliDanmakuConversionError):
            convert.parse_bilibili_danmaku_xml(
                '<!DOCTYPE i [<!ENTITY x "boom">]><i><d p="0,1,25,1">&x;</d></i>'
            )
        with self.assertRaises(convert.BilibiliDanmakuConversionError):
            convert.parse_bilibili_danmaku_xml("<i><d></i>")
        with self.assertRaises(convert.BilibiliDanmakuConversionError):
            convert.parse_bilibili_danmaku_xml("")

    def test_byte_and_comment_limits_are_enforced(self) -> None:
        with patch.object(convert, "MAX_XML_BYTES", 20):
            with self.assertRaises(convert.BilibiliDanmakuConversionError):
                convert.parse_bilibili_danmaku_xml("<i>" + ("x" * 30) + "</i>")

        xml = '<i><d p="0,1,25,1">a</d><d p="1,1,25,1">b</d><d p="2,1,25,1">c</d></i>'
        with patch.object(convert, "MAX_COMMENTS", 2):
            with self.assertRaises(convert.BilibiliDanmakuConversionError):
                convert.parse_bilibili_danmaku_xml(xml)

    def test_json_is_versioned_and_deterministic(self) -> None:
        comments = convert.parse_bilibili_danmaku_xml(SAMPLE_XML)
        first = convert.render_danmaku_json(comments)
        second = convert.render_danmaku_json(comments)
        self.assertEqual(first, second)
        payload = json.loads(first)
        self.assertEqual(payload["schema"], "galaxy.bilibili.danmaku.v1")
        self.assertEqual(payload["count"], 4)
        self.assertEqual(payload["comments"][0]["text"], "Hello & world")

    def test_ass_supports_scroll_fixed_reverse_color_and_escaping(self) -> None:
        comments = convert.parse_bilibili_danmaku_xml(SAMPLE_XML)
        ass = convert.render_danmaku_ass(comments, width=1280, height=720)
        self.assertIn("PlayResX: 1280", ass)
        self.assertIn("PlayResY: 720", ass)
        self.assertIn(r"\move(", ass)
        self.assertIn(r"\an8\pos(640,30)", ass)
        self.assertIn(r"\an2\pos(640,692)", ass)
        self.assertIn("&H000000FF", ass)  # RGB red becomes ASS BGR red
        self.assertIn(r"Top \{brace\}\\path", ass.replace(r"\\{", r"\{").replace(r"\\}", r"\}"))

        dialogue_lines = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
        self.assertEqual(len(dialogue_lines), 4)
        scrolling = dialogue_lines[0]
        reverse = dialogue_lines[3]
        self.assertRegex(scrolling, r"move\(1\d{3},\d+,-\d+,\d+\)")
        self.assertRegex(reverse, r"move\(-\d+,\d+,1\d{3},\d+\)")

    def test_invalid_ass_dimensions_fail_closed(self) -> None:
        comments = convert.parse_bilibili_danmaku_xml(SAMPLE_XML)
        with self.assertRaises(convert.BilibiliDanmakuConversionError):
            convert.render_danmaku_ass(comments, width=100, height=100)
        with self.assertRaises(convert.BilibiliDanmakuConversionError):
            convert.render_danmaku_ass(comments, width=100_000, height=1080)

    def test_file_conversion_writes_only_requested_sibling_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "video.danmaku.xml"
            source.write_text(SAMPLE_XML, encoding="utf-8")

            outputs = convert.convert_danmaku_file(source, formats=("ass", "json"), width=1280, height=720)
            self.assertEqual(outputs["ass"], root / "video.danmaku.ass")
            self.assertEqual(outputs["json"], root / "video.danmaku.json")
            self.assertTrue(outputs["ass"].is_file())
            self.assertTrue(outputs["json"].is_file())
            self.assertEqual(json.loads(outputs["json"].read_text(encoding="utf-8"))["count"], 4)
            self.assertFalse(any(path.name.endswith(".tmp") for path in root.iterdir()))

            with self.assertRaises(convert.BilibiliDanmakuConversionError):
                convert.convert_danmaku_file(source, formats=("srt",))
            self.assertFalse((root / "video.danmaku.srt").exists())

    def test_self_test(self) -> None:
        convert.run_bilibili_danmaku_conversion_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
