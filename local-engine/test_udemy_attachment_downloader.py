from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from course_attachment_files import MAX_ATTACHMENT_FILE_BYTES, attachment_file_record
from course_attachments import replace_course_item_attachments
from course_workspace import add_media_to_course, create_course
from media_library import list_media_items, sync_media_library
from udemy_attachment_downloader import (
    UdemyAttachmentDownloadCancelled,
    UdemyAttachmentDownloadError,
    _select_download_url,
    _udemy_origin,
    download_udemy_attachment,
)


class _FakeResponse:
    def __init__(self, chunks: list[bytes], *, content_length: int = 0) -> None:
        self._chunks = list(chunks)
        self.headers = {"Content-Length": str(content_length)} if content_length else {}
        self.closed = False

    def read(self, _size: int) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def close(self) -> None:
        self.closed = True


class UdemyAttachmentDownloaderTests(unittest.TestCase):
    def _engine_and_attachment(self, root: Path):
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        for target in (downloads, state, data):
            target.mkdir()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def data_dir() -> Path:
                return data

            @staticmethod
            def state_dir() -> Path:
                return state

            @staticmethod
            def default_download_dir() -> Path:
                return downloads

        with patch(
            "course_workspace.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        ):
            course_id = create_course(
                Engine,
                "Python Bootcamp",
                "https://www.udemy.com/course/python-bootcamp/?couponCode=PRIVATE",
                provider="udemy",
            )["id"]
        media = downloads / "lesson.mp4"
        media.write_bytes(b"lesson")
        sync_media_library(
            Engine,
            [{
                "state": "completed",
                "finishedAt": "2026-09-06T00:00:00Z",
                "label": "lesson",
                "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
                "filePath": str(media),
                "fileName": media.name,
                "collectionMode": "course",
            }],
        )
        media_id = next(
            row["id"] for row in list_media_items(Engine, limit=100)
            if row["fileName"] == media.name
        )
        item_id = add_media_to_course(Engine, course_id, media_id)
        attachment = replace_course_item_attachments(
            Engine,
            item_id,
            provider="udemy",
            provider_course_id="udemy:course:456",
            provider_lecture_id="udemy:lecture:1001",
            attachments=[{
                "providerAttachmentId": "udemy:asset:7001",
                "title": "Starter Files",
                "fileName": "../../starter.zip",
                "assetType": "File",
            }],
        )["attachments"][0]
        return Engine, downloads, attachment

    def test_select_download_url_uses_https_download_urls_only(self) -> None:
        metadata = {
            "asset": {
                "external_url": "https://evil.example/?secret=PRIVATE",
                "download_urls": {
                    "File": [
                        {"file": "http://cdn.example/insecure.zip?sig=PRIVATE"},
                        {"file": "https://cdn.example/starter.zip?sig=PRIVATE"},
                    ],
                },
            }
        }
        with patch(
            "udemy_attachment_downloader.validated_public_http_url",
            side_effect=str,
        ):
            selected = _select_download_url(metadata)
        self.assertEqual(selected, "https://cdn.example/starter.zip?sig=PRIVATE")

    def test_udemy_origin_rejects_plain_http_foreign_hosts_and_custom_ports(self) -> None:
        with patch(
            "udemy_attachment_downloader.validated_public_http_url",
            side_effect=str,
        ):
            self.assertEqual(
                _udemy_origin("https://company.udemy.com/course/python/"),
                "https://company.udemy.com",
            )
            for unsafe in (
                "http://www.udemy.com/course/python/",
                "https://example.com/course/python/",
                "https://www.udemy.com:8443/course/python/",
            ):
                with self.subTest(unsafe=unsafe):
                    with self.assertRaises(UdemyAttachmentDownloadError):
                        _udemy_origin(unsafe)

    def test_authorized_download_is_bounded_private_and_server_controlled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads, attachment = self._engine_and_attachment(root)
            captured: dict[str, object] = {}
            response = _FakeResponse([b"abc", b"def"], content_length=6)

            class FakeYDL:
                def __init__(self, options):
                    captured["options"] = dict(options)

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return None

                def urlopen(self, request):
                    captured["downloadUrl"] = str(request.url)
                    return response

            class FakeUdemyIE:
                def __init__(self, _ydl):
                    pass

                def _download_json(self, endpoint, asset_id, _message, query=None):
                    captured["endpoint"] = endpoint
                    captured["assetId"] = asset_id
                    captured["query"] = dict(query or {})
                    return {
                        "asset": {
                            "download_urls": {
                                "File": [
                                    {"file": "https://cdn.example/starter.zip?sig=PRIVATE"}
                                ]
                            },
                            "external_url": "https://evil.example/?token=PRIVATE",
                        }
                    }

            progress: list[tuple[int, int, str]] = []
            with patch("udemy_attachment_downloader.YoutubeDL", FakeYDL), patch(
                "udemy_attachment_downloader.UdemyIE", FakeUdemyIE
            ), patch(
                "udemy_attachment_downloader.validated_public_http_url",
                side_effect=str,
            ):
                result = download_udemy_attachment(
                    engine,
                    attachment["id"],
                    browser="chrome",
                    progress_hook=lambda downloaded, total, name: progress.append(
                        (downloaded, total, name)
                    ),
                )

            self.assertEqual(result["attachmentId"], attachment["id"])
            self.assertTrue(result["downloaded"])
            self.assertEqual(result["sizeBytes"], 6)
            self.assertEqual(result["fileName"], "starter.zip")
            self.assertNotIn("PRIVATE", str(result))
            self.assertNotIn("url", str(result).lower())
            self.assertNotIn(str(downloads), str(result))
            self.assertEqual(captured["options"]["cookiesfrombrowser"], ("chrome", None, None, None))
            endpoint = str(captured["endpoint"])
            self.assertTrue(endpoint.startswith("https://www.udemy.com/"))
            self.assertIn("/subscribed-courses/456/lectures/1001/supplementary-assets/7001/", endpoint)
            self.assertEqual(captured["assetId"], "7001")
            self.assertEqual(captured["query"], {"fields[asset]": "download_urls"})
            self.assertIn("sig=PRIVATE", str(captured["downloadUrl"]))
            self.assertTrue(response.closed)
            self.assertEqual(progress[-1], (6, 6, "starter.zip"))

            files = [path for path in downloads.rglob("*") if path.is_file() and path.name != "lesson.mp4"]
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].name, "starter.zip")
            self.assertEqual(files[0].read_bytes(), b"abcdef")
            self.assertFalse(any(path.name.endswith(".part") for path in downloads.rglob("*")))
            record = attachment_file_record(engine, attachment["id"])
            self.assertIsNotNone(record)
            self.assertNotIn("PRIVATE", str(record))
            self.assertNotIn("https://", str(record))

    def test_oversize_content_length_is_rejected_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads, attachment = self._engine_and_attachment(root)
            response = _FakeResponse([], content_length=MAX_ATTACHMENT_FILE_BYTES + 1)

            class FakeYDL:
                def __init__(self, _options):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return None

                def urlopen(self, _request):
                    return response

            class FakeUdemyIE:
                def __init__(self, _ydl):
                    pass

                def _download_json(self, *_args, **_kwargs):
                    return {"asset": {"download_urls": {"File": [{"file": "https://cdn.example/big.zip"}]}}}

            with patch("udemy_attachment_downloader.YoutubeDL", FakeYDL), patch(
                "udemy_attachment_downloader.UdemyIE", FakeUdemyIE
            ), patch(
                "udemy_attachment_downloader.validated_public_http_url",
                side_effect=str,
            ):
                with self.assertRaisesRegex(UdemyAttachmentDownloadError, "size limit"):
                    download_udemy_attachment(engine, attachment["id"])
            self.assertIsNone(attachment_file_record(engine, attachment["id"]))
            self.assertFalse(any(path.name.endswith(".part") for path in downloads.rglob("*")))

    def test_truncated_content_length_is_rejected_without_partial_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads, attachment = self._engine_and_attachment(root)
            response = _FakeResponse([b"abc"], content_length=10)

            class FakeYDL:
                def __init__(self, _options):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return None

                def urlopen(self, _request):
                    return response

            class FakeUdemyIE:
                def __init__(self, _ydl):
                    pass

                def _download_json(self, *_args, **_kwargs):
                    return {"asset": {"download_urls": {"File": [{"file": "https://cdn.example/truncated.zip?sig=PRIVATE"}]}}}

            with patch("udemy_attachment_downloader.YoutubeDL", FakeYDL), patch(
                "udemy_attachment_downloader.UdemyIE", FakeUdemyIE
            ), patch(
                "udemy_attachment_downloader.validated_public_http_url",
                side_effect=str,
            ):
                with self.assertRaisesRegex(UdemyAttachmentDownloadError, "incomplete") as caught:
                    download_udemy_attachment(engine, attachment["id"])
            self.assertNotIn("PRIVATE", str(caught.exception))
            self.assertTrue(response.closed)
            self.assertIsNone(attachment_file_record(engine, attachment["id"]))
            self.assertFalse(any(path.name.endswith(".part") for path in downloads.rglob("*")))
            saved = [path for path in downloads.rglob("*") if path.is_file() and path.name != "lesson.mp4"]
            self.assertEqual(saved, [])

    def test_precancel_never_resolves_provider_or_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads, attachment = self._engine_and_attachment(root)
            cancelled = threading.Event()
            cancelled.set()

            class NeverYDL:
                def __init__(self, _options):
                    raise AssertionError("provider should not be opened after pre-cancel")

            with patch("udemy_attachment_downloader.YoutubeDL", NeverYDL), patch(
                "udemy_attachment_downloader.validated_public_http_url",
                side_effect=str,
            ):
                with self.assertRaises(UdemyAttachmentDownloadCancelled):
                    download_udemy_attachment(
                        engine,
                        attachment["id"],
                        cancel_event=cancelled,
                    )
            self.assertIsNone(attachment_file_record(engine, attachment["id"]))
            self.assertFalse(any(path.name.endswith(".part") for path in downloads.rglob("*")))


if __name__ == "__main__":
    unittest.main()
