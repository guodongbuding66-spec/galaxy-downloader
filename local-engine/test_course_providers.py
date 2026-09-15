from __future__ import annotations

import unittest
from unittest.mock import patch

from course_providers import (
    CourseProviderError,
    build_course_provider_plan,
    detect_course_provider,
    list_course_providers,
    resolve_course_provider,
)


class CourseProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch(
            "course_providers.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_catalog_exposes_authorized_providers_without_drm_bypass(self) -> None:
        providers = list_course_providers()
        self.assertEqual([provider["id"] for provider in providers], ["udemy", "hotmart"])
        udemy, hotmart = providers
        self.assertTrue(udemy["requiresAuthorizedSession"])
        self.assertTrue(udemy["supportsBrowserCookies"])
        self.assertTrue(udemy["supportsAttachments"])
        self.assertTrue(udemy["downloadAvailable"])
        self.assertFalse(udemy["drmBypassSupported"])

        self.assertEqual(hotmart["status"], "authorized")
        self.assertTrue(hotmart["requiresAuthorizedSession"])
        self.assertTrue(hotmart["supportsBrowserCookies"])
        self.assertFalse(hotmart["supportsSubtitles"])
        self.assertFalse(hotmart["supportsAttachments"])
        self.assertTrue(hotmart["downloadAvailable"])
        self.assertEqual(hotmart["downloadUnavailableReason"], "")
        self.assertFalse(hotmart["drmBypassSupported"])

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

    def test_detects_hotmart_club_member_area(self) -> None:
        self.assertEqual(
            detect_course_provider("https://my-course.club.hotmart.com/lesson/a4Rln5Pa7n/start"),
            "hotmart",
        )
        self.assertEqual(detect_course_provider("https://my-course.club.hotmart.com/"), "hotmart")

    def test_rejects_hotmart_login_host_without_club_subdomain(self) -> None:
        with self.assertRaisesRegex(CourseProviderError, "Hotmart Club"):
            detect_course_provider("https://club.hotmart.com/oauth/login?productId=401198")

    def test_rejects_lookalike_domains(self) -> None:
        with self.assertRaises(CourseProviderError):
            detect_course_provider("https://school.club.hotmart.com.evil.example/lesson/test")
        with self.assertRaises(CourseProviderError):
            detect_course_provider("https://eviludemy.com/course/not-udemy/")

    def test_resolve_hotmart_reports_truthful_authorized_capabilities(self) -> None:
        resolution = resolve_course_provider("https://my-course.club.hotmart.com/lesson/abc/start")
        self.assertEqual(resolution["provider"], "hotmart")
        self.assertEqual(resolution["providerName"], "Hotmart")
        self.assertEqual(resolution["status"], "authorized")
        self.assertTrue(resolution["downloadAvailable"])
        self.assertTrue(resolution["supportsBrowserCookies"])
        self.assertFalse(resolution["supportsSubtitles"])
        self.assertFalse(resolution["supportsAttachments"])
        self.assertFalse(resolution["drmBypassSupported"])
        self.assertNotIn("enginePayload", resolution)
        self.assertNotIn("browser", resolution)

    def test_builds_udemy_engine_payload_with_browser_cookie_source(self) -> None:
        plan = build_course_provider_plan(
            "https://www.udemy.com/course/python-bootcamp/",
            browser="chrome",
        )
        self.assertEqual(plan["provider"], "udemy")
        self.assertEqual(plan["enginePayload"]["browser"], "chrome")
        self.assertTrue(plan["enginePayload"]["includeSubtitle"])
        self.assertTrue(plan["enginePayload"]["includeCourseAttachments"])
        self.assertEqual(plan["enginePayload"]["collectionMode"], "all")

    def test_builds_hotmart_authorized_resolution_plan_without_raw_auth_material(self) -> None:
        source = "https://my-course.club.hotmart.com/lesson/abc/start?lesson=1"
        plan = build_course_provider_plan(source, provider="hotmart", browser="chrome")
        self.assertEqual(plan["provider"], "hotmart")
        self.assertEqual(plan["sourceUrl"], source)
        payload = plan["enginePayload"]
        self.assertEqual(payload["sourceUrl"], source)
        self.assertEqual(payload["browser"], "chrome")
        self.assertEqual(payload["collectionMode"], "single")
        self.assertTrue(payload["_hotmartResolveAuthorizedMedia"])
        self.assertFalse(payload["includeSubtitle"])
        self.assertFalse(payload["includeCourseAttachments"])
        self.assertNotIn("cookie", payload)
        self.assertNotIn("cookieFile", payload)
        self.assertNotIn("httpHeaders", payload)
        self.assertTrue(any("DRM" in warning for warning in plan["warnings"]))

    def test_hotmart_requires_explicit_logged_in_browser(self) -> None:
        with self.assertRaisesRegex(CourseProviderError, "Hotmart.*浏览器"):
            build_course_provider_plan("https://my-course.club.hotmart.com/lesson/abc/start")

    def test_udemy_none_browser_keeps_warning(self) -> None:
        plan = build_course_provider_plan("https://www.udemy.com/course/python-bootcamp/")
        self.assertEqual(plan["enginePayload"]["browser"], "none")
        self.assertTrue(any("Cookie" in warning for warning in plan["warnings"]))

    def test_hotmart_ignores_unsupported_subtitle_and_attachment_requests_truthfully(self) -> None:
        plan = build_course_provider_plan(
            "https://my-course.club.hotmart.com/lesson/abc/start",
            browser="edge",
            include_subtitles=True,
            include_attachments=True,
        )
        self.assertFalse(plan["enginePayload"]["includeSubtitle"])
        self.assertFalse(plan["enginePayload"]["includeCourseAttachments"])
        self.assertFalse(plan["supportsSubtitles"])
        self.assertFalse(plan["supportsAttachments"])

    def test_rejects_invalid_browser_and_provider_mismatch(self) -> None:
        with self.assertRaises(CourseProviderError):
            build_course_provider_plan(
                "https://www.udemy.com/course/python-bootcamp/",
                browser="safari",
            )
        with self.assertRaises(CourseProviderError):
            build_course_provider_plan(
                "https://www.udemy.com/course/python-bootcamp/",
                provider="hotmart",
            )

    def test_include_flags_must_be_boolean(self) -> None:
        with self.assertRaises(CourseProviderError):
            build_course_provider_plan(
                "https://www.udemy.com/course/python-bootcamp/",
                include_subtitles="yes",
            )
        with self.assertRaises(CourseProviderError):
            build_course_provider_plan(
                "https://www.udemy.com/course/python-bootcamp/",
                include_attachments="yes",
            )


if __name__ == "__main__":
    unittest.main()
