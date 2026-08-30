#!/usr/bin/env python3
"""Diagnose Galaxy Local Engine support across the 33-platform catalog.

This intentionally does not treat every cloud-runner failure as a product failure.
The Local Engine runs on the user's own IP/browser session, while GitHub Actions
runs from a shared cloud address. Results are therefore classified into useful
buckets such as COOKIE_REQUIRED and CLOUD_IP_BLOCKED instead of a misleading
binary PASS/FAIL.

Fixtures and the authoritative platform list are reused from platform-smoke.py,
which discovers public URLs from yt-dlp's own extractor tests.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

EXPECTED_PLATFORM_COUNT = 33
DEFAULT_TIMEOUT = 28
DEFAULT_WORKERS = 5
DEFAULT_MAX_CANDIDATES = 2

STATUS_PASS = "PASS"
STATUS_COOKIE = "COOKIE_REQUIRED"
STATUS_CLOUD = "CLOUD_IP_BLOCKED"
STATUS_GEO = "GEO_RESTRICTED"
STATUS_DEAD = "FIXTURE_DEAD"
STATUS_EXTRACTOR = "EXTRACTOR_ERROR"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_NO_FIXTURE = "NO_FIXTURE"
STATUS_UNKNOWN = "UNKNOWN_FAILURE"

STATUS_PRIORITY = {
    STATUS_PASS: 100,
    STATUS_COOKIE: 90,
    STATUS_CLOUD: 80,
    STATUS_GEO: 75,
    STATUS_TIMEOUT: 40,
    STATUS_DEAD: 30,
    STATUS_EXTRACTOR: 20,
    STATUS_UNKNOWN: 10,
    STATUS_NO_FIXTURE: 0,
}

COOKIE_PATTERNS = (
    r"cookies?",
    r"sign[ -]?in",
    r"log[ -]?in",
    r"authentication required",
    r"account required",
    r"members?-only",
    r"private (?:video|content)",
    r"age[- ]restricted",
)

CLOUD_PATTERNS = (
    r"confirm (?:that )?you(?:'re| are) not a bot",
    r"http error 403",
    r"403 forbidden",
    r"http error 429",
    r"too many requests",
    r"rate.?limit",
    r"request blocked",
    r"access denied",
    r"cloudflare",
    r"ip(?: address)? (?:has been |is )?blocked",
)

GEO_PATTERNS = (
    r"not available in your country",
    r"not available (?:from|in) your (?:location|region)",
    r"geo.?restricted",
    r"geographic restriction",
)

DEAD_PATTERNS = (
    r"http error 404",
    r"404 not found",
    r"video (?:is )?unavailable",
    r"content (?:is )?unavailable",
    r"has been removed",
    r"has been deleted",
    r"does not exist",
    r"not found",
)

EXTRACTOR_PATTERNS = (
    r"unsupported url",
    r"no suitable extractor",
    r"unsupported site",
)


@dataclass
class Attempt:
    fixture_url: str
    fixture_source: str
    status: str
    elapsed_ms: int
    extractor: str | None = None
    title: str | None = None
    format_count: int = 0
    error: str | None = None


@dataclass
class PlatformDiagnostic:
    platform: str
    status: str = STATUS_NO_FIXTURE
    extractor: str | None = None
    title: str | None = None
    format_count: int = 0
    fixture_url: str | None = None
    fixture_source: str | None = None
    attempts: list[Attempt] = field(default_factory=list)
    note: str | None = None


def load_platform_smoke() -> Any:
    path = Path(__file__).with_name("platform-smoke.py")
    spec = importlib.util.spec_from_file_location("galaxy_platform_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def has_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def classify_failure(text: str, *, timed_out: bool = False) -> str:
    if timed_out:
        return STATUS_TIMEOUT
    if has_pattern(text, COOKIE_PATTERNS):
        return STATUS_COOKIE
    if has_pattern(text, CLOUD_PATTERNS):
        return STATUS_CLOUD
    if has_pattern(text, GEO_PATTERNS):
        return STATUS_GEO
    if has_pattern(text, DEAD_PATTERNS):
        return STATUS_DEAD
    if has_pattern(text, EXTRACTOR_PATTERNS):
        return STATUS_EXTRACTOR
    return STATUS_UNKNOWN


def compact_error(value: str, limit: int = 600) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return "unknown yt-dlp failure"
    selected = " | ".join(lines[-5:])
    return selected[:limit]


def extract_json(stdout: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    text = stdout.strip()
    if not text:
        return None

    # yt-dlp normally emits exactly one JSON object with --dump-single-json.
    # Search from every opening brace as a defensive fallback for incidental
    # informational lines emitted by an extractor.
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def probe_fixture(executable: Path, candidate: Any, timeout: int) -> Attempt:
    started = time.monotonic()
    command = [
        str(executable),
        "--simulate",
        "--dump-single-json",
        "--no-playlist",
        "--no-warnings",
        "--no-colors",
        "--socket-timeout", str(min(timeout, 20)),
        "--retries", "1",
        "--fragment-retries", "1",
        "--extractor-retries", "1",
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
        return Attempt(
            fixture_url=candidate.url,
            fixture_source=candidate.source,
            status=STATUS_TIMEOUT,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error=compact_error(combined or f"timed out after {timeout}s"),
        )

    elapsed = int((time.monotonic() - started) * 1000)
    payload = extract_json(completed.stdout)
    if completed.returncode == 0 and payload is not None:
        formats = payload.get("formats")
        direct_url = payload.get("url")
        entries = payload.get("entries")
        format_count = len(formats) if isinstance(formats, list) else 0
        usable = format_count > 0 or isinstance(direct_url, str) or isinstance(entries, list)
        if usable:
            return Attempt(
                fixture_url=candidate.url,
                fixture_source=candidate.source,
                status=STATUS_PASS,
                elapsed_ms=elapsed,
                extractor=str(payload.get("extractor_key") or payload.get("extractor") or "") or None,
                title=str(payload.get("title") or "")[:180] or None,
                format_count=format_count,
            )

    combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return Attempt(
        fixture_url=candidate.url,
        fixture_source=candidate.source,
        status=classify_failure(combined),
        elapsed_ms=elapsed,
        error=compact_error(combined),
    )


def diagnose_platform(
    executable: Path,
    platform: str,
    candidates: list[Any],
    *,
    timeout: int,
    max_candidates: int,
) -> PlatformDiagnostic:
    if not candidates:
        return PlatformDiagnostic(
            platform=platform,
            status=STATUS_NO_FIXTURE,
            note="yt-dlp currently exposes no usable public test fixture for this platform",
        )

    attempts: list[Attempt] = []
    for candidate in candidates[:max_candidates]:
        attempt = probe_fixture(executable, candidate, timeout)
        attempts.append(attempt)
        if attempt.status == STATUS_PASS:
            return PlatformDiagnostic(
                platform=platform,
                status=STATUS_PASS,
                extractor=attempt.extractor,
                title=attempt.title,
                format_count=attempt.format_count,
                fixture_url=attempt.fixture_url,
                fixture_source=attempt.fixture_source,
                attempts=attempts,
            )

    best = max(attempts, key=lambda item: STATUS_PRIORITY.get(item.status, 0))
    note = None
    if best.status in {STATUS_COOKIE, STATUS_CLOUD, STATUS_GEO}:
        note = "Extractor reached the platform, but this cloud-runner result is environment/session dependent and does not prove a user-local failure."
    elif best.status == STATUS_DEAD:
        note = "The public fixture appears stale; replace the fixture before judging platform support."
    elif best.status == STATUS_EXTRACTOR:
        note = "yt-dlp did not route the fixture to a supported extractor."

    return PlatformDiagnostic(
        platform=platform,
        status=best.status,
        extractor=best.extractor,
        title=best.title,
        format_count=best.format_count,
        fixture_url=best.fixture_url,
        fixture_source=best.fixture_source,
        attempts=attempts,
        note=note,
    )


def write_markdown(path: Path, results: list[PlatformDiagnostic], version: str) -> None:
    counts = Counter(item.status for item in results)
    lines = [
        "# Galaxy Local Engine · 33-platform diagnostic",
        "",
        f"yt-dlp: `{version}`",
        f"Platforms: **{len(results)}**",
        "",
        "> `COOKIE_REQUIRED`, `CLOUD_IP_BLOCKED` and `GEO_RESTRICTED` mean the extractor reached the platform but the GitHub cloud runner could not complete the session. They must not be reported as proof that the user-local engine is broken.",
        "",
        "## Summary",
        "",
    ]
    for status, count in sorted(counts.items(), key=lambda item: (-STATUS_PRIORITY.get(item[0], 0), item[0])):
        lines.append(f"- **{status}**: {count}")

    lines.extend([
        "",
        "## Matrix",
        "",
        "| Platform | Status | Extractor | Formats | Fixture source |",
        "| --- | --- | --- | ---: | --- |",
    ])
    for item in results:
        lines.append(
            f"| {item.platform} | **{item.status}** | {item.extractor or '—'} | {item.format_count} | {item.fixture_source or '—'} |"
        )

    lines.extend(["", "## Diagnostics", ""])
    for item in results:
        if item.status == STATUS_PASS:
            continue
        lines.append(f"### {item.platform} · {item.status}")
        if item.note:
            lines.append(item.note)
        for attempt in item.attempts:
            lines.append(f"- `{attempt.fixture_source}` · {attempt.elapsed_ms} ms · **{attempt.status}**")
            if attempt.error:
                lines.append(f"  - {attempt.error.replace('|', '\\|')}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yt-dlp", required=True, type=Path)
    parser.add_argument("--json", default="artifacts/local-engine-platform-diagnostic.json", type=Path)
    parser.add_argument("--markdown", default="artifacts/local-engine-platform-diagnostic.md", type=Path)
    parser.add_argument("--workers", default=DEFAULT_WORKERS, type=int)
    parser.add_argument("--timeout", default=DEFAULT_TIMEOUT, type=int)
    parser.add_argument("--max-candidates", default=DEFAULT_MAX_CANDIDATES, type=int)
    args = parser.parse_args()

    executable = args.yt_dlp.resolve()
    if not executable.exists():
        raise SystemExit(f"yt-dlp executable not found: {executable}")

    version_run = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )
    version = (version_run.stdout or version_run.stderr).strip().splitlines()[-1]
    if version_run.returncode != 0 or not version:
        raise SystemExit("yt-dlp executable did not report a version")

    platform_smoke = load_platform_smoke()
    candidates_by_platform = platform_smoke.build_fixture_candidates()
    platforms = list(platform_smoke.PLATFORM_ALIASES.keys())
    if len(platforms) != EXPECTED_PLATFORM_COUNT:
        raise SystemExit(
            f"Platform catalog drifted: expected {EXPECTED_PLATFORM_COUNT}, found {len(platforms)}"
        )

    results_by_platform: dict[str, PlatformDiagnostic] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        future_map = {
            pool.submit(
                diagnose_platform,
                executable,
                platform,
                candidates_by_platform.get(platform, []),
                timeout=max(8, args.timeout),
                max_candidates=max(1, args.max_candidates),
            ): platform
            for platform in platforms
        }
        for future in concurrent.futures.as_completed(future_map):
            platform = future_map[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                result = PlatformDiagnostic(platform=platform, status=STATUS_UNKNOWN, note=str(exc))
            results_by_platform[platform] = result
            print(f"[{len(results_by_platform):02d}/{len(platforms)}] {platform}: {result.status}", flush=True)

    results = [results_by_platform[platform] for platform in platforms]
    payload = {
        "yt_dlp_version": version,
        "platform_count": len(results),
        "summary": dict(Counter(item.status for item in results)),
        "results": [asdict(item) for item in results],
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(args.markdown, results, version)

    print("\nSummary:")
    for status, count in sorted(payload["summary"].items()):
        print(f"  {status}: {count}")
    print(f"JSON: {args.json}")
    print(f"Markdown: {args.markdown}")

    # This workflow is diagnostic. Platform/network/session statuses are data,
    # not a CI failure. Infrastructure/catalog drift still exits non-zero above.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
