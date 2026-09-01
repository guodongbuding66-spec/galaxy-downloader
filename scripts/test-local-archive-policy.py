from __future__ import annotations

import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import archive_policy  # noqa: E402
import external_ytdlp  # noqa: E402


def make_fake_engine(app_directory: Path):
    @dataclass(frozen=True)
    class BaseJob:
        source_url: str

    engine = types.SimpleNamespace()
    engine.Job = BaseJob

    # Real engine.py resolves the module-level Job symbol at call time. The
    # archive policy intentionally replaces that symbol with an extended
    # dataclass, so this fake must do the same rather than closing over BaseJob.
    def parse_job(raw: str):
        query = parse_qs(urlparse(raw).query)
        return engine.Job(query.get("url", [""])[0])

    def job_from_payload(payload):
        return engine.Job(str(payload.get("sourceUrl") or ""))

    def job_to_payload(job):
        return {"sourceUrl": job.source_url}

    def bool_value(value, default=False):
        if value is None:
            return default
        return str(value).lower() in {"1", "true", "yes", "on"}

    class FakeWindow:
        def __init__(self, job):
            self.job = job

        def build_options(self):
            return {"format": "best"}

        def _run_external_job(self, executable):
            return engine.download_with_external_ytdlp(
                executable,
                self.job.source_url,
                marker="fake",
            )

    def fake_external_download(*_args, **kwargs):
        return kwargs.get("download_archive")

    engine.EngineWindow = FakeWindow
    engine.parse_job = parse_job
    engine.job_from_payload = job_from_payload
    engine.job_to_payload = job_to_payload
    engine._bool = bool_value
    engine.app_dir = lambda: app_directory
    engine.download_with_external_ytdlp = fake_external_download
    return engine


class LocalDownloadArchivePolicyTests(unittest.TestCase):
    def test_archive_is_off_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = make_fake_engine(Path(temp_dir))
            archive_policy.install_archive_policy(engine)
            job = engine.job_from_payload({"sourceUrl": "https://example.com/video"})
            self.assertFalse(job.skip_previously_downloaded)
            payload = engine.job_to_payload(job)
            self.assertFalse(payload["skipPreviouslyDownloaded"])

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
        )
        self.assertNotIn("--download-archive", command)

    def test_bridge_payload_and_protocol_can_opt_in(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = make_fake_engine(Path(temp_dir))
            archive_policy.install_archive_policy(engine)

            payload_job = engine.job_from_payload(
                {
                    "sourceUrl": "https://example.com/video",
                    "skipPreviouslyDownloaded": True,
                }
            )
            self.assertTrue(payload_job.skip_previously_downloaded)
            self.assertTrue(engine.job_to_payload(payload_job)["skipPreviouslyDownloaded"])

            source = quote("https://example.com/video", safe="")
            protocol_job = engine.parse_job(
                f"galaxy-downloader://download?url={source}&archive=1"
            )
            self.assertEqual(protocol_job.source_url, "https://example.com/video")
            self.assertTrue(protocol_job.skip_previously_downloaded)

    def test_archive_path_stays_in_engine_state_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            engine = make_fake_engine(app_dir)
            archive_policy.install_archive_policy(engine)
            job = engine.job_from_payload(
                {
                    "sourceUrl": "https://example.com/video",
                    "skipPreviouslyDownloaded": True,
                }
            )
            default_job = engine.job_from_payload(
                {"sourceUrl": "https://example.com/another"}
            )

            window = engine.EngineWindow(job)
            options = window.build_options()
            expected = app_dir / "state" / "download-archive.txt"
            self.assertEqual(Path(options["download_archive"]), expected)
            self.assertTrue(expected.parent.is_dir())
            self.assertNotEqual(expected.parent, app_dir / "downloads")

            default_window = engine.EngineWindow(default_job)
            self.assertNotIn("download_archive", default_window.build_options())

    def test_external_job_receives_archive_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            engine = make_fake_engine(app_dir)
            archive_policy.install_archive_policy(engine)

            enabled = engine.job_from_payload(
                {
                    "sourceUrl": "https://example.com/video",
                    "skipPreviouslyDownloaded": True,
                }
            )
            disabled = engine.job_from_payload(
                {"sourceUrl": "https://example.com/another"}
            )

            enabled_archive = engine.EngineWindow(enabled)._run_external_job(Path("yt-dlp.exe"))
            self.assertEqual(Path(enabled_archive), app_dir / "state" / "download-archive.txt")
            self.assertIsNone(engine.EngineWindow(disabled)._run_external_job(Path("yt-dlp.exe")))

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
