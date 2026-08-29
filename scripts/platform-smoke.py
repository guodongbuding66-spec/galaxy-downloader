#!/usr/bin/env python3
"""Live smoke-test Galaxy Downloader's production parser/download pipeline.

The runner downloads only a small prefix of media responses. It validates real
production parsing and download startup without pulling entire media files.

Fixtures come from yt-dlp's public extractor tests. For each platform we rank
single-media extractors ahead of collection/channel/search extractors and try a
few candidates until one parses. PLATFORM_SMOKE_FIXTURES_JSON can override or
add stable fixtures, for example:
{"youtube":"https://...","wechat":["https://...","https://..."]}.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

DEFAULT_API_BASE = "https://downloader-api.bhwa233.com"
DEFAULT_TIMEOUT = 30
MAX_PROBE_BYTES = 96 * 1024
MAX_JSON_BYTES = 6 * 1024 * 1024
MAX_HLS_DEPTH = 4
MAX_FIXTURE_CANDIDATES = 4

PLATFORM_ALIASES: dict[str, tuple[str, ...]] = {
    "bilibili": ("bilibili",),
    "douyin": ("douyin",),
    "generic": ("generic",),
    "youtube": ("youtube",),
    "telegram": ("telegram",),
    "threads": ("threads",),
    "wechat": ("wechat", "weixin"),
    "niconico": ("niconico", "nicovideo"),
    "weibo": ("weibo",),
    "xiaohongshu": ("xiaohongshu", "xhs"),
    "tiktok": ("tiktok",),
    "instagram": ("instagram",),
    "x": ("twitter",),
    "vimeo": ("vimeo",),
    "dailymotion": ("dailymotion",),
    "streamable": ("streamable",),
    "reddit": ("reddit",),
    "tumblr": ("tumblr",),
    "pinterest": ("pinterest",),
    "vk": ("vk", "vkontakte"),
    "okru": ("odnoklassniki", "okru"),
    "twitch": ("twitch",),
    "soundcloud": ("soundcloud",),
    "applePodcasts": ("applepodcasts", "applepodcast"),
    "kuaishou": ("kuaishou",),
    "zhihu": ("zhihu",),
    "bluesky": ("bluesky",),
    "rumble": ("rumble",),
    "snapchat": ("snapchat",),
    "coub": ("coub",),
    "imgur": ("imgur",),
    "odysee": ("lbry", "odysee"),
    "rutube": ("rutube",),
}

MANUAL_DEFAULT_FIXTURES: dict[str, list[str]] = {
    "generic": ["https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"],
}

COLLECTION_WORDS = (
    "album", "channel", "collection", "playlist", "search", "user", "profile",
    "feed", "live", "series", "show", "course", "tag", "category", "clips",
)


@dataclass(frozen=True)
class FixtureCandidate:
    url: str
    source: str
    rank: int = 0


@dataclass
class ProbeResult:
    ok: bool
    status: int | None = None
    content_type: str | None = None
    bytes_read: int = 0
    kind: str | None = None
    error: str | None = None


@dataclass
class PlatformResult:
    platform: str
    fixture_url: str | None = None
    fixture_source: str | None = None
    attempted_fixtures: int = 0
    status: str = "SKIP"
    parse: ProbeResult = field(default_factory=lambda: ProbeResult(False, error="not run"))
    video: ProbeResult | None = None
    audio: ProbeResult | None = None
    cover: ProbeResult | None = None
    subtitle: ProbeResult | None = None
    detected_platform: str | None = None
    title: str | None = None
    media_mode: str | None = None
    note_type: str | None = None
    result_kind: str | None = None
    quality_count: int = 0
    subtitle_count: int = 0
    elapsed_ms: int = 0
    diagnostics: list[str] = field(default_factory=list)


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def iter_testcases(extractor: Any) -> Iterable[dict[str, Any]]:
    cls = type(extractor)
    raw = getattr(cls, "_TESTS", None)
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                yield item
    single = getattr(cls, "_TEST", None)
    if isinstance(single, dict):
        yield single


def extractor_rank(extractor: Any, aliases: tuple[str, ...]) -> int | None:
    ie_name = str(getattr(extractor, "IE_NAME", ""))
    class_name = type(extractor).__name__
    desc = str(getattr(extractor, "IE_DESC", ""))
    normalized_aliases = tuple(normalize_name(alias) for alias in aliases)
    normalized_ie = normalize_name(ie_name)
    normalized_class = normalize_name(class_name)
    normalized_desc = normalize_name(desc)

    rank: int | None = None
    for alias in normalized_aliases:
        if not alias:
            continue
        if normalized_ie == alias:
            rank = min(rank if rank is not None else 999, 0)
        elif normalized_ie.startswith(alias):
            rank = min(rank if rank is not None else 999, 2)
        elif normalized_class.startswith(alias):
            rank = min(rank if rank is not None else 999, 3)
        elif alias in normalized_ie:
            rank = min(rank if rank is not None else 999, 5)
        elif alias in normalized_class:
            rank = min(rank if rank is not None else 999, 6)
        elif alias in normalized_desc:
            rank = min(rank if rank is not None else 999, 9)
    if rank is None:
        return None

    lower_name = f"{ie_name} {class_name}".lower()
    if any(word in lower_name for word in COLLECTION_WORDS):
        rank += 20
    return rank


def discover_yt_dlp_candidates() -> dict[str, list[FixtureCandidate]]:
    try:
        from yt_dlp.extractor import gen_extractors  # type: ignore
    except Exception as exc:  # pragma: no cover
        print(f"warning: yt-dlp fixture discovery unavailable: {exc}", file=sys.stderr)
        return {}

    extractors = list(gen_extractors())
    output: dict[str, list[FixtureCandidate]] = {}

    for platform, aliases in PLATFORM_ALIASES.items():
        if platform == "generic":
            continue
        ranked: list[tuple[int, int, Any]] = []
        for ie in extractors:
            rank = extractor_rank(ie, aliases)
            if rank is not None:
                ranked.append((rank, len(str(getattr(ie, "IE_NAME", ""))), ie))
        ranked.sort(key=lambda item: (item[0], item[1]))

        seen: set[str] = set()
        candidates: list[FixtureCandidate] = []
        for rank, _, ie in ranked:
            for testcase in iter_testcases(ie):
                url = testcase.get("url")
                if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                    continue
                if testcase.get("only_matching") or testcase.get("skip") or url in seen:
                    continue
                seen.add(url)
                candidates.append(FixtureCandidate(
                    url=url,
                    source=f"yt-dlp:{getattr(ie, 'IE_NAME', type(ie).__name__)}",
                    rank=rank,
                ))
                if len(candidates) >= MAX_FIXTURE_CANDIDATES:
                    break
            if len(candidates) >= MAX_FIXTURE_CANDIDATES:
                break
        output[platform] = candidates
    return output


def load_fixture_overrides() -> dict[str, list[str]]:
    raw = os.environ.get("PLATFORM_SMOKE_FIXTURES_JSON", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid PLATFORM_SMOKE_FIXTURES_JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("PLATFORM_SMOKE_FIXTURES_JSON must be a JSON object")

    output: dict[str, list[str]] = {}
    for key, value in parsed.items():
        if key not in PLATFORM_ALIASES:
            continue
        values = value if isinstance(value, list) else [value]
        urls = [item for item in values if isinstance(item, str) and item.startswith(("http://", "https://"))]
        if urls:
            output[key] = urls
    return output


def build_fixture_candidates() -> dict[str, list[FixtureCandidate]]:
    discovered = discover_yt_dlp_candidates()
    overrides = load_fixture_overrides()
    output: dict[str, list[FixtureCandidate]] = {}
    for platform in PLATFORM_ALIASES:
        combined: list[FixtureCandidate] = []
        combined.extend(FixtureCandidate(url, "env-override", -20) for url in overrides.get(platform, []))
        combined.extend(FixtureCandidate(url, "manual-default", -10) for url in MANUAL_DEFAULT_FIXTURES.get(platform, []))
        combined.extend(discovered.get(platform, []))
        seen: set[str] = set()
        output[platform] = [
            item for item in sorted(combined, key=lambda item: item.rank)
            if not (item.url in seen or seen.add(item.url))
        ][:MAX_FIXTURE_CANDIDATES]
    return output


def read_prefix(response: Any, limit: int = MAX_PROBE_BYTES) -> bytes:
    chunks: list[bytes] = []
    remaining = limit
    while remaining > 0:
        chunk = response.read(min(16 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def request_prefix(url: str, timeout: int, accept: str = "*/*") -> tuple[int, dict[str, str], bytes, str]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "Range": f"bytes=0-{MAX_PROBE_BYTES - 1}",
            "User-Agent": "GalaxyDownloaderPlatformSmoke/1.1 (+GitHub Actions)",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        headers = {key.lower(): value for key, value in response.headers.items()}
        data = read_prefix(response)
        return int(getattr(response, "status", 200)), headers, data, response.geturl()


def request_json(url: str, timeout: int) -> tuple[int, dict[str, str], Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "GalaxyDownloaderPlatformSmoke/1.1 (+GitHub Actions)",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            raise ValueError(f"JSON response exceeded {MAX_JSON_BYTES} bytes")
        headers = {key.lower(): value for key, value in response.headers.items()}
        return int(getattr(response, "status", 200)), headers, json.loads(data.decode("utf-8", errors="replace"))


def decode_json_prefix(data: bytes) -> Any:
    return json.loads(data.decode("utf-8", errors="replace"))


def extract_resolved_url(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("url", "downloadUrl", "download_url"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    nested = payload.get("data")
    if isinstance(nested, str) and nested.startswith(("http://", "https://")):
        return nested
    if isinstance(nested, dict):
        for key in ("url", "downloadUrl", "download_url"):
            value = nested.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
    return None


def first_hls_resource(playlist: str, playlist_url: str) -> str | None:
    for raw_line in playlist.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        return urllib.parse.urljoin(playlist_url, line)
    return None


def probe_media_url(url: str, timeout: int, depth: int = 0) -> ProbeResult:
    if depth > MAX_HLS_DEPTH:
        return ProbeResult(False, kind="redirect-depth", error="resolver/HLS nesting too deep")
    try:
        status, headers, data, final_url = request_prefix(url, timeout)
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        text_prefix = data[:4096].decode("utf-8", errors="ignore").lstrip()

        if "json" in content_type or text_prefix.startswith("{"):
            try:
                payload = decode_json_prefix(data)
            except Exception as exc:
                return ProbeResult(False, status=status, content_type=content_type, bytes_read=len(data), kind="json", error=f"invalid JSON: {exc}")
            resolved = extract_resolved_url(payload)
            if not resolved:
                success = payload.get("success") if isinstance(payload, dict) else None
                message = payload.get("error") or payload.get("message") if isinstance(payload, dict) else None
                return ProbeResult(False, status=status, content_type=content_type, bytes_read=len(data), kind="json", error=f"resolver returned no URL; success={success}; {message or ''}".strip())
            nested = probe_media_url(resolved, timeout, depth + 1)
            if nested.ok:
                nested.kind = f"resolver→{nested.kind or 'media'}"
            return nested

        looks_hls = (
            "application/vnd.apple.mpegurl" in content_type
            or "application/x-mpegurl" in content_type
            or text_prefix.startswith("#EXTM3U")
            or urllib.parse.urlparse(final_url).path.lower().endswith(".m3u8")
        )
        if looks_hls:
            resource = first_hls_resource(data.decode("utf-8", errors="replace"), final_url)
            if not resource:
                return ProbeResult(False, status=status, content_type=content_type, bytes_read=len(data), kind="hls", error="playlist has no media/variant URI")
            nested = probe_media_url(resource, timeout, depth + 1)
            return ProbeResult(nested.ok, nested.status, nested.content_type, len(data) + nested.bytes_read, "hls", nested.error)

        return ProbeResult(status in (200, 206) and len(data) > 0, status, content_type or None, len(data), "media", None if len(data) else "empty response")
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = read_prefix(exc, 4096)
        except Exception:
            pass
        message = body.decode("utf-8", errors="replace")[:500].strip()
        return ProbeResult(False, exc.code, exc.headers.get_content_type() if exc.headers else None, len(body), "http", message or str(exc))
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        return ProbeResult(False, kind="network", error=str(exc))
    except Exception as exc:
        return ProbeResult(False, kind="exception", error=f"{type(exc).__name__}: {exc}")


def parse_source(api_base: str, source_url: str, timeout: int) -> tuple[ProbeResult, dict[str, Any] | None]:
    endpoint = f"{api_base.rstrip('/')}/api/parse?{urllib.parse.urlencode({'url': source_url})}"
    try:
        status, headers, payload = request_json(endpoint, timeout)
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if status != 200 or not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), dict):
            message = payload.get("error") or payload.get("message") if isinstance(payload, dict) else None
            return ProbeResult(False, status, content_type, 0, "json", str(message or "parse returned unsuccessful payload")), payload if isinstance(payload, dict) else None
        return ProbeResult(True, status, content_type, 0, "json"), payload
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = read_prefix(exc, 8192)
        except Exception:
            pass
        return ProbeResult(False, exc.code, exc.headers.get_content_type() if exc.headers else None, len(body), "http", body.decode("utf-8", errors="replace")[:1200] or str(exc)), None
    except Exception as exc:
        return ProbeResult(False, kind="exception", error=f"{type(exc).__name__}: {exc}"), None


def source_download_url(api_base: str, source_url: str, media_type: str, quality: str = "best") -> str:
    query = urllib.parse.urlencode({"url": source_url, "type": media_type, "quality": quality})
    return f"{api_base.rstrip('/')}/api/download?{query}"


def first_subtitle_url(data: dict[str, Any]) -> str | None:
    tracks = data.get("subtitles")
    if not isinstance(tracks, list):
        return None
    for track in tracks:
        if not isinstance(track, dict):
            continue
        value = track.get("downloadUrl") or track.get("url")
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def should_expect_video(data: dict[str, Any]) -> bool:
    return data.get("kind") != "audio" and data.get("noteType") not in ("audio", "image") and data.get("videoAudioMode") != "pure_music"


def should_expect_audio(data: dict[str, Any]) -> bool:
    if data.get("noteType") == "image" and not (data.get("downloadAudioUrl") or data.get("originDownloadAudioUrl")):
        return False
    return bool(
        data.get("kind") == "audio"
        or data.get("noteType") == "audio"
        or data.get("videoAudioMode") in ("separate", "pure_music")
        or data.get("downloadAudioUrl")
        or data.get("originDownloadAudioUrl")
    )


def choose_parsable_fixture(platform: str, candidates: list[FixtureCandidate], api_base: str, timeout: int) -> tuple[FixtureCandidate | None, ProbeResult, dict[str, Any] | None, list[str]]:
    last_probe = ProbeResult(False, kind="fixture", error="no stable live fixture discovered")
    diagnostics: list[str] = []
    for index, candidate in enumerate(candidates):
        probe, payload = parse_source(api_base, candidate.url, timeout)
        if probe.ok and payload:
            if index > 0:
                diagnostics.append(f"fixture fallback selected after {index} failed candidate(s)")
            return candidate, probe, payload, diagnostics
        last_probe = probe
        detail = probe.error or f"HTTP {probe.status or '?'}"
        diagnostics.append(f"fixture {index + 1} ({candidate.source}) failed: {detail[:260]}")
        time.sleep(0.2)
    return None, last_probe, None, diagnostics


def run_platform(platform: str, candidates: list[FixtureCandidate], api_base: str, timeout: int) -> PlatformResult:
    started = time.monotonic()
    result = PlatformResult(platform=platform, attempted_fixtures=len(candidates))
    if not candidates:
        result.parse = ProbeResult(False, kind="fixture", error="no stable live fixture discovered; provide PLATFORM_SMOKE_FIXTURES_JSON")
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    selected, parse_probe, payload, fixture_diagnostics = choose_parsable_fixture(platform, candidates, api_base, timeout)
    result.parse = parse_probe
    result.diagnostics.extend(fixture_diagnostics)
    if not selected or not payload or not isinstance(payload.get("data"), dict):
        result.fixture_url = candidates[0].url
        result.fixture_source = candidates[0].source
        result.status = "FAIL"
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    result.fixture_url = selected.url
    result.fixture_source = selected.source
    data: dict[str, Any] = payload["data"]
    result.detected_platform = str(data.get("platform") or "") or None
    result.title = str(data.get("title") or data.get("desc") or "")[:160] or None
    result.media_mode = str(data.get("videoAudioMode") or "") or None
    result.note_type = str(data.get("noteType") or "") or None
    result.result_kind = str(data.get("kind") or "") or None
    result.quality_count = len(data.get("qualityOptions") or []) if isinstance(data.get("qualityOptions"), list) else 0
    result.subtitle_count = len(data.get("subtitles") or []) if isinstance(data.get("subtitles"), list) else 0

    primary_failures: list[str] = []
    optional_failures: list[str] = []

    if should_expect_video(data):
        result.video = probe_media_url(source_download_url(api_base, selected.url, "video"), timeout)
        if not result.video.ok:
            fallback = data.get("downloadVideoUrl") or data.get("originDownloadVideoUrl")
            if isinstance(fallback, str) and fallback.startswith(("http://", "https://")):
                fallback_probe = probe_media_url(fallback, timeout)
                if fallback_probe.ok:
                    result.video = fallback_probe
                    result.diagnostics.append("source-aware video endpoint failed but parsed video stream is reachable")
            if not result.video.ok:
                primary_failures.append("video")

    if should_expect_audio(data):
        result.audio = probe_media_url(source_download_url(api_base, selected.url, "audio"), timeout)
        if not result.audio.ok:
            fallback = data.get("downloadAudioUrl") or data.get("originDownloadAudioUrl")
            if isinstance(fallback, str) and fallback.startswith(("http://", "https://")):
                fallback_probe = probe_media_url(fallback, timeout)
                if fallback_probe.ok:
                    result.audio = fallback_probe
                    result.diagnostics.append("source-aware audio endpoint failed but parsed audio stream is reachable")
            if not result.audio.ok and data.get("videoAudioMode") not in ("muxed", "not_applicable"):
                primary_failures.append("audio")

    cover = data.get("cover")
    if isinstance(cover, str) and cover.startswith(("http://", "https://")):
        result.cover = probe_media_url(cover, timeout)
        if not result.cover.ok:
            optional_failures.append("cover")

    subtitle_url = first_subtitle_url(data)
    if subtitle_url:
        result.subtitle = probe_media_url(subtitle_url, timeout)
        if not result.subtitle.ok:
            optional_failures.append("subtitle")

    if primary_failures:
        result.status = "FAIL"
        result.diagnostics.append("primary media probe failed: " + ", ".join(primary_failures))
    elif optional_failures:
        result.status = "PARTIAL"
        result.diagnostics.append("optional resource probe failed: " + ", ".join(optional_failures))
    else:
        result.status = "PASS"

    result.elapsed_ms = int((time.monotonic() - started) * 1000)
    return result


def probe_cell(probe: ProbeResult | None) -> str:
    if probe is None:
        return "—"
    if probe.ok:
        details = probe.kind or "ok"
        if probe.status:
            details += f"/{probe.status}"
        return f"✅ {details}"
    status = f"/{probe.status}" if probe.status else ""
    return f"❌ {probe.kind or 'fail'}{status}"


def write_reports(results: list[PlatformResult], output_dir: Path, api_base: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary = {key: sum(1 for item in results if item.status == key) for key in ("PASS", "PARTIAL", "FAIL", "SKIP")}
    payload = {
        "generatedAt": generated_at,
        "apiBase": api_base,
        "summary": summary,
        "results": [asdict(item) for item in results],
    }
    (output_dir / "platform-smoke.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Galaxy Downloader platform smoke report",
        "",
        f"Generated: `{generated_at}`  ",
        f"API: `{api_base}`  ",
        f"PASS **{summary['PASS']}** · PARTIAL **{summary['PARTIAL']}** · FAIL **{summary['FAIL']}** · SKIP **{summary['SKIP']}**",
        "",
        "> PASS means the production API parsed a live fixture and CI could read a real media prefix. It is a strong smoke signal, not a guarantee that every post/account/region will download forever.",
        "",
        "| Platform | Status | Parse | Video | Audio | Cover | Subtitle | Fixture |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in results:
        fixture = item.fixture_source or "missing"
        lines.append(
            f"| {item.platform} | **{item.status}** | {probe_cell(item.parse)} | {probe_cell(item.video)} | {probe_cell(item.audio)} | {probe_cell(item.cover)} | {probe_cell(item.subtitle)} | {fixture} |"
        )
    lines.extend(["", "## Diagnostics", ""])
    for item in results:
        if item.status in ("FAIL", "PARTIAL", "SKIP") or item.diagnostics:
            detail = "; ".join(item.diagnostics) or item.parse.error or "No fixture"
            lines.append(f"- **{item.platform}** — {detail}")
    (output_dir / "platform-smoke.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default=os.environ.get("PLATFORM_SMOKE_API_BASE", DEFAULT_API_BASE))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("PLATFORM_SMOKE_TIMEOUT", DEFAULT_TIMEOUT)))
    parser.add_argument("--workers", type=int, default=int(os.environ.get("PLATFORM_SMOKE_WORKERS", "2")))
    parser.add_argument("--output-dir", default="platform-smoke-artifacts")
    parser.add_argument("--strict", action="store_true", help="exit non-zero when any platform FAILs")
    args = parser.parse_args()

    candidates = build_fixture_candidates()
    platforms = list(PLATFORM_ALIASES)
    fixture_count = sum(1 for platform in platforms if candidates.get(platform))
    print(f"Testing {len(platforms)} registered platforms against {args.api_base}")
    print(f"Discovered live fixture candidates for {fixture_count}/{len(platforms)} platforms")

    results_by_platform: dict[str, PlatformResult] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(run_platform, platform, candidates.get(platform, []), args.api_base, args.timeout): platform
            for platform in platforms
        }
        for future in concurrent.futures.as_completed(futures):
            platform = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = PlatformResult(platform=platform, status="FAIL")
                result.parse = ProbeResult(False, kind="runner", error=f"{type(exc).__name__}: {exc}")
            results_by_platform[platform] = result
            print(f"[{result.status:7}] {platform:14} parse={probe_cell(result.parse)} video={probe_cell(result.video)} audio={probe_cell(result.audio)} fixture={result.fixture_source or '-'}")

    results = [results_by_platform[platform] for platform in platforms]
    write_reports(results, Path(args.output_dir), args.api_base)

    counts = {key: sum(1 for item in results if item.status == key) for key in ("PASS", "PARTIAL", "FAIL", "SKIP")}
    print("Summary:", counts)
    if args.strict and counts["FAIL"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
