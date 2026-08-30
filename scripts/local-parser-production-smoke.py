#!/usr/bin/env python3
"""Probe Galaxy's deployed first-party parsers and read real media bytes."""

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
USER_AGENT = "GalaxyDownloaderProductionSmoke/1.1 (+GitHub Actions)"


@dataclass(frozen=True)
class Fixture:
    platform: str
    url: str
    media_type: str


FIXTURES = (
    Fixture(
        "vimeo",
        "https://player.vimeo.com/video/54469442",
        "video",
    ),
    Fixture(
        "dailymotion",
        "https://www.dailymotion.com/video/x5kesuj",
        "video",
    ),
    Fixture(
        "apple_podcasts",
        "https://podcasts.apple.com/us/podcast/urbana-podcast-724-by-david-penn/id1531349107?i=1000748574256",
        "audio",
    ),
)


def request_json(url: str, timeout: int) -> tuple[int, dict[str, str], Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(4 * 1024 * 1024)
        headers = {key.lower(): value for key, value in response.headers.items()}
        return int(getattr(response, "status", 200)), headers, json.loads(body.decode("utf-8"))


def read_prefix(url: str, timeout: int) -> tuple[int, str, int]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "*/*",
            "Range": f"bytes=0-{READ_BYTES - 1}",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(READ_BYTES)
        return (
            int(getattr(response, "status", 200)),
            response.headers.get("content-type", "").split(";", 1)[0].strip().lower(),
            len(body),
        )


def parse_endpoint(base_url: str, source_url: str) -> str:
    query = urllib.parse.urlencode({"url": source_url})
    return f"{base_url.rstrip('/')}/api/local-parse?{query}"


def absolute_media_url(base_url: str, value: str) -> str:
    return urllib.parse.urljoin(f"{base_url.rstrip('/')}/", value)


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


def probe_fixture(base_url: str, fixture: Fixture, timeout: int) -> tuple[bool, str]:
    try:
        status, _headers, payload = request_json(parse_endpoint(base_url, fixture.url), timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        return False, f"parse HTTP {exc.code}: {detail[:500]}"
    except Exception as exc:
        return False, f"parse error: {type(exc).__name__}: {exc}"

    if status != 200 or not isinstance(payload, dict) or payload.get("success") is not True:
        return False, f"parse unsuccessful: HTTP {status} payload={str(payload)[:500]}"

    data = payload.get("data")
    if not isinstance(data, dict):
        return False, "parse payload has no data object"

    detected = data.get("platform")
    if detected != fixture.platform:
        return False, f"platform mismatch: expected {fixture.platform}, got {detected!r}"

    media = first_media_url(data, fixture.media_type)
    if not media:
        return False, f"no {fixture.media_type} URL returned"

    target = absolute_media_url(base_url, media)
    try:
        media_status, content_type, bytes_read = read_prefix(target, timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        return False, f"media HTTP {exc.code}: {detail[:500]}"
    except Exception as exc:
        return False, f"media error: {type(exc).__name__}: {exc}"

    if media_status not in (200, 206):
        return False, f"media returned HTTP {media_status}"
    if bytes_read <= 0:
        return False, "media response was empty"
    if "json" in content_type or content_type.startswith("text/"):
        return False, f"media returned non-media content type {content_type!r}"

    return True, f"HTTP {media_status} {content_type or 'unknown'} {bytes_read} bytes"


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
            print("All first-party production parser probes passed.", flush=True)
            return 0
        if attempt < args.attempts:
            print(f"Retrying in {args.retry_delay}s to allow deployment/edge propagation...", flush=True)
            time.sleep(max(0, args.retry_delay))

    print("Production first-party parser smoke failed.", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
