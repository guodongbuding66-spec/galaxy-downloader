from __future__ import annotations

import unittest
from unittest.mock import patch

from course_providers import (
    CourseProviderError,
    build_course_provider_plan,
    detect_course_provider,
    list_course_providers,
)


class CourseProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch(
            "course_providers.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_catalog_exposes_udemy_without_drm_bypass(self) -> None:
        providers = list_course_providers()
        self.assertEqual([provider["id"] for provider in providers], ["udemy"])
        self.assertTrue(providers[0]["requiresAuthorizedSession"])
        self.assertFalse(providers[0]["drmBypassSupported"])

    def test_detects_standard_udemy_course_url(self) -> None:
        self.assertEqual(
            detect_course_provider("https://www.udemy.com/course/python-bootcamp/learn/lecture/123"),
            "udemy",
        )

    def test_detects_udemy_business_subdomain(self) -> None:
        self.assertEqual(
            detect_course_provider("https://example.udemy.com/course/internal-training/"),
            "udemy",
        )

    def test_rejects_lookalike_udemy_domain(self) -> None:
        with self.assertRaises(CourseProviderError):
            detect_course_provider("https://eviludemy.com/course/not-udemy/")

    def test_requires_course_path(self) -> None:
        with self.assertRaisesRegex(CourseProviderError, "course"):
            detect_course_provider("https://www.udemy.com/home/my-courses/learning/")

    def test_builds_engine_payload_with_browser_cookie_source(self) -> None:
        plan = build_course_provider_plan(
            "https://www.udemy.com/course/python-bootcamp/",
            browser="chrome",
        )
        self.assertEqual(plan["provider"], "udemy")
        self.assertFalse(plan["drmBypassSupported"])
        self.assertEqual(plan["enginePayload"]["browser"], "chrome")
        self.assertTrue(plan["enginePayload"]["includeSubtitle"])
        self.assertEqual(plan["enginePayload"]["subtitleMode"], "both")
        self.assertEqual(plan["enginePayload"]["collectionMode"], "all")

    def test_no_browser_returns_authorization_warning(self) -> None:
        plan = build_course_provider_plan("https://www.udemy.com/course/python-bootcamp/")
        self.assertEqual(plan["enginePayload"]["browser"], "none")
        self.assertTrue(any("Cookie" in warning for warning in plan["warnings"]))

    def test_subtitles_can_be_disabled(self) -> None:
        plan = build_course_provider_plan(
            "https://www.udemy.com/course/python-bootcamp/",
            include_subtitles=False,
        )
        self.assertFalse(plan["enginePayload"]["includeSubtitle"])
        self.assertEqual(plan["enginePayload"]["subtitleMode"], "none")

    def test_rejects_invalid_browser(self) -> None:
        with self.assertRaises(CourseProviderError):
            build_course_provider_plan(
                "https://www.udemy.com/course/python-bootcamp/",
                browser="safari",
            )

    def test_rejects_provider_mismatch(self) -> None:
        with self.assertRaises(CourseProviderError):
            build_course_provider_plan(
                "https://www.udemy.com/course/python-bootcamp/",
                provider="hotmart",
            )

    def test_include_subtitles_must_be_boolean(self) -> None:
        with self.assertRaises(CourseProviderError):
            build_course_provider_plan(
                "https://www.udemy.com/course/python-bootcamp/",
                include_subtitles="yes",
            )


if __name__ == "__main__":
    unittest.main()
