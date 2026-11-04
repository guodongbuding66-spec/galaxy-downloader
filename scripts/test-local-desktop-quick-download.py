from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_hooks import registered_after_build_ui_hooks  # noqa: E402
from desktop_quick_download import (  # noqa: E402
    QuickPreview,
    _human_duration,
    _invalidate_quick_preview,
    _option_label,
    _parse_quick_url,
    _submission_result,
    build_quick_download_payload,
    install_desktop_quick_download,
    preview_from_parse_result,
    run_desktop_quick_download_self_test,
)


def parse_result(*, muxed: bool = False):
    video = {
        "id": "video:22" if muxed else "video:137",
        "formatId": "22" if muxed else "137",
        "label": "720p · AVC · MP4 · 含音频" if muxed else "1080p · AVC · MP4",
        "streamType": "muxed" if muxed else "video-only",
        "height": 720 if muxed else 1080,
        "filesizeApprox": 25 * 1024 * 1024,
    }
    return {
        "success": True,
        "data": {
            "title": "  Demo   video  ",
            "platform": "youtube",
            "duration": 125,
            "collectionCount": 1,
            "downloadVideoUrl": "https://signed.example/video?token=secret",
            "formatCatalog": {
                "videoOptions": [video],
                "audioOptions": [
                    {
                        "id": "audio:251",
                        "formatId": "251",
                        "label": "160 kbps · OPUS · WEBM",
                        "streamType": "audio-only",
                        "audioBitrate": 160,
                    }
                ],
                "defaultVideoId": video["id"],
                "defaultAudioId": "audio:251",
            },
        },
    }


