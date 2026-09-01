from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import entrypoint  # noqa: E402
import external_ytdlp  # noqa: E402


class LocalDownloadArchivePolicyTests(unittest.TestCase):
    def test_archive_is_off_by_default(self):
        job = entrypoint.engine.job_from_payload({"sourceUrl": "https://example.com/video"})
        self.assertFalse(job.skip_previously_downloaded)
        payload = entrypoint.engine.job_to_payload(job)
        self.assertFalse(payload["skipPreviouslyDownloaded"])

        command = external_ytdlp.build_external_command(
            Path("yt-dlp.exe"),
            job.source_url,
            format_selector="bv+ba/b",
            output_template="downloads/%(title)s.%(ext)s",
            ffmpeg_location=None,
            browser="none",
            playlist=False,
            include_subtitle=False,
            subtitle_language=None,
            include_cover=False,
        )
        self.assertNotIn("--download-archive", command)

    def test_bridge_payload_and_protocol_can_opt_in(self):
        payload_job = entrypoint.engine.job_from_payload(
            {
                "sourceUrl": "https://example.com/video",
                "skipPreviouslyDownloaded": True,
            }
        )
        self.assertTrue(payload_job.skip_previously_downloaded)
        self.assertTrue(entrypoint.engine.job_to_payload(payload_job)["skipPreviouslyDownloaded"])

        source = quote("https://example.com/video", safe="")
        protocol_job = entrypoint.engine.parse_job(
            f"galaxy-downloader://download?url={source}&archive=1"
        )
        self.assertTrue(protocol_job.skip_previously_downloaded)

    def test_archive_path_stays_in_engine_state_directory(self):
        job = entrypoint.engine.job_from_payload(
            {
                "sourceUrl": "https://example.com/video",
                "skipPreviouslyDownloaded": True,
            }
        )
        default_job = entrypoint.engine.job_from_payload(
            {"sourceUrl": "https://example.com/another"}
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            with mock.patch.object(entrypoint.engine, "app_dir", return_value=app_dir):
                window = entrypoint.engine.EngineWindow.__new__(entrypoint.engine.EngineWindow)
                window.job = job
                options = window.build_options()
                expected = app_dir / "state" / "download-archive.txt"
                self.assertEqual(Path(options["download_archive"]), expected)
                self.assertTrue(expected.parent.is_dir())
                self.assertNotEqual(expected.parent, app_dir / "downloads")

                default_window = entrypoint.engine.EngineWindow.__new__(entrypoint.engine.EngineWindow)
                default_window.job = default_job
                default_options = default_window.build_options()
                self.assertNotIn("download_archive", default_options)

    def test_external_ytdlp_receives_exact_archive_path_only_when_enabled(self):
        archive = Path("state") / "download-archive.txt"
        command = external_ytdlp.build_external_command(
            Path("yt-dlp.exe"),
            "https://example.com/video",
            format_selector="bv+ba/b",
            output_template="downloads/%(title)s.%(ext)s",
            ffmpeg_location=None,
            browser="none",
            playlist=False,
            include_subtitle=False,
            subtitle_language=None,
            include_cover=False,
            download_archive=archive,
        )
        index = command.index("--download-archive")
        self.assertEqual(command[index + 1], str(archive))


if __name__ == "__main__":
    unittest.main(verbosity=2)
