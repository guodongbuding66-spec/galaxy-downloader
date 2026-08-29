from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.main import (
    common_yt_dlp_args,
    format_has_audio,
    format_has_video,
    parse_with_ytdlp,
    platform_id,
    run_process,
    validate_public_source_url,
)

PROBE_TIMEOUT = int(os.getenv("GALAXY_SMOKE_PROBE_TIMEOUT", "75"))
PROBE_SECONDS = float(os.getenv("GALAXY_SMOKE_PROBE_SECONDS", "1.0"))


def score_video(fmt: dict[str, Any]) -> tuple[int, int, float, int]:
    muxed = format_has_video(fmt) and format_has_audio(fmt)
    height = int(fmt.get("height") or 0)
    bitrate = float(fmt.get("tbr") or 0)
    size = int(fmt.get("filesize") or fmt.get("filesize_approx") or 0)
    return (1 if muxed else 0, height, bitrate, size)


def score_audio(fmt: dict[str, Any]) -> tuple[float, int]:
    bitrate = float(fmt.get("abr") or fmt.get("tbr") or 0)
    size = int(fmt.get("filesize") or fmt.get("filesize_approx") or 0)
    return (bitrate, size)


def choose_formats(info: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    formats = [
        fmt for fmt in info.get("formats") or []
        if isinstance(fmt, dict) and isinstance(fmt.get("url"), str)
    ]
    videos = [fmt for fmt in formats if format_has_video(fmt)]
    audios = [fmt for fmt in formats if format_has_audio(fmt)]
    video = max(videos, key=score_video, default=None)
    audio = max(audios, key=score_audio, default=None)
    return video, audio


def compact_format(fmt: dict[str, Any] | None) -> dict[str, Any] | None:
    if not fmt:
        return None
    return {
        "formatId": fmt.get("format_id"),
        "ext": fmt.get("ext"),
        "height": fmt.get("height"),
        "width": fmt.get("width"),
        "fps": fmt.get("fps"),
        "vcodec": fmt.get("vcodec"),
        "acodec": fmt.get("acodec"),
        "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
        "protocol": fmt.get("protocol"),
    }


def probe_download(source_url: str, fmt: dict[str, Any] | None, label: str) -> dict[str, Any] | None:
    if not fmt:
        return None

    format_id = str(fmt.get("format_id") or "").strip()
    selector = format_id or ("bestvideo/best" if label == "video" else "bestaudio/best")

    with tempfile.TemporaryDirectory(prefix=f"galaxy-smoke-{label}-") as directory:
        output = Path(directory) / "probe.%(ext)s"
        command = common_yt_dlp_args() + [
            "--quiet",
            "--no-progress",
            "--force-overwrites",
            "--no-part",
            "--format",
            selector,
            "--download-sections",
            f"*0-{PROBE_SECONDS:g}",
            "--output",
            str(output),
            source_url,
        ]
        try:
            completed = run_process(command, PROBE_TIMEOUT)
        except Exception as exc:
            return {
                "ok": False,
                "method": "yt-dlp-section",
                "formatId": format_id or None,
                "error": f"{type(exc).__name__}: {exc}",
            }

        files = [path for path in Path(directory).iterdir() if path.is_file()]
        total_bytes = sum(path.stat().st_size for path in files)
        if completed.returncode != 0 or total_bytes <= 0:
            diagnostic = (completed.stderr or completed.stdout or "yt-dlp probe failed")[-3500:].strip()
            return {
                "ok": False,
                "method": "yt-dlp-section",
                "formatId": format_id or None,
                "exitCode": completed.returncode,
                "bytes": total_bytes,
                "error": diagnostic,
            }

        return {
            "ok": True,
            "method": "yt-dlp-section",
            "formatId": format_id or None,
            "bytes": total_bytes,
            "files": [
                {
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "suffix": path.suffix.lower(),
                }
                for path in files
            ],
        }


def run(url: str) -> dict[str, Any]:
    source_url = validate_public_source_url(url)
    try:
        info = parse_with_ytdlp(source_url)
    except Exception as exc:
        detail = getattr(exc, "detail", None)
        status_code = getattr(exc, "status_code", None)
        return {
            "status": "PARSE_FAIL",
            "url": source_url,
            "httpStatus": status_code,
            "error": str(detail or exc),
        }

    video, audio = choose_formats(info)
    video_probe = probe_download(source_url, video, "video")

    same_format = bool(
        video
        and audio
        and str(video.get("format_id") or "") == str(audio.get("format_id") or "")
    )
    if same_format:
        audio_probe = video_probe
    elif video_probe and video_probe.get("ok"):
        # One successful real media download is enough to prove that this
        # platform's extraction + authenticated media path works. Avoid a
        # second network-heavy probe unless video failed or the item is audio-only.
        audio_probe = None
    else:
        audio_probe = probe_download(source_url, audio, "audio")

    has_media = bool(video_probe and video_probe.get("ok")) or bool(audio_probe and audio_probe.get("ok"))
    status = "PASS" if has_media else "MEDIA_FAIL"
    return {
        "status": status,
        "url": source_url,
        "platform": platform_id(info),
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "formatCount": len(info.get("formats") or []),
        "videoFormat": compact_format(video),
        "audioFormat": compact_format(audio),
        "videoProbe": video_probe,
        "audioProbe": audio_probe,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m app.smoke_cli <media-url>", file=sys.stderr)
        return 2
    report = run(sys.argv[1])
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
