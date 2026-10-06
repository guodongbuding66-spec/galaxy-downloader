from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from download_profile_policy import (  # noqa: E402
    apply_profile_to_external_command,
    apply_profile_to_job,
    profile_output_template,
    run_download_profile_policy_self_test,
)


def main() -> int:
    run_download_profile_policy_self_test()

    from dataclasses import dataclass
    import tempfile

    @dataclass(frozen=True)
    class Job:
        source_url: str
        video_quality: str = "best"
        audio_quality: str = "best"
        include_audio: bool = True
        include_subtitle: bool = False
        subtitle_lang: str | None = None
        browser: str = "none"
        skip_previously_downloaded: bool = False
        split_chapters: bool = False
        subtitle_languages: tuple[str, ...] = ()
        sponsorblock_categories: tuple[str, ...] = ()
        download_profile_id: str = ""
        download_profile_name: str = ""
        profile_container: str = ""
        profile_directory: str = ""
        profile_filename: str = ""
        profile_rate_limit_mib: float | None = None
        profile_post_process: str = ""

    profile = {
        "id": "b" * 32,
        "name": "Course Archive",
        "settings": {
            "video": "1080p",
            "audio": "best",
            "container": "mkv",
            "subtitle": "en",
            "archive": True,
            "browser": "chrome",
            "directory": "Courses/Udemy",
            "filename": "%(title)s [%(id)s]",
            "rateLimitMiB": 8,
            "chapters": True,
            "sponsorBlock": True,
            "postProcess": "remux",
        },
    }
    job = apply_profile_to_job(Job("https://www.udemy.com/course/demo"), profile)
    assert job.video_quality == "1080p"
    assert job.download_profile_name == "Course Archive"
    assert job.include_subtitle is True
    assert job.skip_previously_downloaded is True
    assert job.browser == "chrome"

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class FakeEngine:
            @staticmethod
            def default_download_dir() -> Path:
                return root

        outtmpl = profile_output_template(FakeEngine, job, str(root / "default.%(ext)s"))
        normalized = outtmpl.replace("\\", "/")
        assert normalized.endswith("Courses/Udemy/%(title)s [%(id)s].%(ext)s")

        command = [
            "yt-dlp",
            "--merge-output-format", "mp4/mkv",
            "--limit-rate", "1M",
            "-o", str(root / "old.%(ext)s"),
            "--", job.source_url,
        ]
        applied = apply_profile_to_external_command(FakeEngine, job, command)
        assert applied[applied.index("--merge-output-format") + 1] == "mkv"
        assert applied[applied.index("--limit-rate") + 1] == str(8 * 1024 * 1024)
        assert applied[applied.index("--remux-video") + 1] == "mkv"
        assert applied[applied.index("-o") + 1].replace("\\", "/").endswith(
            "Courses/Udemy/%(title)s [%(id)s].%(ext)s"
        )

    print("download profile application contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
