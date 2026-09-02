from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from media_cleanup import (  # noqa: E402
    CleanupRegion,
    MediaCleanupCancelled,
    MediaCleanupError,
    cleanup_visible_overlay,
    probe_media,
)


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=90)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "command failed").strip()
        raise AssertionError(f"Command failed ({completed.returncode}): {' '.join(command)}\n{detail}")


def _resolve_ffmpeg_directory(explicit: str | None) -> Path:
    if explicit:
        root = Path(explicit).expanduser().resolve()
    else:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise AssertionError("ffmpeg and ffprobe are required for the integration regression")
        ffmpeg_path = Path(ffmpeg).resolve()
        ffprobe_path = Path(ffprobe).resolve()
        if ffmpeg_path.parent != ffprobe_path.parent:
            raise AssertionError("ffmpeg and ffprobe must come from the same directory")
        root = ffmpeg_path.parent

    ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    ffprobe_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    if not (root / ffmpeg_name).is_file():
        raise AssertionError(f"Missing {ffmpeg_name} in {root}")
    if not (root / ffprobe_name).is_file():
        raise AssertionError(f"Missing {ffprobe_name} in {root}")
    return root


def _tool(root: Path, name: str) -> Path:
    exe = root / f"{name}.exe"
    return exe if exe.exists() else root / name


def _create_fixture_image(ffmpeg: Path, output: Path) -> None:
    _run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:d=1",
            "-vf",
            "drawbox=x=80:y=40:w=64:h=32:color=white:t=fill",
            "-frames:v",
            "1",
            str(output),
        ]
    )


def _create_fixture_video(ffmpeg: Path, output: Path) -> None:
    _run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=25:duration=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=44100:duration=3",
            "-vf",
            "drawbox=x=80:y=40:w=64:h=32:color=white:t=fill",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ]
    )


def _assert_manifest(result, expected_kind: str) -> None:
    assert result.output_path.is_file() and result.output_path.stat().st_size > 0
    assert result.manifest_path.is_file()
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["operation"] == "visible-overlay-cleanup"
    assert payload["method"] == "ffmpeg-delogo"
    assert payload["mediaKind"] == expected_kind
    assert payload["sourceSha256"] == result.source_sha256
    assert payload["outputSha256"] == result.output_sha256
    assert payload["sourceSha256"] != payload["outputSha256"]
    assert payload["regions"] == [{"x": 80, "y": 40, "width": 64, "height": 32}]


def _assert_audio_preserved(ffprobe: Path, output: Path) -> None:
    completed = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout or "{}")
    assert (payload.get("streams") or [{}])[0].get("codec_type") == "audio"


def run_regression(ffmpeg_directory: Path) -> None:
    ffmpeg = _tool(ffmpeg_directory, "ffmpeg")
    ffprobe = _tool(ffmpeg_directory, "ffprobe")
    region = CleanupRegion(80, 40, 64, 32)

    with tempfile.TemporaryDirectory(prefix="galaxy-media-cleanup-") as directory:
        root = Path(directory)
        source_image = root / "source.png"
        source_video = root / "source.mp4"
        _create_fixture_image(ffmpeg, source_image)
        _create_fixture_video(ffmpeg, source_video)

        image_probe = probe_media(ffprobe, source_image, "image")
        assert (image_probe.width, image_probe.height, image_probe.media_kind) == (320, 180, "image")
        image_result = cleanup_visible_overlay(ffmpeg_directory, source_image, (region,))
        _assert_manifest(image_result, "image")

        second_image_result = cleanup_visible_overlay(ffmpeg_directory, source_image, (region,))
        assert second_image_result.output_path.name == "source.cleaned-2.png"
        assert second_image_result.output_path != image_result.output_path

        video_probe = probe_media(ffprobe, source_video, "video")
        assert (video_probe.width, video_probe.height, video_probe.media_kind) == (320, 180, "video")
        assert video_probe.duration_seconds > 0
        progress_samples: list[float] = []
        video_result = cleanup_visible_overlay(
            ffmpeg_directory,
            source_video,
            (region,),
            progress_callback=lambda percent, _status: progress_samples.append(percent),
        )
        _assert_manifest(video_result, "video")
        _assert_audio_preserved(ffprobe, video_result.output_path)
        assert progress_samples and progress_samples[0] == 0.0
        assert progress_samples[-1] == 100.0
        assert all(0.0 <= value <= 100.0 for value in progress_samples)

        cancelled_output = root / "cancelled.mp4"
        cancel_event = threading.Event()

        def cancel_after_prepare(percent: float, _status: str) -> None:
            if percent == 0.0:
                cancel_event.set()

        try:
            cleanup_visible_overlay(
                ffmpeg_directory,
                source_video,
                (region,),
                output_path=cancelled_output,
                cancel_event=cancel_event,
                progress_callback=cancel_after_prepare,
            )
        except MediaCleanupCancelled:
            pass
        else:
            raise AssertionError("Expected media cleanup cancellation")
        assert not cancelled_output.exists()
        assert not cancelled_output.with_suffix(".mp4.cleanup.json").exists()

        try:
            cleanup_visible_overlay(ffmpeg_directory, source_image, (CleanupRegion(300, 170, 40, 20),))
        except MediaCleanupError as exc:
            assert "exceeds" in str(exc).lower()
        else:
            raise AssertionError("Out-of-frame cleanup region should fail closed")

        missing_tools = root / "missing-tools"
        missing_tools.mkdir()
        try:
            cleanup_visible_overlay(missing_tools, source_image, (region,))
        except MediaCleanupError as exc:
            assert "ffmpeg" in str(exc).lower()
        else:
            raise AssertionError("Missing FFmpeg should fail closed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise media cleanup with real FFmpeg/FFprobe binaries")
    parser.add_argument("--ffmpeg-dir", help="Directory containing ffmpeg[.exe] and ffprobe[.exe]")
    args = parser.parse_args()
    ffmpeg_directory = _resolve_ffmpeg_directory(args.ffmpeg_dir)
    run_regression(ffmpeg_directory)
    print(f"Media cleanup integration regression passed with {ffmpeg_directory}")
