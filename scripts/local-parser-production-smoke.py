#!/usr/bin/env python3
"""Probe deployed first-party parsers and read real media bytes.

A platform passes only when the deployed parser returns a normalized result and
the returned media path yields real non-text bytes. HLS playlists are followed
until a media segment is reached. Output includes parse/media timings so a
Vimeo control-plane timeout can be distinguished from a media/CDN failure.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL = "https://galaxy-downloader.guodongbuding66.workers.dev"
READ_BYTES = 64 * 1024
MAX_PLAYLIST_BYTES = 2 * 1024 * 1024
MAX_HLS_DEPTH = 8
USER_AGENT = "GalaxyDownloaderProductionSmoke/2.2 (+GitHub Actions)"
HLS_CONTENT_TYPES = {
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
}


@dataclass(frozen=True)
class Fixture:
    platform: str
    url: str
    media_type: str
    parse_path: str = "/api/local-parse"


FIXTURES = (
    # Real Vimeo URL reported by the Galaxy Downloader user on 2026-08-31.
    # It previously fell into browser-cookie extraction and surfaced
    # "ERROR: no such table: meta". Keep it as a permanent regression fixture.
    Fixture(
        "vimeo",
        "https://vimeo.com/1222036529?share=copy&fl=cl&fe=ci",
        "video",
        "/api/vimeo-native",
    ),
    # Current yt-dlp Dailymotion extractor test fixture.
    Fixture("dailymotion", "https://www.dailymotion.com/video/x5kesuj", "video"),
    Fixture(
        "apple_podcasts",
        "https://podcasts.apple.com/us/podcast/urbana-podcast-724-by-david-penn/id1531349107?i=1000748574256",
        "audio",
    ),
)


def elapsed_ms(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


def parse_endpoint(base_url: str, fixture: Fixture) -> str:
    query = urllib.parse.urlencode({"url": fixture.url})
    return f"{base_url.rstrip('/')}{fixture.parse_path}?{query}"


def absolute_url(base_url: str, value: str) -> str:
    return urllib.parse.urljoin(f"{base_url.rstrip('/')}/", value)


def request_json(url: str, timeout: int) -> tuple[int, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read(4 * 1024 * 1024)
        return int(getattr(response, "status", 200)), json.loads(payload.decode("utf-8"))


def request_bytes(
    url: str,
    timeout: int,
    *,
    use_range: bool,
    max_bytes: int,
) -> tuple[int, str, bytes]:
    headers = {
        "Accept": "*/*",
        "User-Agent": USER_AGENT,
    }
    if use_range:
        headers["Range"] = f"bytes=0-{READ_BYTES - 1}"

    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(max_bytes)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        return int(getattr(response, "status", 200)), content_type, body


def first_media_url(data: dict[str, Any], media_type: str) -> str | None:
    if media_type == "audio":
        value = data.get("downloadAudioUrl") or data.get("originDownloadAudioUrl")
        return value if isinstance(value, str) and value else None

    qualities = data.get("qualityOptions")
    if isinstance(qualities, list):
        for option in qualities:
            if not isinstance(option, dict):
                continue
            value = option.get("downloadUrl")
            if isinstance(value, str) and value:
                return value

    value = data.get("downloadVideoUrl") or data.get("originDownloadVideoUrl")
    return value if isinstance(value, str) and value else None


def looks_like_hls(url: str, content_type: str, body: bytes) -> bool:
    return (
        url.lower().split("?", 1)[0].endswith(".m3u8")
        or content_type in HLS_CONTENT_TYPES
        or body.lstrip().startswith(b"#EXTM3U")
    )


def first_playlist_uri(text: str) -> str | None:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            return line
    return None


def compact_http_error(exc: urllib.error.HTTPError) -> str:
    try:
        detail = exc.read(4096).decode("utf-8", errors="replace")
    except Exception:
        detail = ""
    return f"HTTP {exc.code}: {detail[:500]}"


def read_real_media(url: str, timeout: int) -> tuple[int, str, int, str, int]:
    current = url
    for depth in range(MAX_HLS_DEPTH):
        try:
            status, content_type, body = request_bytes(
                current,
                timeout,
                use_range=depth == 0,
                max_bytes=MAX_PLAYLIST_BYTES if depth > 0 else READ_BYTES,
            )
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"HLS/media depth={depth} {compact_http_error(exc)} url={current[:180]}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"HLS/media depth={depth} {type(exc).__name__}: {exc} url={current[:180]}"
            ) from exc

        if not looks_like_hls(current, content_type, body):
            return status, content_type, len(body), current, depth

        playlist = body.decode("utf-8", errors="replace")
        child = first_playlist_uri(playlist)
        if not child:
            raise RuntimeError(f"HLS playlist depth={depth} has no child media URI")
        current = urllib.parse.urljoin(current, child)

    raise RuntimeError("HLS nesting exceeded smoke-test limit")


def probe_fixture(base_url: str, fixture: Fixture, timeout: int) -> tuple[bool, str]:
    parse_started = time.perf_counter()
    try:
        status, payload = request_json(parse_endpoint(base_url, fixture), timeout)
    except urllib.error.HTTPError as exc:
        return False, f"parse failed after {elapsed_ms(parse_started)}ms: {compact_http_error(exc)}"
    except Exception as exc:
        return False, f"parse failed after {elapsed_ms(parse_started)}ms: {type(exc).__name__}: {exc}"
    parse_ms = elapsed_ms(parse_started)

    if status != 200 or not isinstance(payload, dict) or payload.get("success") is not True:
        return False, f"parse unsuccessful after {parse_ms}ms: HTTP {status} payload={str(payload)[:500]}"

    data = payload.get("data")
    if not isinstance(data, dict):
        return False, f"parse payload has no data object (parse={parse_ms}ms)"

    detected = data.get("platform")
    if detected != fixture.platform:
        return False, f"platform mismatch: expected {fixture.platform}, got {detected!r} (parse={parse_ms}ms)"

    media = first_media_url(data, fixture.media_type)
    if not media:
        return False, f"no {fixture.media_type} URL returned (parse={parse_ms}ms)"
    target = absolute_url(base_url, media)

    media_started = time.perf_counter()
    try:
        media_status, content_type, bytes_read, final_url, hls_depth = read_real_media(target, timeout)
    except Exception as exc:
        return False, (
            f"media failed after {elapsed_ms(media_started)}ms (parse={parse_ms}ms): "
            f"{type(exc).__name__}: {exc}"
        )
    media_ms = elapsed_ms(media_started)

    if media_status not in (200, 206):
        return False, f"media returned HTTP {media_status} (parse={parse_ms}ms media={media_ms}ms depth={hls_depth})"
    if bytes_read <= 0:
        return False, f"media response was empty (parse={parse_ms}ms media={media_ms}ms depth={hls_depth})"
    if "json" in content_type or content_type.startswith("text/"):
        return False, (
            f"final media returned non-media content type {content_type!r} "
            f"(parse={parse_ms}ms media={media_ms}ms depth={hls_depth})"
        )

    return True, (
        f"HTTP {media_status} {content_type or 'unknown'} {bytes_read} bytes "
        f"parse={parse_ms}ms media={media_ms}ms hls_depth={hls_depth} from {final_url[:140]}"
    )


def run_once(base_url: str, timeout: int) -> bool:
    results: dict[str, tuple[bool, str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(FIXTURES)) as pool:
        futures = {
            pool.submit(probe_fixture, base_url, fixture, timeout): fixture
            for fixture in FIXTURES
        }
        for future in concurrent.futures.as_completed(futures):
            fixture = futures[future]
            try:
                results[fixture.platform] = future.result()
            except Exception as exc:
                results[fixture.platform] = (False, f"runner error: {type(exc).__name__}: {exc}")

    all_ok = True
    for fixture in FIXTURES:
        ok, detail = results[fixture.platform]
        print(f"[{'PASS' if ok else 'FAIL'}] {fixture.platform}: {detail}", flush=True)
        all_ok = all_ok and ok
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--retry-delay", type=int, default=15)
    args = parser.parse_args()

    for attempt in range(1, max(1, args.attempts) + 1):
        print(f"\nProduction smoke attempt {attempt}/{args.attempts}: {args.base_url}", flush=True)
        if run_once(args.base_url, args.timeout):
            print("All first-party production media probes passed.", flush=True)
            return 0
        if attempt < args.attempts:
            print(f"Retrying in {args.retry_delay}s for deployment/edge propagation...", flush=True)
            time.sleep(max(0, args.retry_delay))

    print("Production first-party media smoke failed.", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
