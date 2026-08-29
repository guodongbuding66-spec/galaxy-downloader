from app.yt_dlp_wrapper import (
    find_source_url,
    platform_hint,
    platform_proxy,
    replace_proxy,
    should_retry_with_cookies,
    strip_cookie_args,
)


def test_platform_hint_covers_special_routes() -> None:
    assert platform_hint("https://www.youtube.com/watch?v=abc") == "youtube"
    assert platform_hint("https://www.xiaohongshu.com/explore/abc") == "xiaohongshu"
    assert platform_hint("https://clips.twitch.tv/example") == "twitch"
    assert platform_hint("https://rumble.com/v-example.html") == "rumble"


def test_find_source_url_uses_last_http_argument() -> None:
    assert find_source_url(["--proxy", "http://proxy.test:8080", "https://rumble.com/v1.html"]) == "https://rumble.com/v1.html"


def test_strip_cookie_args_handles_both_forms() -> None:
    assert strip_cookie_args(["--cookies", "/tmp/c.txt", "--format", "best", "https://example.com"]) == [
        "--format",
        "best",
        "https://example.com",
    ]
    assert strip_cookie_args(["--cookies=/tmp/c.txt", "https://example.com"]) == ["https://example.com"]


def test_replace_proxy_is_platform_override_safe() -> None:
    assert replace_proxy(["--proxy", "http://global:1", "https://rumble.com/v1"], "http://rumble:2") == [
        "--proxy",
        "http://rumble:2",
        "https://rumble.com/v1",
    ]


def test_platform_proxy_uses_isolated_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("YTDLP_YOUTUBE_PROXY", "http://youtube-proxy:8080")
    monkeypatch.setenv("YTDLP_XHS_PROXY", "http://xhs-proxy:8080")
    monkeypatch.setenv("YTDLP_RUMBLE_PROXY", "http://rumble-proxy:8080")
    assert platform_proxy("youtube") == "http://youtube-proxy:8080"
    assert platform_proxy("xiaohongshu") == "http://xhs-proxy:8080"
    assert platform_proxy("rumble") == "http://rumble-proxy:8080"
    assert platform_proxy("twitch") == ""
    assert platform_proxy("generic") == ""


def test_xiaohongshu_no_formats_can_retry_with_cookies() -> None:
    assert should_retry_with_cookies(b"ERROR: No video formats found", "xiaohongshu") is True
    assert should_retry_with_cookies(b"ERROR: No video formats found", "generic") is False


def test_auth_failures_can_retry_with_cookies() -> None:
    assert should_retry_with_cookies(b"ERROR: Sign in to confirm you're not a bot", "youtube") is True
    assert should_retry_with_cookies(b"ERROR: HTTP Error 403: Forbidden", "generic") is True
