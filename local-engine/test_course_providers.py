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

    def test_catalog_exposes_download_capability_without_drm_bypass(self) -> None:
        providers = list_course_providers()
        self.assertEqual([provider["id"] for provider in providers], ["udemy", "hotmart"])
        udemy, hotmart = providers
        self.assertTrue(udemy["requiresAuthorizedSession"])
        self.assertTrue(udemy["supportsBrowserCookies"])
        self.assertTrue(udemy["supportsAttachments"])
        self.assertTrue(udemy["downloadAvailable"])
        self.assertEqual(udemy["downloadUnavailableReason"], "")
        self.assertFalse(udemy["drmBypassSupported"])
        self.assertEqual(hotmart["status"], "discovery")
        self.assertTrue(hotmart["requiresAuthorizedSession"])
        self.assertFalse(hotmart["supportsBrowserCookies"])
        self.assertFalse(hotmart["supportsSubtitles"])
        self.assertFalse(hotmart["supportsAttachments"])
        self.assertFalse(hotmart["downloadAvailable"])
        self.assertIn("授权下载适配器尚未实现", hotmart["downloadUnavailableReason"])
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
            detect_course_provider(
                "https://sosmaesexaustas20.club.hotmart.com/lesson/a4Rln5Pa7n/importante-nao-pule-essa-aula-ok"
            ),
            "hotmart",
        )
        self.assertEqual(
            detect_course_provider("https://my-course.club.hotmart.com/"),
            "hotmart",
        )

    def test_rejects_hotmart_login_host_without_club_subdomain(self) -> None:
        with self.assertRaisesRegex(CourseProviderError, "Hotmart Club"):
            detect_course_provider("https://club.hotmart.com/oauth/login?productId=401198")

    def test_rejects_lookalike_hotmart_club_domain(self) -> None:
        with self.assertRaises(CourseProviderError):
            detect_course_provider("https://school.club.hotmart.com.evil.example/lesson/test")

    def test_rejects_lookalike_udemy_domain(self) -> None:
        with self.assertRaises(CourseProviderError):
            detect_course_provider("https://eviludemy.com/course/not-udemy/")

    def test_requires_course_path(self) -> None:
        with self.assertRaisesRegex(CourseProviderError, "course"):
            detect_course_provider("https://www.udemy.com/home/my-courses/learning/")

    def test_resolve_udemy_returns_safe_capabilities_without_engine_payload(self) -> None:
        resolution = resolve_course_provider(
            "https://www.udemy.com/course/python-bootcamp/",
            provider="auto",
        )
        self.assertEqual(resolution["provider"], "udemy")
        self.assertEqual(resolution["providerName"], "Udemy")
        self.assertTrue(resolution["downloadAvailable"])
        self.assertTrue(resolution["supportsBrowserCookies"])
        self.assertTrue(resolution["supportsSubtitles"])
        self.assertTrue(resolution["supportsAttachments"])
        self.assertEqual(resolution["downloadUnavailableReason"], "")
        self.assertFalse(resolution["drmBypassSupported"])
        self.assertNotIn("enginePayload", resolution)
        self.assertNotIn("browser", resolution)

    def test_resolve_hotmart_returns_discovery_capabilities_without_download_plan(self) -> None:
        resolution = resolve_course_provider(
            "https://my-course.club.hotmart.com/lesson/abc/start",
        )
        self.assertEqual(resolution["provider"], "hotmart")
        self.assertEqual(resolution["providerName"], "Hotmart")
        self.assertEqual(resolution["status"], "discovery")
        self.assertFalse(resolution["downloadAvailable"])
        self.assertFalse(resolution["supportsBrowserCookies"])
        self.assertFalse(resolution["supportsSubtitles"])
        self.assertFalse(resolution["supportsAttachments"])
        self.assertIn("授权下载适配器尚未实现", resolution["downloadUnavailableReason"])
        self.assertFalse(resolution["drmBypassSupported"])
        self.assertNotIn("enginePayload", resolution)
        self.assertNotIn("browser", resolution)

    def test_resolve_rejects_explicit_provider_mismatch(self) -> None:
        with self.assertRaises(CourseProviderError):
            resolve_course_provider(
                "https://www.udemy.com/course/python-bootcamp/",
                provider="hotmart",
            )

    def test_builds_engine_payload_with_browser_cookie_source(self) -> None:
        plan = build_course_provider_plan(
            "https://www.udemy.com/course/python-bootcamp/",
            browser="chrome",
        )
        self.assertEqual(plan["provider"], "udemy")
        self.assertTrue(plan["downloadAvailable"])
        self.assertFalse(plan["drmBypassSupported"])
        self.assertEqual(plan["enginePayload"]["browser"], "chrome")
        self.assertTrue(plan["enginePayload"]["includeSubtitle"])
        self.assertTrue(plan["enginePayload"]["includeCourseAttachments"])
        self.assertEqual(plan["enginePayload"]["subtitleMode"], "both")
        self.assertEqual(plan["enginePayload"]["collectionMode"], "all")

    def test_no_browser_returns_authorization_warning(self) -> None:
        plan = build_course_provider_plan("https://www.udemy.com/course/python-bootcamp/")
        self.assertEqual(plan["enginePayload"]["browser"], "none")
        self.assertTrue(any("Cookie" in warning for warning in plan["warnings"]))

    def test_subtitles_and_attachment_inventory_can_be_disabled(self) -> None:
        plan = build_course_provider_plan(
            "https://www.udemy.com/course/python-bootcamp/",
            include_subtitles=False,
            include_attachments=False,
        )
        self.assertFalse(plan["enginePayload"]["includeSubtitle"])
        self.assertFalse(plan["enginePayload"]["includeCourseAttachments"])
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

    def test_hotmart_auto_plan_is_discovery_only(self) -> None:
        with self.assertRaisesRegex(CourseProviderError, "Hotmart.*授权下载适配器尚未实现"):
            build_course_provider_plan(
                "https://my-course.club.hotmart.com/lesson/abc/start",
                browser="chrome",
            )

    def test_hotmart_explicit_plan_cannot_fall_through_to_generic_downloader(self) -> None:
        with self.assertRaisesRegex(CourseProviderError, "Hotmart.*授权下载适配器尚未实现"):
            build_course_provider_plan(
                "https://my-course.club.hotmart.com/",
                provider="hotmart",
                browser="safari",
                include_subtitles=False,
                include_attachments=False,
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
