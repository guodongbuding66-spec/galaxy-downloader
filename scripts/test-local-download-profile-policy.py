#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from download_profile_policy import (  # noqa: E402
    PROFILE_APPLIED_JOB_FIELDS,
    PROFILE_DEFERRED_FIELDS,
    install_download_profile_policy,
    payload_explicit_fields,
    profile_settings,
    run_download_profile_policy_self_test,
)
from download_profiles import create_profile  # noqa: E402


@dataclass(frozen=True)
class BaseJob:
    source_url: str
    video_quality: str = "best"
    audio_quality: str = "best"
    include_subtitle: bool = False
    subtitle_lang: str | None = None
    browser: str = "none"
    skip_previously_downloaded: bool = False
    split_chapters: bool = False


class FakeWindow:
    def bridge_status(self):
        return {"state": "ready"}


def make_engine(root: Path):
    state = root / "state"
    state.mkdir(parents=True, exist_ok=True)
    engine = SimpleNamespace()
    engine.Job = BaseJob
    engine.EngineWindow = FakeWindow
    engine.state_dir = lambda: state
    engine.app_dir = lambda: root
    engine._bool = lambda value, default=False: default if value is None else str(value).lower() in {"1", "true", "yes", "on"}

    def parse_job(raw: str):
        query = parse_qs(urlparse(raw).query)
        return engine.Job(
            source_url=unquote(query.get("url", [""])[0]),
            video_quality=query.get("video", ["best"])[0] or "best",
            audio_quality=query.get("audio", ["best"])[0] or "best",
            include_subtitle=engine._bool(query.get("subtitle", ["0"])[0]),
            subtitle_lang=query.get("subtitle_lang", [""])[0] or None,
            browser=query.get("browser", ["none"])[0] or "none",
            skip_previously_downloaded=engine._bool(query.get("archive", ["0"])[0]),
            split_chapters=engine._bool(query.get("split_chapters", ["0"])[0]),
        )

    def job_from_payload(payload):
        return engine.Job(
            source_url=str(payload.get("sourceUrl") or ""),
            video_quality=str(payload.get("videoQuality") or "best"),
            audio_quality=str(payload.get("audioQuality") or "best"),
            include_subtitle=bool(payload.get("includeSubtitle", False)),
            subtitle_lang=str(payload.get("subtitleLanguage") or "").strip() or None,
            browser=str(payload.get("browser") or "none"),
            skip_previously_downloaded=bool(payload.get("skipPreviouslyDownloaded", False)),
            split_chapters=bool(payload.get("splitChapters", False)),
        )

    def job_to_payload(job):
        return {
            "sourceUrl": job.source_url,
            "videoQuality": job.video_quality,
            "audioQuality": job.audio_quality,
            "includeSubtitle": job.include_subtitle,
            "subtitleLanguage": job.subtitle_lang,
            "browser": job.browser,
            "skipPreviouslyDownloaded": job.skip_previously_downloaded,
            "splitChapters": job.split_chapters,
        }

    engine.parse_job = parse_job
    engine.job_from_payload = job_from_payload
    engine.job_to_payload = job_to_payload
    return engine


