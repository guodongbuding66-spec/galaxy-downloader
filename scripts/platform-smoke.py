#!/usr/bin/env python3
"""Live smoke-test Galaxy Downloader's production parser/download pipeline.

The script deliberately reads only a small prefix of media responses. It verifies
that a real upstream URL can be parsed and that the backend can begin serving the
selected media without downloading full copyrighted files during CI.

Fixtures are discovered from yt-dlp's public extractor test cases when possible.
They can be overridden with PLATFORM_SMOKE_FIXTURES_JSON, e.g.
{"youtube":"https://...","wechat":"https://..."}.
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
MAX_HLS_DEPTH = 4

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

MANUAL_DEFAULT_FIXTURES = {
    # Stable public HLS test stream; this exercises the generic/HLS path without
    # depending on a social platform post staying online.
    "generic": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
}


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


def discover_yt_dlp_fixtures() -> tuple[dict[str, str], dict[str, str]]:
    try:
        from yt_dlp.extractor import gen_extractors  # type: ignore
    except Exception as exc:  # pragma: no cover - only happens in missing CI dep
        print(f"warning: yt-dlp fixture discovery unavailable: {exc}", file=sys.stderr)
        return {}, {}

    extractors = list(gen_extractors())
    fixtures: dict[str, str] = {}
    sources: dict[str, str] = {}

    for platform, aliases in PLATFORM_ALIASES.items():
        if platform == "generic":
            continue
        normalized_aliases = tuple(normalize_name(alias) for alias in aliases)
        candidates: list[Any] = []
        for ie in extractors:
            names = [
                str(getattr(ie, "IE_NAME", "")),
                type(ie).__name__,
                str(getattr(ie, "IE_DESC", "")),
            ]
            normalized_names = [normalize_name(name) for name in names]
            if any(alias and any(alias in name for name in normalized_names) for alias in normalized_aliases):
                candidates.append(ie)

        for ie in candidates:
            for testcase in iter_testcases(ie):
                url = testcase.get("url")
                if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                    continue
                if testcase.get("only_matching") or testcase.get("skip"):
                    continue
                fixtures[platform] = url
                sources[platform] = f"yt-dlp:{getattr(ie, 'IE_NAME', type(ie).__name__)}"
                break
            if platform in fixtures:
                break

    return fixtures, sources


def load_fixture_overrides() -> dict[str, str]:
    raw = os.environ.get("PLATFORM_SMOKE_FIXTURES_JSON", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid PLATFORM_SMOKE_FIXTURES_JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("PLATFORM_SMOKE_FIXTURES_JSON must be a JSON object")
    return {
        key: value
        for key, value in parsed.items()
        if key in PLATFORM_ALIASES and isinstance(value, str) and value.startswith(("http://", "https://"))
    }


def build_fixtures() -> tuple[dict[str, str], dict[str, str]]:
    discovered, sources = discover_yt_dlp_fixtures()
    fixtures = {**discovered, **MANUAL_DEFAULT_FIXTURES}
    fixture_sources = {**sources, **{key: "manual-default" for key in MANUAL_DEFAULT_FIXTURES}}
    overrides = load_fixture_overrides()
    fixtures.update(overrides)
    fixture_sources.update({key: "env-override" for key in overrides})
    return fixtures, fixture_sources


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
            "User-Agent": "GalaxyDownloaderPlatformSmoke/1.0 (+GitHub Actions)",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        headers = {key.lower(): value for key, value in response.headers.items()}
        data = read_prefix(response)
        final_url = response.geturl()
        return int(getattr(response, "status", 200)), headers, data, final_url


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
            playlist = data.decode("utf-8", errors="replace")
            resource = first_hls_resource(playlist, final_url)
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
        status, headers, data, _ = request_prefix(endpoint, timeout, "application/json")
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        payload = decode_json_prefix(data)
        if status not in (200, 206) or not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), dict):
            message = payload.get("error") or payload.get("message") if isinstance(payload, dict) else None
            return ProbeResult(False, status, content_type, len(data), "json", str(message or "parse returned unsuccessful payload")), payload if isinstance(payload, dict) else None
        return ProbeResult(True, status, content_type, len(data), "json"), payload
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = read_prefix(exc, 4096)
        except Exception:
            pass
        return ProbeResult(False, exc.code, exc.headers.get_content_type() if exc.headers else None, len(body), "http", body.decode("utf-8", errors="replace")[:500] or str(exc)), None
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


def run_platform(platform: str, fixture_url: str | None, fixture_source: str | None, api_base: str, timeout: int) -> PlatformResult:
    started = time.monotonic()
    result = PlatformResult(platform=platform, fixture_url=fixture_url, fixture_source=fixture_source)
    if not fixture_url:
        result.parse = ProbeResult(False, kind="fixture", error="no stable live fixture discovered; provide PLATFORM_SMOKE_FIXTURES_JSON")
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    parse_probe, payload = parse_source(api_base, fixture_url, timeout)
    result.parse = parse_probe
    if not parse_probe.ok or not payload or not isinstance(payload.get("data"), dict):
        result.status = "FAIL"
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

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
        result.video = probe_media_url(source_download_url(api_base, fixture_url, "video"), timeout)
        if not result.video.ok:
            # Some custom backends only expose the parsed stream URL. Probe that
            # too before declaring the platform broken.
            fallback = data.get("downloadVideoUrl") or data.get("originDownloadVideoUrl")
            if isinstance(fallback, str) and fallback.startswith(("http://", "https://")):
                fallback_probe = probe_media_url(fallback, timeout)
                if fallback_probe.ok:
                    result.video = fallback_probe
                    result.diagnostics.append("source-aware video endpoint failed but parsed video stream is reachable")
            if not result.video.ok:
                primary_failures.append("video")

    if should_expect_audio(data):
        result.audio = probe_media_url(source_download_url(api_base, fixture_url, "audio"), timeout)
        if not result.audio.ok:
            fallback = data.get("downloadAudioUrl") or data.get("originDownloadAudioUrl")
            if isinstance(fallback, str) and fallback.startswith(("http://", "https://")):
                fallback_probe = probe_media_url(fallback, timeout)
                if fallback_probe.ok:
                    result.audio = fallback_probe
                    result.diagnostics.append("source-aware audio endpoint failed but parsed audio stream is reachable")
            # A muxed video legitimately may not expose a dedicated audio URL.
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
    summary = {
        key: sum(1 for item in results if item.status == key)
        for key in ("PASS", "PARTIAL", "FAIL", "SKIP")
    }
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
        "> A PASS means the production API parsed the live fixture and CI could read a real media prefix. It is a strong smoke signal, not a mathematical guarantee that every post/account/region will download forever.",
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
    parser.add_argument("--workers", type=int, default=int(os.environ.get("PLATFORM_SMOKE_WORKERS", "4")))
    parser.add_argument("--output-dir", default="platform-smoke-artifacts")
    parser.add_argument("--strict", action="store_true", help="exit non-zero when any platform FAILs")
    args = parser.parse_args()

    fixtures, sources = build_fixtures()
    platforms = list(PLATFORM_ALIASES)
    print(f"Testing {len(platforms)} registered platforms against {args.api_base}")
    print(f"Discovered live fixtures for {len(fixtures)}/{len(platforms)} platforms")

    results_by_platform: dict[str, PlatformResult] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(run_platform, platform, fixtures.get(platform), sources.get(platform), args.api_base, args.timeout): platform
            for platform in platforms
        }
        for future in concurrent.futures.as_completed(futures):
            platform = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # keep the matrix running even if one worker crashes
                result = PlatformResult(platform=platform, fixture_url=fixtures.get(platform), fixture_source=sources.get(platform), status="FAIL")
                result.parse = ProbeResult(False, kind="runner", error=f"{type(exc).__name__}: {exc}")
            results_by_platform[platform] = result
            print(f"[{result.status:7}] {platform:14} parse={probe_cell(result.parse)} video={probe_cell(result.video)} audio={probe_cell(result.audio)}")

    results = [results_by_platform[platform] for platform in platforms]
    write_reports(results, Path(args.output_dir), args.api_base)

    counts = {key: sum(1 for item in results if item.status == key) for key in ("PASS", "PARTIAL", "FAIL", "SKIP")}
    print("Summary:", counts)
    if args.strict and counts["FAIL"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
