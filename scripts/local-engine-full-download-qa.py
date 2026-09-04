#!/usr/bin/env python3
"""End-to-end download QA for Galaxy Local Engine's 33-platform catalog.

Unlike the lightweight smoke tests, this runner asks the same yt-dlp executable
installed by Galaxy Local Engine to download a COMPLETE small public fixture.
A platform only receives PASS_FULL after a non-empty final file is present and
ffprobe/file validation succeeds. Environment/session failures are classified
separately so cloud-runner blocks are never reported as product passes.

WeChat Channels is intentionally classified AUTH_REQUIRED in cloud CI because
Galaxy v0.4.6+ uses the native Yuanbao/browser-session path instead of yt-dlp.
That path requires a real local browser login and must be verified on a Windows
machine with an authenticated Yuanbao session.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

EXPECTED_PLATFORM_COUNT = 33
DEFAULT_TIMEOUT = 150
DEFAULT_WORKERS = 3
DEFAULT_MAX_CANDIDATES = 3
DEFAULT_MAX_FILE_MB = 120

PASS_FULL = "PASS_FULL"
AUTH_REQUIRED = "AUTH_REQUIRED"
CLOUD_IP_BLOCKED = "CLOUD_IP_BLOCKED"
GEO_RESTRICTED = "GEO_RESTRICTED"
FIXTURE_DEAD = "FIXTURE_DEAD"
TOO_LARGE = "TOO_LARGE"
NO_FIXTURE = "NO_FIXTURE"
NO_EXTRACTOR = "NO_EXTRACTOR"
TIMEOUT = "TIMEOUT"
FAIL = "FAIL"

# Stable compact fallbacks used before yt-dlp's own extractor fixtures.
# Keep these public and non-paywalled. The normal PLATFORM_SMOKE_FIXTURES_JSON
# secret still takes highest priority through platform-smoke.py.
MANUAL_FULL_FIXTURES: dict[str, list[str]] = {
    "generic": ["https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4"],
    "threads": ["https://www.threads.net/t/CuXnwmrMIZL"],
    "wechat": ["https://weixin.qq.com/sph/Axv548mzBF"],
    "kuaishou": ["https://www.kuaishou.com/f/X3t3Ee6o1L7gqHe"],
}

COOKIE_PATTERNS = (
    r"cookies?", r"sign[ -]?in", r"log[ -]?in", r"authentication required",
    r"account required", r"members?-only", r"private (?:video|content)",
    r"age[- ]restricted", r"login required",
)
CLOUD_PATTERNS = (
    r"confirm (?:that )?you(?:'re| are) not a bot", r"http error 403",
    r"403 forbidden", r"http error 412", r"412 precondition failed",
    r"http error 429", r"too many requests", r"rate.?limit", r"request blocked",
    r"access denied", r"cloudflare", r"ip(?: address)? (?:has been |is )?blocked",
)
GEO_PATTERNS = (
    r"not available in your country", r"not available (?:from|in) your (?:location|region)",
    r"geo.?restricted", r"geographic restriction",
)
DEAD_PATTERNS = (
    r"http error 404", r"404 not found", r"video (?:is )?unavailable",
    r"content (?:is )?unavailable", r"has been removed", r"has been deleted",
    r"does not exist", r"not found",
)
TOO_LARGE_PATTERNS = (
    r"larger than max-filesize", r"exceeds max-filesize", r"file is larger than",
    r"maximum file size",
)
NO_EXTRACTOR_PATTERNS = (r"unsupported url", r"no suitable extractor", r"unsupported site")


@dataclass
class Attempt:
    url: str
    source: str
    status: str
    elapsed_ms: int
    filename: str | None = None
    size_bytes: int = 0
    duration: float | None = None
    format_name: str | None = None
    streams: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class PlatformResult:
    platform: str
    status: str
    attempts: list[Attempt] = field(default_factory=list)
    selected_url: str | None = None
    selected_source: str | None = None
    filename: str | None = None
    size_bytes: int = 0
    duration: float | None = None
    format_name: str | None = None
    streams: list[str] = field(default_factory=list)
    note: str | None = None


def load_module(filename: str, module_name: str) -> Any:
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def compact(text: str, limit: int = 900) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " | ".join(lines[-8:])[:limit] or "unknown failure"


def has(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def classify(text: str, timed_out: bool = False) -> str:
    if timed_out:
        return TIMEOUT
    if has(text, TOO_LARGE_PATTERNS):
        return TOO_LARGE
    if has(text, COOKIE_PATTERNS):
        return AUTH_REQUIRED
    if has(text, CLOUD_PATTERNS):
        return CLOUD_IP_BLOCKED
    if has(text, GEO_PATTERNS):
        return GEO_RESTRICTED
    if has(text, DEAD_PATTERNS):
        return FIXTURE_DEAD
    if has(text, NO_EXTRACTOR_PATTERNS):
        return NO_EXTRACTOR
    return FAIL


def candidate_list(platform_smoke: Any, platform: str, discovered: dict[str, list[Any]], limit: int) -> list[Any]:
    items: list[Any] = []
    fixture_type = platform_smoke.FixtureCandidate
    # Environment/secret overrides were already injected by build_fixture_candidates.
    items.extend(discovered.get(platform, []))
    # Add compact QA-specific fallbacks without replacing higher-priority overrides.
    existing = {item.url for item in items}
    for url in MANUAL_FULL_FIXTURES.get(platform, []):
        if url not in existing:
            items.insert(0, fixture_type(url=url, source="qa-manual", rank=-30))
            existing.add(url)
    return items[:limit]


def final_files(folder: Path) -> list[Path]:
    ignored_suffixes = {".part", ".ytdl", ".json", ".description", ".vtt", ".srt", ".ass", ".lrc"}
    output: list[Path] = []
    for path in folder.rglob("*"):
        if not path.is_file() or path.suffix.lower() in ignored_suffixes:
            continue
        if path.name.endswith(".info.json"):
            continue
        output.append(path)
    return sorted(output, key=lambda p: p.stat().st_size, reverse=True)


def ffprobe_validate(path: Path, ffprobe: str) -> tuple[bool, float | None, str | None, list[str], str | None]:
    cmd = [
        ffprobe, "-v", "error", "-show_entries",
        "format=duration,format_name,size:stream=codec_type,codec_name",
        "-of", "json", str(path),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
    if completed.returncode != 0:
        return False, None, None, [], compact(completed.stderr or completed.stdout)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return False, None, None, [], f"ffprobe JSON decode failed: {exc}"
    fmt = payload.get("format") if isinstance(payload, dict) else {}
    streams_raw = payload.get("streams") if isinstance(payload, dict) else []
    duration = None
    try:
        raw = (fmt or {}).get("duration")
        if raw not in (None, "N/A"):
            duration = float(raw)
    except (TypeError, ValueError):
        duration = None
    format_name = str((fmt or {}).get("format_name") or "") or None
    streams: list[str] = []
    if isinstance(streams_raw, list):
        for stream in streams_raw:
            if not isinstance(stream, dict):
                continue
            kind = str(stream.get("codec_type") or "unknown")
            codec = str(stream.get("codec_name") or "unknown")
            streams.append(f"{kind}:{codec}")
    # Some image/GIF fixtures have no meaningful duration, but must have a decodable stream.
    valid = path.stat().st_size > 0 and bool(streams)
    return valid, duration, format_name, streams, None if valid else "ffprobe found no decodable stream"


def run_attempt(executable: Path, ffprobe: str, candidate: Any, timeout: int, max_file_mb: int) -> Attempt:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="galaxy-full-qa-") as tmp:
        out_dir = Path(tmp)
        template = str(out_dir / "%(extractor_key)s-%(id)s.%(ext)s")
        command = [
            str(executable),
            "--no-playlist",
            "--no-warnings",
            "--no-colors",
            "--socket-timeout", str(min(timeout, 30)),
            "--retries", "1",
            "--fragment-retries", "1",
            "--extractor-retries", "1",
            "--max-filesize", f"{max_file_mb}M",
            "--format", f"worst[filesize<={max_file_mb}M]/worst[filesize_approx<={max_file_mb}M]/worst",
            "--output", template,
            "--", candidate.url,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            combined = "\n".join(filter(None, [
                exc.stdout if isinstance(exc.stdout, str) else "",
                exc.stderr if isinstance(exc.stderr, str) else "",
            ]))
            return Attempt(candidate.url, candidate.source, TIMEOUT, int((time.monotonic() - started) * 1000), error=compact(combined or "download timed out"))

        files = final_files(out_dir)
        elapsed = int((time.monotonic() - started) * 1000)
        combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        if completed.returncode != 0 or not files:
            return Attempt(candidate.url, candidate.source, classify(combined), elapsed, error=compact(combined))

        selected = files[0]
        ok, duration, format_name, streams, probe_error = ffprobe_validate(selected, ffprobe)
        if not ok:
            return Attempt(
                candidate.url, candidate.source, FAIL, elapsed,
                filename=selected.name, size_bytes=selected.stat().st_size,
                duration=duration, format_name=format_name, streams=streams,
                error=probe_error,
            )
        return Attempt(
            candidate.url, candidate.source, PASS_FULL, elapsed,
            filename=selected.name, size_bytes=selected.stat().st_size,
            duration=duration, format_name=format_name, streams=streams,
        )


def diagnose_platform(executable: Path, ffprobe: str, platform: str, candidates: list[Any], timeout: int, max_file_mb: int) -> PlatformResult:
    if platform == "wechat":
        return PlatformResult(
            platform=platform,
            status=AUTH_REQUIRED,
            selected_url=candidates[0].url if candidates else None,
            selected_source=candidates[0].source if candidates else None,
            note="Galaxy Local Engine v0.4.6+ routes WeChat Channels through native Yuanbao/browser-session resolution. Cloud CI has no user's browser login; real Windows authenticated verification is required.",
        )
    if not candidates:
        return PlatformResult(platform=platform, status=NO_FIXTURE, note="No usable public full-download fixture was discovered.")

    attempts: list[Attempt] = []
    for candidate in candidates:
        attempt = run_attempt(executable, ffprobe, candidate, timeout, max_file_mb)
        attempts.append(attempt)
        if attempt.status == PASS_FULL:
            return PlatformResult(
                platform=platform, status=PASS_FULL, attempts=attempts,
                selected_url=attempt.url, selected_source=attempt.source,
                filename=attempt.filename, size_bytes=attempt.size_bytes,
                duration=attempt.duration, format_name=attempt.format_name,
                streams=attempt.streams,
            )
    # Prefer environment/session classifications over a stale fixture/error.
    priority = {AUTH_REQUIRED: 80, CLOUD_IP_BLOCKED: 70, GEO_RESTRICTED: 65, TOO_LARGE: 60, TIMEOUT: 40, FIXTURE_DEAD: 30, NO_EXTRACTOR: 20, FAIL: 10}
    best = max(attempts, key=lambda item: priority.get(item.status, 0))
    return PlatformResult(
        platform=platform, status=best.status, attempts=attempts,
        selected_url=best.url, selected_source=best.source,
        filename=best.filename, size_bytes=best.size_bytes,
        duration=best.duration, format_name=best.format_name, streams=best.streams,
        note=best.error,
    )


def write_reports(results: list[PlatformResult], output_dir: Path, yt_version: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = dict(Counter(item.status for item in results))
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform_count": len(results),
        "yt_dlp_version": yt_version,
        "summary": summary,
        "results": [asdict(item) for item in results],
    }
    (output_dir / "full-download-qa.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Galaxy Local Engine · 33-platform full-download QA",
        "",
        f"yt-dlp: `{yt_version}`  ",
        f"Platforms: **{len(results)}**  ",
        "",
        "> `PASS_FULL` means a complete public fixture was downloaded to disk and validated by ffprobe. `AUTH_REQUIRED`, `CLOUD_IP_BLOCKED`, and `GEO_RESTRICTED` are not passes and require a real local/session test before release claims.",
        "",
        "## Summary",
        "",
    ]
    for status, count in sorted(summary.items()):
        lines.append(f"- **{status}**: {count}")
    lines += [
        "", "## Matrix", "",
        "| Platform | Status | Size MiB | Duration | Container | Streams | Fixture |",
        "| --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for item in results:
        size = f"{item.size_bytes / 1024 / 1024:.2f}" if item.size_bytes else "—"
        duration = f"{item.duration:.2f}s" if item.duration is not None else "—"
        streams = ", ".join(item.streams) or "—"
        lines.append(f"| {item.platform} | **{item.status}** | {size} | {duration} | {item.format_name or '—'} | {streams} | {item.selected_source or '—'} |")
    lines += ["", "## Non-pass diagnostics", ""]
    for item in results:
        if item.status == PASS_FULL:
            continue
        lines.append(f"### {item.platform} · {item.status}")
        if item.note:
            lines.append(item.note.replace("|", "\\|"))
        for attempt in item.attempts:
            lines.append(f"- `{attempt.source}` · **{attempt.status}** · {attempt.elapsed_ms} ms")
            if attempt.error:
                lines.append(f"  - {attempt.error.replace('|', '\\|')}")
        lines.append("")
    (output_dir / "full-download-qa.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yt-dlp", required=True, type=Path)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--output-dir", default="artifacts/full-download-qa", type=Path)
    parser.add_argument("--timeout", default=DEFAULT_TIMEOUT, type=int)
    parser.add_argument("--workers", default=DEFAULT_WORKERS, type=int)
    parser.add_argument("--max-candidates", default=DEFAULT_MAX_CANDIDATES, type=int)
    parser.add_argument("--max-file-mb", default=DEFAULT_MAX_FILE_MB, type=int)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    executable = args.yt_dlp.resolve()
    if not executable.exists():
        raise SystemExit(f"yt-dlp executable not found: {executable}")
    ffprobe = shutil.which(args.ffprobe) or args.ffprobe
    probe = subprocess.run([ffprobe, "-version"], capture_output=True, text=True, timeout=15, check=False)
    if probe.returncode != 0:
        raise SystemExit("ffprobe is required for full-download validation")
    version_run = subprocess.run([str(executable), "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False)
    yt_version = (version_run.stdout or version_run.stderr).strip().splitlines()[-1]
    if version_run.returncode != 0 or not yt_version:
        raise SystemExit("yt-dlp executable did not report a version")

    platform_smoke = load_module("platform-smoke.py", "galaxy_platform_smoke_full")
    discovered = platform_smoke.build_fixture_candidates()
    platforms = list(platform_smoke.PLATFORM_ALIASES.keys())
    if len(platforms) != EXPECTED_PLATFORM_COUNT:
        raise SystemExit(f"Platform catalog drifted: expected {EXPECTED_PLATFORM_COUNT}, found {len(platforms)}")

    candidates = {p: candidate_list(platform_smoke, p, discovered, max(1, args.max_candidates)) for p in platforms}
    results_by_platform: dict[str, PlatformResult] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(diagnose_platform, executable, ffprobe, p, candidates[p], max(30, args.timeout), max(5, args.max_file_mb)): p
            for p in platforms
        }
        for future in concurrent.futures.as_completed(futures):
            platform = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                result = PlatformResult(platform=platform, status=FAIL, note=f"{type(exc).__name__}: {exc}")
            results_by_platform[platform] = result
            print(f"[{len(results_by_platform):02d}/{len(platforms)}] {platform:14} {result.status}", flush=True)

    results = [results_by_platform[p] for p in platforms]
    write_reports(results, args.output_dir, yt_version)
    summary = Counter(item.status for item in results)
    print("Summary:", dict(summary))
    if args.strict and summary.get(PASS_FULL, 0) != EXPECTED_PLATFORM_COUNT:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
