from __future__ import annotations

import os
import subprocess
import sys
import urllib.parse
from collections.abc import Sequence

REAL_YTDLP = os.getenv("GALAXY_REAL_YTDLP", "/opt/venv/bin/yt-dlp")
COOKIE_POLICY = os.getenv("YTDLP_COOKIE_POLICY", "when_needed").strip().lower()

AUTH_RETRY_MARKERS = (
    "sign in",
    "login required",
    "private video",
    "members-only",
    "members only",
    "age-restricted",
    "age restricted",
    "confirm you're not a bot",
    "confirm you’re not a bot",
    "cookies are required",
    "http error 401",
    "http error 403",
)


def find_source_url(args: Sequence[str]) -> str:
    for value in reversed(args):
        if value.startswith(("https://", "http://")):
            return value
    return ""


def platform_hint(source_url: str) -> str:
    try:
        host = (urllib.parse.urlsplit(source_url).hostname or "").lower()
    except ValueError:
        return "generic"
    if host == "youtu.be" or host.endswith(".youtube.com") or host == "youtube.com":
        return "youtube"
    if host.endswith(".xiaohongshu.com") or host == "xiaohongshu.com" or host.endswith(".xhslink.com") or host == "xhslink.com":
        return "xiaohongshu"
    if host.endswith(".twitch.tv") or host == "twitch.tv":
        return "twitch"
    if host.endswith(".rumble.com") or host == "rumble.com":
        return "rumble"
    return "generic"


def has_cookie_args(args: Sequence[str]) -> bool:
    return any(value == "--cookies" or value.startswith("--cookies=") for value in args)


def strip_cookie_args(args: Sequence[str]) -> list[str]:
    output: list[str] = []
    skip_next = False
    for value in args:
        if skip_next:
            skip_next = False
            continue
        if value == "--cookies":
            skip_next = True
            continue
        if value.startswith("--cookies="):
            continue
        output.append(value)
    return output


def replace_proxy(args: Sequence[str], proxy: str) -> list[str]:
    output: list[str] = []
    skip_next = False
    for value in args:
        if skip_next:
            skip_next = False
            continue
        if value == "--proxy":
            skip_next = True
            continue
        if value.startswith("--proxy="):
            continue
        output.append(value)
    if proxy:
        return ["--proxy", proxy, *output]
    return output


def should_retry_with_cookies(stderr: bytes, platform: str) -> bool:
    message = stderr.decode("utf-8", errors="replace").lower()
    if any(marker in message for marker in AUTH_RETRY_MARKERS):
        return True
    # RedNote often returns an apparently successful page while withholding media data
    # from anonymous sessions, which yt-dlp reports as no formats rather than a login error.
    if platform == "xiaohongshu" and "no video formats found" in message:
        return True
    return False


def run_real(args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [REAL_YTDLP, *args],
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )


def emit(completed: subprocess.CompletedProcess[bytes], prefix: bytes = b"") -> int:
    if completed.stdout:
        sys.stdout.buffer.write(completed.stdout)
    if prefix:
        sys.stderr.buffer.write(prefix)
    if completed.stderr:
        sys.stderr.buffer.write(completed.stderr)
    return completed.returncode


def main() -> int:
    args = list(sys.argv[1:])
    source_url = find_source_url(args)
    platform = platform_hint(source_url)

    # Rumble's current failures are Cloudflare/TLS-fingerprint related. Keep a dedicated
    # route so an anti-bot proxy/mitm layer can be enabled without sending all traffic there.
    if platform == "rumble":
        rumble_proxy = os.getenv("YTDLP_RUMBLE_PROXY", "").strip()
        if rumble_proxy:
            args = replace_proxy(args, rumble_proxy)

    cookies_present = has_cookie_args(args)
    anonymous_args = strip_cookie_args(args)

    # yt-dlp currently documents Twitch cases where passing cookies breaks extraction.
    if platform == "twitch" and os.getenv("YTDLP_TWITCH_ALLOW_COOKIES", "0") != "1":
        return emit(run_real(anonymous_args))

    if COOKIE_POLICY == "never":
        return emit(run_real(anonymous_args))

    if COOKIE_POLICY == "always" or not cookies_present:
        return emit(run_real(args))

    # Default: Pinchflat-style "when needed". Try the least stateful request first and
    # only consume account/session cookies after an authentication-shaped failure.
    first = run_real(anonymous_args)
    if first.returncode == 0 or not should_retry_with_cookies(first.stderr, platform):
        return emit(first)

    second = run_real(args)
    diagnostic = b"[galaxy] anonymous attempt failed; retrying with configured cookies\n"
    if first.stderr:
        diagnostic += first.stderr[-2000:] + b"\n"
    return emit(second, diagnostic)


if __name__ == "__main__":
    raise SystemExit(main())
