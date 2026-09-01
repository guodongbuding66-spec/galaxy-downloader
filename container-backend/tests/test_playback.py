from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import playback
from app.server import app

client = TestClient(app)


def muxed_format(url: str, *, height: int = 720, ext: str = "mp4") -> dict[str, Any]:
    return {
        "url": url,
        "protocol": "https",
        "ext": ext,
        "height": height,
        "fps": 30,
        "tbr": 1500,
        "vcodec": "h264",
        "acodec": "aac",
    }


def test_server_registers_dedicated_playback_route():
    response = client.get(
        "/api/play",
        params={"url": "https://example.com/watch/1", "type": "invalid"},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "BAD_REQUEST"
    assert payload["error"] == "type must be video or audio"


def test_video_preview_prefers_one_muxed_progressive_stream():
    info = {
        "formats": [
            {
                "url": "https://cdn.example/video-only.mp4",
                "protocol": "https",
                "ext": "mp4",
                "height": 2160,
                "vcodec": "h264",
                "acodec": "none",
            },
            muxed_format("https://cdn.example/muxed-720.mp4", height=720),
            muxed_format("https://cdn.example/muxed-1080.webm", height=1080, ext="webm"),
        ]
    }

    selected = playback._preview_candidate(info, "video")
    assert selected is not None
    # Compatibility is scored before resolution so browsers get a broadly
    # playable MP4 stream instead of a higher but less portable container.
    assert selected["url"] == "https://cdn.example/muxed-720.mp4"
    assert selected["acodec"] == "aac"


def test_video_preview_does_not_silently_choose_video_only_dash():
    info = {
        "formats": [
            {
                "url": "https://cdn.example/video-only.mp4",
                "protocol": "https",
                "ext": "mp4",
                "height": 2160,
                "vcodec": "h264",
                "acodec": "none",
            },
            {
                "url": "https://cdn.example/audio.m4a",
                "protocol": "https",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "aac",
            },
        ]
    }

    assert playback._preview_candidate(info, "video") is None


def test_parser_headers_never_forward_cookie_or_authorization():
    info = {
        "http_headers": {
            "User-Agent": "Galaxy Test",
            "Cookie": "session=secret",
            "Authorization": "Bearer secret",
            "Referer": "https://provider.example/watch/1",
        }
    }
    fmt = muxed_format("https://cdn.example/video.mp4")
    fmt["http_headers"] = {
        "Origin": "https://provider.example",
        "Cookie": "other=secret",
    }

    headers = playback._format_request_headers(info, fmt)
    lowered = {key.lower(): value for key, value in headers.items()}
    assert lowered["user-agent"] == "Galaxy Test"
    assert lowered["referer"] == "https://provider.example/watch/1"
    assert lowered["origin"] == "https://provider.example"
    assert "cookie" not in lowered
    assert "authorization" not in lowered


def test_single_range_policy_accepts_normal_browser_ranges():
    assert playback._validated_range_header(None) is None
    assert playback._validated_range_header("") is None
    assert playback._validated_range_header("bytes=0-") == "bytes=0-"
    assert playback._validated_range_header("BYTES=100-200") == "bytes=100-200"
    assert playback._validated_range_header("bytes=-500") == "bytes=-500"


@pytest.mark.parametrize(
    "value",
    [
        "items=0-10",
        "bytes=-",
        "bytes=-0",
        "bytes=500-100",
        "bytes=0-10,20-30",
        "bytes=0 - 10",
        "bytes=99999999999999999999-",
        "bytes=" + "1" * 140 + "-",
    ],
)
def test_single_range_policy_rejects_malformed_or_multipart_ranges(value: str):
    with pytest.raises(ValueError):
        playback._validated_range_header(value)


def test_playback_redirect_requires_location_header():
    class FakeRedirect:
        headers: dict[str, str] = {}

    with pytest.raises(RuntimeError, match="missing Location"):
        playback._redirect_target(
            "https://cdn.example/video.mp4",
            FakeRedirect(),  # type: ignore[arg-type]
            0,
        )


def test_playback_redirect_limit_is_fail_closed(monkeypatch):
    class FakeRedirect:
        headers = {"location": "/next.mp4"}

    monkeypatch.setattr(playback, "PLAYBACK_MAX_REDIRECTS", 1)
    assert playback._redirect_target(
        "https://cdn.example/video.mp4",
        FakeRedirect(),  # type: ignore[arg-type]
        0,
    ) == "https://cdn.example/next.mp4"

    with pytest.raises(RuntimeError, match="redirect limit exceeded"):
        playback._redirect_target(
            "https://cdn.example/video.mp4",
            FakeRedirect(),  # type: ignore[arg-type]
            1,
        )


def test_invalid_range_is_rejected_before_parser_work(monkeypatch):
    monkeypatch.setattr(playback.core, "validate_public_source_url", lambda value: value)

    async def should_not_parse(_source_url: str, _media_type: str):
        raise AssertionError("parser must not run for an invalid Range header")

    monkeypatch.setattr(playback, "_resolve_preview", should_not_parse)
    response = client.get(
        "/api/play",
        params={"url": "https://example.com/watch/1", "type": "video"},
        headers={"Range": "bytes=0-10,20-30"},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "BAD_REQUEST"
    assert payload["error"] == "Range must be a single valid bytes range."


def test_no_muxed_preview_redirects_to_finished_file_compatibility_path(monkeypatch):
    monkeypatch.setattr(playback.core, "validate_public_source_url", lambda value: value)

    async def no_preview(_source_url: str, _media_type: str):
        return None

    monkeypatch.setattr(playback, "_resolve_preview", no_preview)

    response = client.get(
        "/api/play",
        params={"url": "https://example.com/watch/1", "type": "video"},
        follow_redirects=False,
    )
    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("/api/download?")
    assert "type=video" in location
    assert "quality=best" in location


def test_range_header_and_partial_content_are_preserved(monkeypatch):
    monkeypatch.setattr(playback.core, "validate_public_source_url", lambda value: value)

    async def resolved(_source_url: str, _media_type: str):
        return "https://cdn.example/video.mp4", {"User-Agent": "Galaxy Test"}

    captured: dict[str, Any] = {}

    class FakeClient:
        async def aclose(self):
            captured["client_closed"] = True

    class FakeResponse:
        status_code = 206
        headers = {
            "content-type": "video/mp4",
            "content-length": "4",
            "content-range": "bytes 0-3/10",
            "accept-ranges": "bytes",
        }

        async def aiter_raw(self):
            yield b"test"

        async def aclose(self):
            captured["response_closed"] = True

    async def open_upstream(target_url: str, method: str, headers: dict[str, str]):
        captured["target_url"] = target_url
        captured["method"] = method
        captured["headers"] = dict(headers)
        return FakeClient(), FakeResponse()

    monkeypatch.setattr(playback, "_resolve_preview", resolved)
    monkeypatch.setattr(playback, "_open_validated_upstream", open_upstream)

    response = client.get(
        "/api/play",
        params={"url": "https://example.com/watch/1", "type": "video"},
        headers={"Range": "bytes=0-3"},
    )

    assert response.status_code == 206
    assert response.content == b"test"
    assert response.headers["content-range"] == "bytes 0-3/10"
    assert response.headers["accept-ranges"] == "bytes"
    assert captured["headers"]["Range"] == "bytes=0-3"
    assert captured["response_closed"] is True
    assert captured["client_closed"] is True