class QuickPreviewCoreTests(unittest.TestCase):
    def test_self_test(self):
        run_desktop_quick_download_self_test()

    def test_preview_uses_catalog_not_legacy_signed_url(self):
        preview = preview_from_parse_result("https://example.test/watch", parse_result())
        self.assertEqual(preview.title, "Demo video")
        self.assertEqual(preview.default_video_id, "video:137")
        self.assertEqual(preview.default_audio_id, "audio:251")
        self.assertNotIn("signed.example", str(preview))
        self.assertNotIn("downloadUrl", str(preview))

    def test_separate_stream_payload_uses_real_format_ids(self):
        preview = preview_from_parse_result("https://example.test/watch", parse_result())
        payload = build_quick_download_payload(
            preview,
            selected_video_id="video:137",
            selected_audio_id="audio:251",
            browser="edge",
        )
        self.assertEqual(payload["videoFormatId"], "137")
        self.assertEqual(payload["audioFormatId"], "251")
        self.assertFalse(payload["selectedVideoHasAudio"])
        self.assertTrue(payload["includeAudio"])
        self.assertEqual(payload["videoQuality"], "1080p")
        self.assertEqual(payload["browser"], "edge")

    def test_muxed_payload_ignores_separate_audio_selection(self):
        preview = preview_from_parse_result("https://example.test/watch", parse_result(muxed=True))
        payload = build_quick_download_payload(
            preview,
            selected_video_id="video:22",
            selected_audio_id="audio:251",
        )
        self.assertEqual(payload["videoFormatId"], "22")
        self.assertIsNone(payload["audioFormatId"])
        self.assertTrue(payload["selectedVideoHasAudio"])
        self.assertTrue(payload["includeAudio"])

    def test_audio_only_payload_is_supported(self):
        preview = QuickPreview(
            source_url="https://example.test/audio",
            title="Audio",
            platform="soundcloud",
            duration_seconds=30,
            video_options=(),
            audio_options=(
                {
                    "id": "audio:251",
                    "formatId": "251",
                    "label": "160 kbps · OPUS",
                    "streamType": "audio-only",
                    "audioBitrate": 160,
                },
            ),
            default_video_id=None,
            default_audio_id="audio:251",
            collection_count=1,
        )
        payload = build_quick_download_payload(
            preview,
            selected_video_id=None,
            selected_audio_id="audio:251",
        )
        self.assertIsNone(payload["videoFormatId"])
        self.assertEqual(payload["audioFormatId"], "251")
        self.assertEqual(payload["videoQuality"], "audio-only")

    def test_parse_errors_are_stable(self):
        with self.assertRaisesRegex(ValueError, "AUTH_REQUIRED"):
            preview_from_parse_result(
                "https://example.test/private",
                {"success": False, "code": "AUTH_REQUIRED", "error": "请登录"},
            )

    def test_no_formats_fail_closed_at_download(self):
        preview = preview_from_parse_result(
            "https://example.test/article",
            {"success": True, "data": {"title": "Article", "formatCatalog": {}}},
        )
        self.assertFalse(preview.has_exact_formats)
        with self.assertRaisesRegex(ValueError, "没有可用于本机下载"):
            build_quick_download_payload(preview, selected_video_id=None, selected_audio_id=None)

    def test_unknown_default_ids_are_not_trusted(self):
        result = parse_result()
        result["data"]["formatCatalog"]["defaultVideoId"] = "video:does-not-exist"
        preview = preview_from_parse_result("https://example.test/watch", result)
        self.assertEqual(preview.default_video_id, "video:137")

    def test_format_label_adds_size_without_exposing_url(self):
        label = _option_label(
            {
                "formatId": "137",
                "label": "1080p · AVC",
                "filesize": 5 * 1024 * 1024,
                "downloadUrl": "https://should-not-appear.example/secret",
            }
        )
        self.assertIn("5.0 MB", label)
        self.assertNotIn("http", label)

    def test_duration_formatting(self):
        self.assertEqual(_human_duration(125), "2:05")
        self.assertEqual(_human_duration(3661), "1:01:01")

    def test_changed_source_invalidates_preview_and_pending_parse(self):
        state = SimpleNamespace(value="")
        download = SimpleNamespace(calls=[])
        parse = SimpleNamespace(calls=[])
        panel = SimpleNamespace(hidden=False)
        window = SimpleNamespace(
            _quick_parse_generation=7,
            _quick_preview=object(),
            _quick_video_display={"1080p": "137"},
            _quick_audio_display={"Opus": "251"},
            _quick_url_var=SimpleNamespace(get=lambda: "https://example.test/new"),
            _quick_state_var=SimpleNamespace(set=lambda value: setattr(state, "value", value)),
            _quick_download_button=SimpleNamespace(state=download.calls.append),
            _quick_parse_button=SimpleNamespace(state=parse.calls.append),
            _quick_preview_panel=SimpleNamespace(pack_forget=lambda: setattr(panel, "hidden", True)),
        )
        _invalidate_quick_preview(window)
        self.assertEqual(window._quick_parse_generation, 8)
        self.assertIsNone(window._quick_preview)
        self.assertEqual(window._quick_video_display, {})
        self.assertEqual(window._quick_audio_display, {})
        self.assertEqual(download.calls, [["disabled"]])
        self.assertEqual(parse.calls, [["!disabled"]])
        self.assertTrue(panel.hidden)
        self.assertIn("重新解析", state.value)
        window._quick_url_var = SimpleNamespace(get=lambda: "")
        _invalidate_quick_preview(window)
        self.assertEqual(window._quick_parse_generation, 9)
        self.assertIn("粘贴", state.value)

    def test_parse_completion_cannot_restore_an_edited_source(self):
        callbacks = []
        window = SimpleNamespace(
            _quick_url_var=SimpleNamespace(get=lambda: "https://example.test/first"),
            _quick_browser_var=SimpleNamespace(get=lambda: "不使用浏览器登录"),
            _quick_parse_generation=0,
            _quick_preview=None,
            _quick_parse_button=SimpleNamespace(state=lambda _value: None),
            _quick_download_button=SimpleNamespace(state=lambda _value: None),
            _quick_preview_panel=SimpleNamespace(pack_forget=lambda: None),
            _quick_state_var=SimpleNamespace(set=lambda _value: None),
            after=lambda _delay, callback: callbacks.append(callback),
            winfo_exists=lambda: True,
        )
        engine = SimpleNamespace(_validated_source_url=lambda url: url)
        with patch("desktop_quick_download.bridge.parse_with_bundled_ytdlp", return_value=parse_result()), patch(
            "desktop_quick_download.threading.Thread"
        ) as thread:
            thread.return_value.start.side_effect = lambda: thread.call_args.kwargs["target"]()
            _parse_quick_url(window, engine)
        self.assertEqual(len(callbacks), 1)
        _invalidate_quick_preview(window)
        callbacks[0]()
        self.assertIsNone(window._quick_preview)
        self.assertEqual(window._quick_parse_generation, 2)

    def test_submission_normalizes_queue_contract(self):
        result = SimpleNamespace(accepted=True, message="queued", code="QUEUED")
        self.assertEqual(_submission_result(result), (True, "queued", "QUEUED"))
        self.assertEqual(_submission_result((True, "accepted")), (True, "accepted", ""))


class QuickPreviewArchitectureTests(unittest.TestCase):
    def test_desktop_hook_is_registered_without_wrapping_build_ui(self):
        class Window:
            pass

        engine = SimpleNamespace(EngineWindow=Window)
        install_desktop_quick_download(engine)
        self.assertIn("desktop-quick-download", registered_after_build_ui_hooks(Window))
        self.assertFalse(hasattr(Window, "_build_ui"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
