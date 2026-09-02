from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from batch_input import (  # noqa: E402
    MAX_BATCH_INPUT_CHARS,
    BatchInputResult,
    parse_batch_input,
    run_batch_input_self_test,
)


class BatchInputTests(unittest.TestCase):
    def test_txt_preserves_duplicates_and_ignores_blank_comments(self):
        result = parse_batch_input(
            "# one per line\n\nhttps://example.com/a\nhttps://example.com/a\nhttps://example.com/b\n",
            format_hint="txt",
        )
        self.assertEqual(result.format, "txt")
        self.assertEqual(
            [item.source_url for item in result.items],
            ["https://example.com/a", "https://example.com/a", "https://example.com/b"],
        )
        self.assertEqual(result.issue_count, 0)

    def test_invalid_rows_do_not_abort_valid_rows_or_leak_tokens(self):
        result = parse_batch_input(
            "https://example.com/good\n"
            "http://127.0.0.1/private?token=secret-token\n"
            "https://user:password@example.com/private\n"
            "not-a-url\n"
            "https://example.com/also-good\n",
            format_hint="txt",
        )
        self.assertEqual(result.accepted_count, 2)
        self.assertEqual([issue.code for issue in result.issues], ["INVALID_URL", "INVALID_URL", "INVALID_URL"])
        self.assertNotIn("secret-token", repr(result.issues))
        self.assertNotIn("password", repr(result.issues))

    def test_auto_detects_csv_and_normalizes_optional_title(self):
        result = parse_batch_input(
            "source_url,display-title\n"
            "https://example.com/one,  First   item  \n"
            "https://example.com/two,Second\n"
        )
        self.assertEqual(result.format, "csv")
        self.assertEqual([item.display_title for item in result.items], ["First item", "Second"])
        self.assertEqual([item.row for item in result.items], [2, 3])

    def test_chinese_csv_headers_are_supported(self):
        result = parse_batch_input(
            "链接,标题\nhttps://example.com/a,任务 A\nhttps://example.com/b,任务 B\n",
            format_hint="csv",
        )
        self.assertEqual(result.accepted_count, 2)
        self.assertEqual(result.items[0].display_title, "任务 A")

    def test_missing_csv_url_column_is_reported_once(self):
        result = parse_batch_input("title,note\nDemo,Missing URL\n", format_hint="csv")
        self.assertEqual(result.items, ())
        self.assertEqual([issue.code for issue in result.issues], ["MISSING_URL_COLUMN"])
        self.assertEqual(result.issues[0].row, 1)

    def test_item_limit_keeps_first_valid_items_in_order(self):
        result = parse_batch_input(
            "https://example.com/1\nhttps://example.com/2\nhttps://example.com/3\n",
            format_hint="txt",
            max_items=2,
        )
        self.assertEqual([item.source_url for item in result.items], ["https://example.com/1", "https://example.com/2"])
        self.assertEqual(result.issues[-1].code, "ITEM_LIMIT")
        self.assertEqual(result.issues[-1].row, 3)

    def test_row_limit_is_bounded_without_dropping_prior_results(self):
        result = parse_batch_input(
            "https://example.com/1\nhttps://example.com/2\nhttps://example.com/3\n",
            format_hint="txt",
            max_rows=2,
        )
        self.assertEqual(result.accepted_count, 2)
        self.assertEqual(result.issues[-1].code, "ROW_LIMIT")

    def test_oversized_input_fails_as_result_not_exception(self):
        result = parse_batch_input("x" * (MAX_BATCH_INPUT_CHARS + 1))
        self.assertIsInstance(result, BatchInputResult)
        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.issues[0].code, "INPUT_TOO_LARGE")

    def test_invalid_parser_options_fail_fast(self):
        with self.assertRaises(ValueError):
            parse_batch_input("https://example.com", format_hint="json")
        with self.assertRaises(ValueError):
            parse_batch_input("https://example.com", max_items=0)
        with self.assertRaises(ValueError):
            parse_batch_input("https://example.com", max_rows=0)

    def test_embedded_self_test(self):
        run_batch_input_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
