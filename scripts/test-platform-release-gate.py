from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from platform_release_gate import (  # noqa: E402
    CRITICAL_PLATFORMS,
    EXPECTED_PLATFORM_COUNT,
    evaluate_report,
    expected_platforms,
)


def passing_row(platform: str) -> dict[str, object]:
    return {
        "platform": platform,
        "status": "PASS",
        "fixture_url": f"https://fixtures.example/{platform}",
        "parse": {"ok": True, "status": 200, "kind": "json"},
        "video": {"ok": True, "status": 206, "kind": "media"},
        "audio": None,
        "cover": None,
        "subtitle": None,
    }


class PlatformReleaseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.platforms = expected_platforms()
        self.assertEqual(len(self.platforms), EXPECTED_PLATFORM_COUNT)
        self.assertTrue(CRITICAL_PLATFORMS.issubset(self.platforms))

    def report(self) -> dict[str, object]:
        return {"results": [passing_row(platform) for platform in self.platforms]}

    def test_all_33_pass(self) -> None:
        self.assertEqual(evaluate_report(self.report(), self.platforms), [])

    def test_partial_skip_and_fail_are_blocking(self) -> None:
        for status in ("PARTIAL", "SKIP", "FAIL"):
            payload = self.report()
            payload["results"][0]["status"] = status  # type: ignore[index]
            problems = evaluate_report(payload, self.platforms)
            self.assertTrue(any(status in problem for problem in problems))

    def test_missing_duplicate_and_extra_rows_are_blocking(self) -> None:
        payload = self.report()
        rows = payload["results"]  # type: ignore[assignment]
        rows.pop()  # type: ignore[union-attr]
        rows.append(dict(rows[0]))  # type: ignore[index,union-attr]
        rows.append(passing_row("unexpected"))  # type: ignore[union-attr]
        problems = evaluate_report(payload, self.platforms)
        self.assertTrue(any("duplicate" in problem for problem in problems))
        self.assertTrue(any("missing" in problem for problem in problems))
        self.assertTrue(any("unexpected" in problem for problem in problems))

    def test_pass_without_live_fixture_or_resource_probe_is_blocking(self) -> None:
        payload = self.report()
        row = payload["results"][0]  # type: ignore[index]
        row["fixture_url"] = "fixture-id-only"  # type: ignore[index]
        row["video"] = None  # type: ignore[index]
        problems = evaluate_report(payload, self.platforms)
        self.assertTrue(any("live HTTP(S) fixture" in problem for problem in problems))
        self.assertTrue(any("real resource probe" in problem for problem in problems))

    def test_vimeo_and_dailymotion_are_explicit_critical_gates(self) -> None:
        for critical in CRITICAL_PLATFORMS:
            payload = self.report()
            for row in payload["results"]:  # type: ignore[union-attr]
                if row["platform"] == critical:
                    row["status"] = "FAIL"
            problems = evaluate_report(payload, self.platforms)
            self.assertTrue(any(f"critical platform did not pass: {critical}" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main(verbosity=2)
