#!/usr/bin/env python3
"""Run real platform regression checks against the production Container image.

The script deliberately distinguishes parser success from actual media access:
1. It discovers current single-media fixtures from yt-dlp's extractor tests.
2. It executes ``app.smoke_cli`` inside the production Docker image. That CLI
   parses with the exact image runtime and reads only a small media prefix from
   the same network path.
3. For a passing fixture it also calls the public-compatible /api/parse HTTP
   endpoint to validate the frontend response shape.
4. Separately, it downloads one tiny generic MP4 through /api/download to prove
   the full HTTP download route produces a real media file.

Failures are reported rather than hidden. Anti-bot/cookie/proxy requirements are
expected to remain visible until the corresponding runtime configuration exists.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLATFORM_SMOKE = ROOT / "scripts" / "platform-smoke.py"
OUTPUT_DIR = ROOT / "platform-smoke-artifacts"
CONTAINER = os.getenv("GALAXY_SMOKE_CONTAINER", "galaxy-downloader-live-smoke")
API_BASE = os.getenv("GALAXY_SMOKE_LOCAL_API_BASE", "http://127.0.0.1:8080").rstrip("/")
TIMEOUT = int(os.getenv("GALAXY_SMOKE_TIMEOUT", "110"))
MAX_CANDIDATES = int(os.getenv("GALAXY_SMOKE_MAX_CANDIDATES", "4"))

TARGETS = ("youtube", "weibo", "vimeo", "xiaohongshu", "twitch", "rumble")
MANUAL_FIXTURES: dict[str, list[str]] = {
    "youtube": ["https://www.youtube.com/watch?v=YE7VzlLtp-4&t=1s&end=9"],
    "twitch": ["https://m.twitch.tv/ninja/clip/SuaveNeighborlySrirachaHeyGirl-1J8kzeLFWxdUBZ4C"],
    "weibo": ["https://weibo.com/7827771738/N4xlMvjhI"],
    "vimeo": ["https://player.vimeo.com/video/54469442", "https://vimeo.com/68375962"],
    "rumble": ["https://rumble.com/vdmum1-moose-the-dog-helps-girls-dig-a-snow-fort.html"],
}
TINY_DOWNLOAD_FIXTURE = os.getenv(
    "GALAXY_SMOKE_TINY_DOWNLOAD_URL",
    "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4",
)


def load_fixture_helper():
    spec = importlib.util.spec_from_file_location("platform_smoke_container_live", PLATFORM_SMOKE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load platform-smoke.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def fixture_candidates() -> dict[str, list[str]]:
    smoke = load_fixture_helper()
    discovered = smoke.build_fixture_candidates()
    result: dict[str, list[str]] = {}
    for platform in TARGETS:
        urls = list(MANUAL_FIXTURES.get(platform, []))
        for candidate in discovered.get(platform, []):
            url = getattr(candidate, "url", None)
            if isinstance(url, str):
                urls.append(url)
        result[platform] = dedupe(urls)[:MAX_CANDIDATES]
    return result


def run_container_probe(url: str) -> dict[str, Any]:
    command = ["docker", "exec", CONTAINER, "python", "-m", "app.smoke_cli", url]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "url": url, "elapsedMs": round((time.monotonic() - started) * 1000)}

    stdout = (completed.stdout or "").strip().splitlines()
    payload: dict[str, Any] | None = None
    for line in reversed(stdout):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            payload = value
            break

    if payload is None:
        payload = {
            "status": "CLI_ERROR",
            "url": url,
            "error": (completed.stderr or completed.stdout or f"exit {completed.returncode}")[-3000:].strip(),
        }
    payload["exitCode"] = completed.returncode
    payload["elapsedMs"] = round((time.monotonic() - started) * 1000)
    return payload


def get_json(url: str, timeout: int = 90) -> tuple[int, dict[str, Any] | None, str | None]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "GalaxyDownloaderSmoke/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(8 * 1024 * 1024)
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception as exc:
                return getattr(response, "status", 200), None, f"invalid JSON: {exc}"
            return getattr(response, "status", 200), payload if isinstance(payload, dict) else None, None
    except urllib.error.HTTPError as exc:
        body = exc.read(128 * 1024).decode("utf-8", errors="replace")
        return exc.code, None, body[-3000:]
    except Exception as exc:
        return 0, None, f"{type(exc).__name__}: {exc}"


def api_parse_probe(url: str) -> dict[str, Any]:
    endpoint = f"{API_BASE}/api/parse?{urllib.parse.urlencode({'url': url})}"
    status, payload, error = get_json(endpoint, timeout=TIMEOUT)
    if not payload or not payload.get("success") or not isinstance(payload.get("data"), dict):
        return {"ok": False, "status": status, "error": error or payload}
    data = payload["data"]
    quality_options = data.get("qualityOptions") if isinstance(data.get("qualityOptions"), list) else []
    subtitles = data.get("subtitles") if isinstance(data.get("subtitles"), list) else []
    return {
        "ok": True,
        "status": status,
        "platform": data.get("platform"),
        "kind": data.get("kind"),
        "videoAudioMode": data.get("videoAudioMode"),
        "qualityCount": len(quality_options),
        "subtitleCount": len(subtitles),
        "hasVideoUrl": bool(data.get("downloadVideoUrl")),
        "hasAudioUrl": bool(data.get("downloadAudioUrl")),
    }


def tiny_download_probe() -> dict[str, Any]:
    endpoint = f"{API_BASE}/api/download?{urllib.parse.urlencode({'url': TINY_DOWNLOAD_FIXTURE, 'type': 'video', 'quality': 'best'})}"
    started = time.monotonic()
    request = urllib.request.Request(endpoint, headers={"User-Agent": "GalaxyDownloaderSmoke/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read(8 * 1024 * 1024)
            content_type = response.headers.get("content-type", "")
            return {
                "ok": getattr(response, "status", 200) in {200, 206} and len(body) > 1024 and not content_type.startswith("application/json"),
                "status": getattr(response, "status", 200),
                "bytes": len(body),
                "contentType": content_type,
                "contentDisposition": response.headers.get("content-disposition"),
                "elapsedMs": round((time.monotonic() - started) * 1000),
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status": exc.code,
            "error": exc.read(64 * 1024).decode("utf-8", errors="replace")[-2000:],
            "elapsedMs": round((time.monotonic() - started) * 1000),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsedMs": round((time.monotonic() - started) * 1000),
        }


def summarize_status(attempts: list[dict[str, Any]]) -> str:
    if any(item.get("status") == "PASS" for item in attempts):
        return "PASS"
    if any(item.get("status") == "MEDIA_FAIL" for item in attempts):
        return "MEDIA_FAIL"
    if any(item.get("status") not in {"PARSE_FAIL", "TIMEOUT", "CLI_ERROR"} for item in attempts):
        return "PARTIAL"
    return "PARSE_FAIL"


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Galaxy Downloader Container live smoke",
        "",
        "This report runs inside the production Docker image. `PASS` means yt-dlp parsed the fixture and the same container read real media bytes from the selected CDN stream.",
        "",
        "| Platform | Status | Extractor | Formats | Media bytes | API shape | Notes |",
        "| --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for platform in TARGETS:
        item = report.get("platforms", {}).get(platform, {})
        selected = item.get("selected") or {}
        bytes_read = max(
            int((selected.get("videoProbe") or {}).get("bytes") or 0),
            int((selected.get("audioProbe") or {}).get("bytes") or 0),
        )
        api_ok = "✅" if (item.get("apiParse") or {}).get("ok") else "❌"
        note = str(selected.get("error") or "")[:180].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {platform} | **{item.get('status', 'NO_FIXTURE')}** | {selected.get('extractor') or '—'} | {selected.get('formatCount') or 0} | {bytes_read} | {api_ok} | {note or '—'} |"
        )
    download = report.get("downloadE2E", {})
    lines.extend([
        "",
        "## Full HTTP download route",
        "",
        f"Tiny generic media: **{'PASS' if download.get('ok') else 'FAIL'}** · HTTP `{download.get('status', '—')}` · `{download.get('bytes', 0)}` bytes · `{download.get('contentType', '—')}`.",
        "",
        "> YouTube, Rumble, Vimeo and similar anti-bot services may still require cookies, browser impersonation or a proxy. This report intentionally leaves those failures visible instead of treating parser metadata as a successful download.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fixtures = fixture_candidates()
    report: dict[str, Any] = {
        "container": CONTAINER,
        "apiBase": API_BASE,
        "runtime": {
            "cookiesConfigured": bool(os.getenv("YTDLP_COOKIES_B64", "").strip()),
            "proxyConfigured": bool(os.getenv("YTDLP_PROXY", "").strip()),
            "impersonation": os.getenv("YTDLP_IMPERSONATE", "chrome"),
        },
        "platforms": {},
    }

    for platform in TARGETS:
        attempts: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        for candidate in fixtures.get(platform, []):
            result = run_container_probe(candidate)
            attempts.append(result)
            print(f"[{result.get('status', 'UNKNOWN'):10}] {platform:12} {candidate}")
            if result.get("status") == "PASS":
                selected = result
                break
            if selected is None and result.get("status") == "MEDIA_FAIL":
                selected = result
        if selected is None and attempts:
            selected = attempts[-1]

        status = summarize_status(attempts) if attempts else "NO_FIXTURE"
        api_parse = api_parse_probe(selected["url"]) if selected and selected.get("status") == "PASS" else {"ok": False, "skipped": True}
        if status == "PASS" and not api_parse.get("ok"):
            status = "PARTIAL"
        report["platforms"][platform] = {
            "status": status,
            "selected": selected,
            "apiParse": api_parse,
            "attempts": attempts,
        }

    report["downloadE2E"] = tiny_download_probe()
    print("[DOWNLOAD-E2E]", json.dumps(report["downloadE2E"], ensure_ascii=False))

    json_path = OUTPUT_DIR / "container-live-smoke.json"
    md_path = OUTPUT_DIR / "container-live-smoke.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(md_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
