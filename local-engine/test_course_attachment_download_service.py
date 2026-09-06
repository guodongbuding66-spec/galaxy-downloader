from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from course_attachment_download_service import (
    CourseAttachmentDownloadService,
    CourseAttachmentDownloadServiceError,
)
from udemy_attachment_downloader import UdemyAttachmentDownloadCancelled


class CourseAttachmentDownloadServiceTests(unittest.TestCase):
    def _wait_for(self, service, job_id: str, states: set[str], timeout: float = 2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = service.status(job_id)
            if status["state"] in states:
                return status
            time.sleep(0.01)
        raise AssertionError(f"job did not reach {states}: {service.status(job_id)}")

    def test_submit_progress_completion_and_public_payload_are_safe(self) -> None:
        attachment_id = "a" * 32

        def fake_download(_context, requested, *, browser, cancel_event, progress_hook):
            self.assertEqual(requested, attachment_id)
            self.assertEqual(browser, "chrome")
            self.assertFalse(cancel_event.is_set())
            progress_hook(5, 10, "starter.zip")
            progress_hook(10, 10, "starter.zip")
            return {
                "attachmentId": attachment_id,
                "downloaded": True,
                "sizeBytes": 10,
                "fileName": "starter.zip",
            }

        with patch(
            "course_attachment_download_service.attachment_download_context",
            return_value={"id": attachment_id},
        ), patch(
            "course_attachment_download_service.download_udemy_attachment",
            side_effect=fake_download,
        ):
            service = CourseAttachmentDownloadService(object())
            self.addCleanup(service.close)
            submitted = service.submit(attachment_id, browser="chrome")
            self.assertEqual(submitted["attachmentId"], attachment_id)
            self.assertEqual(submitted["state"], "queued")
            self.assertNotIn("browser", submitted)
            self.assertNotIn("url", str(submitted).lower())
            self.assertNotIn("path", str(submitted).lower())

            completed = self._wait_for(service, submitted["id"], {"completed"})
            self.assertEqual(completed["progress"], 100.0)
            self.assertEqual(completed["downloadedBytes"], 10)
            self.assertEqual(completed["sizeBytes"], 10)
            self.assertEqual(completed["fileName"], "starter.zip")
            self.assertEqual(completed["error"], "")
            self.assertNotIn("browser", completed)

    def test_running_job_can_be_cancelled_without_error_leak(self) -> None:
        attachment_id = "b" * 32
        started = threading.Event()

        def fake_download(_context, _requested, *, browser, cancel_event, progress_hook):
            self.assertEqual(browser, "firefox")
            progress_hook(1, 100, "notes.pdf")
            started.set()
            while not cancel_event.wait(0.01):
                pass
            raise UdemyAttachmentDownloadCancelled("attachment download cancelled")

        with patch(
            "course_attachment_download_service.attachment_download_context",
            return_value={"id": attachment_id},
        ), patch(
            "course_attachment_download_service.download_udemy_attachment",
            side_effect=fake_download,
        ):
            service = CourseAttachmentDownloadService(object())
            self.addCleanup(service.close)
            submitted = service.submit(attachment_id, browser="firefox")
            self.assertTrue(started.wait(1.0))
            cancelling = service.cancel(submitted["id"])
            self.assertIn(cancelling["state"], {"cancelling", "cancelled"})
            cancelled = self._wait_for(service, submitted["id"], {"cancelled"})
            self.assertEqual(cancelled["error"], "")
            self.assertNotIn("firefox", str(cancelled))

    def test_duplicate_inflight_submit_reuses_job_before_capacity_rejection(self) -> None:
        attachment_id = "c" * 32
        release = threading.Event()

        def fake_download(_context, _requested, *, browser, cancel_event, progress_hook):
            while not release.wait(0.01):
                if cancel_event.is_set():
                    raise UdemyAttachmentDownloadCancelled("attachment download cancelled")
            return {
                "attachmentId": attachment_id,
                "downloaded": True,
                "sizeBytes": 1,
                "fileName": "x.bin",
            }

        with patch(
            "course_attachment_download_service.attachment_download_context",
            return_value={"id": attachment_id},
        ), patch(
            "course_attachment_download_service.download_udemy_attachment",
            side_effect=fake_download,
        ):
            service = CourseAttachmentDownloadService(object())
            self.addCleanup(service.close)
            first = service.submit(attachment_id, browser="edge")
            with patch.object(service._queue, "full", return_value=True):
                second = service.submit(attachment_id, browser="edge")
            self.assertEqual(first["id"], second["id"])
            with self.assertRaises(Exception):
                service.submit(attachment_id, browser="../../cookies.txt")
            release.set()
            self._wait_for(service, first["id"], {"completed"})

    def test_unknown_job_is_not_found(self) -> None:
        service = CourseAttachmentDownloadService(object())
        self.addCleanup(service.close)
        with self.assertRaises(CourseAttachmentDownloadServiceError):
            service.status("d" * 32)
        with self.assertRaises(CourseAttachmentDownloadServiceError):
            service.cancel("d" * 32)


if __name__ == "__main__":
    unittest.main()
