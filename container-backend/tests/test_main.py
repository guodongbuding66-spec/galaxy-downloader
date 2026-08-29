from __future__ import annotations

import socket
from pathlib import Path

from fastapi.testclient import TestClient

from app import main as backend


def _public_dns(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def test_validate_public_source_url_blocks_private_targets(monkeypatch):
    monkeypatch.setattr(backend.socket, "getaddrinfo", _public_dns)

    assert backend.validate_public_source_url("https://example.com/video") == "https://example.com/video"

    for value in (
        "http://127.0.0.1/media",
        "http://10.0.0.1/media",
        "http://localhost/media",
        "http://user:pass@example.com/media",
        "file:///etc/passwd",
    ):
        try:
            backend.validate_public_source_url(value)
        except Exception:
            pass
        else:
            raise AssertionError(f"private/unsafe URL was accepted: {value}")


def test_normalize_twitch_clip_with_muxed_formats():
    info = {
        "extractor_key": "TwitchClips",
        "title": "Example clip",
        "thumbnail": "https://cdn.example/cover.jpg",
        "duration": 12.5,
        "formats": [
            {
                "format_id": "720",
                "url": "https://cdn.example/clip-720.mp4",
                "height": 720,
                "width": 1280,
                "fps": 60,
                "ext": "mp4",
                "vcodec": "avc1.64001f",
                "acodec": "mp4a.40.2",
                "tbr": 2500,
            },
            {
                "format_id": "480",
                "url": "https://cdn.example/clip-480.mp4",
                "height": 480,
                "width": 854,
                "fps": 30,
                "ext": "mp4",
                "vcodec": "avc1.4d401e",
                "acodec": "mp4a.40.2",
                "tbr": 1200,
            },
        ],
    }

    result = backend.normalize_parse_result(
        info,
        "https://clips.twitch.tv/example",
        "https://backend.example",
    )

    assert result["platform"] == "twitch"
    assert result["kind"] == "video"
    assert result["videoAudioMode"] == "muxed"
    assert result["downloadVideoUrl"].startswith("https://backend.example/api/download?")
    assert result["downloadAudioUrl"].startswith("https://backend.example/api/download?")
    assert [item["quality"] for item in result["qualityOptions"]] == ["best", "720", "480"]


def test_separate_video_audio_detection():
    info = {
        "extractor_key": "Youtube",
        "title": "Separate streams",
        "formats": [
            {
                "format_id": "137",
                "url": "https://cdn.example/video.mp4",
                "height": 1080,
                "ext": "mp4",
                "vcodec": "avc1",
                "acodec": "none",
            },
            {
                "format_id": "140",
                "url": "https://cdn.example/audio.m4a",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a",
            },
        ],
    }

    result = backend.normalize_parse_result(
        info,
        "https://www.youtube.com/watch?v=test",
        "https://backend.example",
    )

    assert result["platform"] == "youtube"
    assert result["videoAudioMode"] == "separate"
    assert result["downloadVideoUrl"]
    assert result["downloadAudioUrl"]


def test_format_selection_prefers_requested_quality_and_audio():
    assert backend.select_format("audio", "best", None) == "ba/b"
    assert backend.select_format("video", "1080", None) == "bv*[height<=1080]+ba/b[height<=1080]/b"
    assert backend.select_format("video", "best", "137") == "137+ba/137/b"
    assert backend.select_format("video", "best", "../../unsafe") == "unsafe+ba/unsafe/b"


def test_common_ytdlp_args_enable_supported_runtime_and_impersonation():
    args = backend.common_yt_dlp_args()
    runtime_index = args.index("--js-runtimes")
    impersonate_index = args.index("--impersonate")
    assert args[runtime_index + 1] == "node"
    assert args[impersonate_index + 1]


def test_parse_endpoint_returns_frontend_compatible_shape(monkeypatch):
    monkeypatch.setattr(backend, "validate_public_source_url", lambda value: value)
    monkeypatch.setattr(
        backend,
        "parse_with_ytdlp",
        lambda _value: {
            "extractor_key": "Weibo",
            "title": "Weibo test",
            "formats": [
                {
                    "format_id": "1",
                    "url": "https://cdn.example/video.mp4",
                    "height": 720,
                    "ext": "mp4",
                    "vcodec": "h264",
                    "acodec": "aac",
                }
            ],
        },
    )

    client = TestClient(backend.app)
    response = client.get(
        "/api/parse",
        params={"url": "https://weibo.com/example"},
        headers={"x-request-id": "test-request"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["requestId"] == "test-request"
    assert payload["data"]["platform"] == "weibo"
    assert "/api/download?" in payload["data"]["downloadVideoUrl"]


def test_download_endpoint_streams_created_media_and_cleans_temp_dir(monkeypatch):
    monkeypatch.setattr(backend, "validate_public_source_url", lambda value: value)
    created_dirs: list[Path] = []

    def fake_download(_url: str, _media_type: str, _quality: str, _format_id: str | None, output_dir: Path) -> Path:
        created_dirs.append(output_dir)
        target = output_dir / "media.mp4"
        target.write_bytes(b"galaxy-media-test")
        return target

    monkeypatch.setattr(backend, "download_with_ytdlp", fake_download)

    client = TestClient(backend.app)
    response = client.get(
        "/api/download",
        params={"url": "https://example.com/video", "type": "video"},
        headers={"x-request-id": "download-test"},
    )

    assert response.status_code == 200
    assert response.content == b"galaxy-media-test"
    assert response.headers["x-request-id"] == "download-test"
    assert created_dirs and not created_dirs[0].exists()


def test_health_endpoint():
    client = TestClient(backend.app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["service"] == "galaxy-downloader-backend"