def run() -> None:
    run_download_profile_policy_self_test()
    assert "container" in PROFILE_DEFERRED_FIELDS
    assert "script" in PROFILE_DEFERRED_FIELDS
    assert tuple(PROFILE_APPLIED_JOB_FIELDS) == ("video", "audio", "browser", "subtitle", "archive", "chapters")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        engine = make_engine(root)
        youtube = create_profile(
            engine,
            "YouTube 4K",
            patterns=["youtube.com/*"],
            settings={
                "video": "2160p",
                "audio": "192",
                "browser": "chrome",
                "subtitle": "en",
                "archive": True,
                "chapters": True,
                "container": "mkv",
                "directory": "Video/YouTube",
                "filename": "%(title)s",
                "rateLimitMiB": 12,
                "sponsorBlock": True,
                "postProcess": "remux",
                "script": {"enabled": False},
            },
        )
        course = create_profile(
            engine,
            "Course",
            patterns=["udemy.com/course/*"],
            settings={"video": "1080p", "audio": "best", "browser": "none", "archive": False},
        )

        job_cls = install_download_profile_policy(engine)
        assert job_cls is engine.Job
        assert getattr(FakeWindow, "_galaxy_download_profile_policy_installed", False) is True

        legacy_default_payload = {
            "sourceUrl": "https://youtube.com/watch?v=demo",
            "videoQuality": "best",
            "audioQuality": "best",
            "browser": "none",
            "includeSubtitle": False,
            "skipPreviouslyDownloaded": False,
            "splitChapters": False,
        }
        auto_job = engine.job_from_payload(legacy_default_payload)
        assert auto_job.profile_mode == "auto"
        assert auto_job.profile_id == youtube["id"]
        assert auto_job.video_quality == "2160p"
        assert auto_job.audio_quality == "192"
        assert auto_job.browser == "chrome"
        assert auto_job.include_subtitle is True
        assert auto_job.subtitle_lang == "en"
        assert auto_job.skip_previously_downloaded is True
        assert auto_job.split_chapters is True
        snapshot = profile_settings(auto_job)
        assert snapshot["container"] == "mkv"
        assert snapshot["directory"] == "Video/YouTube"
        assert snapshot["rateLimitMiB"] == 12.0
        assert snapshot["script"]["enabled"] is False

        non_default = engine.job_from_payload(
            {"sourceUrl": auto_job.source_url, "videoQuality": "1080p", "browser": "firefox"}
        )
        assert non_default.video_quality == "1080p"
        assert non_default.browser == "firefox"
        assert set(non_default.profile_explicit_fields) == {"video", "browser"}

        explicit_default = engine.job_from_payload(
            {
                **legacy_default_payload,
                "profileExplicitFields": ["video", "browser", "subtitle", "archive", "chapters"],
            }
        )
        assert explicit_default.video_quality == "best"
        assert explicit_default.browser == "none"
        assert explicit_default.include_subtitle is False
        assert explicit_default.skip_previously_downloaded is False
        assert explicit_default.split_chapters is False

        manual_job = engine.job_from_payload(
            {"sourceUrl": "https://example.com/course", "profileId": course["id"]}
        )
        assert manual_job.profile_mode == "manual"
        assert manual_job.profile_id == course["id"]
        assert manual_job.video_quality == "1080p"

        protocol_job = engine.parse_job(
            "galaxy-downloader://download?url=https%3A%2F%2Fyoutube.com%2Fwatch%3Fv%3Ddemo&video=best"
        )
        assert protocol_job.profile_mode == "auto"
        assert protocol_job.video_quality == "best"
        assert "video" in protocol_job.profile_explicit_fields

        auto_payload = engine.job_to_payload(auto_job)
        assert auto_payload["profileId"] == ""
        assert auto_payload["resolvedProfileId"] == youtube["id"]
        assert auto_payload["profileMode"] == "auto"
        assert auto_payload["profileExplicitFields"] == []

        manual_payload = engine.job_to_payload(manual_job)
        assert manual_payload["profileId"] == course["id"]
        assert manual_payload["resolvedProfileId"] == course["id"]
        assert manual_payload["profileMode"] == "manual"

        status = FakeWindow().bridge_status()
        policy = status["downloadProfilePolicy"]
        assert policy["autoApply"] is True
        assert policy["manualOverride"] is True
        assert policy["precedence"] == ["explicit", "manual-profile", "auto-profile", "global-default"]

        # Reinstall must be idempotent.
        assert install_download_profile_policy(engine) is engine.Job

    assert payload_explicit_fields({"videoQuality": "best", "browser": "none"}) == ()
    assert payload_explicit_fields({"subtitleMode": "manual"}) == ("subtitle",)
    assert payload_explicit_fields({"subtitleLanguages": ["en", "ja"]}) == ("subtitle",)
    source = (LOCAL_ENGINE / "download_profile_policy.py").read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "os.system" not in source
    assert "profileExplicitFields" in source
    assert "PROFILE_DEFERRED_FIELDS" in source

    entrypoint = (LOCAL_ENGINE / "entrypoint.py").read_text(encoding="utf-8")
    assert "install_download_profile_policy(engine)" in entrypoint
    assert "run_download_profile_policy_self_test()" in entrypoint
    assert "_galaxy_download_profile_policy_installed" in entrypoint


if __name__ == "__main__":
    run()
    print("Download Profile job-default precedence contract passed")
