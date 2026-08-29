from __future__ import annotations

import json
import os
import sys
import urllib.parse
from typing import Any

from curl_cffi import requests

from app.main import (
    format_has_audio,
    format_has_video,
    parse_with_ytdlp,
    platform_id,
    validate_public_source_url,
)

PROBE_BYTES = int(os.getenv("GALAXY_SMOKE_PROBE_BYTES", str(64 * 1024)))
PROBE_TIMEOUT = int(os.getenv("GALAXY_SMOKE_PROBE_TIMEOUT", "30"))


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


def probe_format(fmt: dict[str, Any] | None) -> dict[str, Any] | None:
    if not fmt or not isinstance(fmt.get("url"), str):
        return None

    headers = {
        str(key): str(value)
        for key, value in (fmt.get("http_headers") or {}).items()
        if isinstance(key, str) and isinstance(value, str) and value
    }
    headers["Range"] = f"bytes=0-{max(0, PROBE_BYTES - 1)}"
    impersonate = os.getenv("YTDLP_IMPERSONATE", "chrome")

    try:
        with requests.get(
            fmt["url"],
            headers=headers,
            timeout=PROBE_TIMEOUT,
            stream=True,
            impersonate=impersonate,
            allow_redirects=True,
        ) as response:
            received = 0
            for chunk in response.iter_content(chunk_size=min(32 * 1024, PROBE_BYTES)):
                if not chunk:
                    continue
                received += min(len(chunk), PROBE_BYTES - received)
                if received >= PROBE_BYTES:
                    break

            content_type = response.headers.get("content-type", "")
            final_host = urllib.parse.urlsplit(str(response.url)).hostname
            looks_error = content_type.lower().startswith(("text/html", "application/json", "text/plain")) and response.status_code >= 400
            return {
                "ok": 200 <= response.status_code < 400 and received > 0 and not looks_error,
                "status": response.status_code,
                "bytes": received,
                "contentType": content_type,
                "finalHost": final_host,
            }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
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
    video_probe = probe_format(video)
    if audio is video:
        audio_probe = video_probe
    else:
        audio_probe = probe_format(audio)

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
