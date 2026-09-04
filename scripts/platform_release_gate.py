#!/usr/bin/env python3
"""Hard release gate for Galaxy Downloader's 33-platform production smoke.

The scheduled platform smoke remains diagnostic. This wrapper is intentionally
strict: a release candidate passes only when every registered platform reports
PASS from a real production parse plus media-prefix probe. PARTIAL, FAIL, SKIP,
missing/duplicate rows, or a failed Vimeo/Dailymotion row all block release.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = ROOT / "scripts" / "platform-smoke.py"
EXPECTED_PLATFORM_COUNT = 33
CRITICAL_PLATFORMS = {"vimeo", "dailymotion"}


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("galaxy_platform_smoke", SMOKE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load platform smoke contract")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def expected_platforms() -> tuple[str, ...]:
    module = _load_smoke_module()
    platforms = tuple(str(item) for item in module.PLATFORM_ALIASES)
    if len(platforms) != EXPECTED_PLATFORM_COUNT or len(set(platforms)) != EXPECTED_PLATFORM_COUNT:
        raise RuntimeError(
            f"platform registry must contain exactly {EXPECTED_PLATFORM_COUNT} unique entries; got {len(platforms)}"
        )
    if not CRITICAL_PLATFORMS.issubset(platforms):
        raise RuntimeError("platform registry is missing Vimeo or Dailymotion")
    return platforms


def evaluate_report(payload: Any, platforms: Iterable[str] | None = None) -> list[str]:
    expected = tuple(platforms or expected_platforms())
    expected_set = set(expected)
    problems: list[str] = []
    if not isinstance(payload, dict):
        return ["report root is not an object"]
    rows = payload.get("results")
    if not isinstance(rows, list):
        return ["report does not contain a results array"]

    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            problems.append("report contains a non-object platform row")
            continue
        platform = str(row.get("platform") or "").strip()
        if not platform:
            problems.append("report contains a row without platform id")
            continue
        if platform in seen:
            problems.append(f"duplicate platform row: {platform}")
            continue
        seen[platform] = row

    missing = [item for item in expected if item not in seen]
    extra = sorted(set(seen) - expected_set)
    if missing:
        problems.append("missing platform rows: " + ", ".join(missing))
    if extra:
        problems.append("unexpected platform rows: " + ", ".join(extra))
    if len(seen) != EXPECTED_PLATFORM_COUNT:
        problems.append(f"expected {EXPECTED_PLATFORM_COUNT} unique platform rows; got {len(seen)}")

    for platform in expected:
        row = seen.get(platform)
        if row is None:
            continue
        status = str(row.get("status") or "").upper()
        if status != "PASS":
            problems.append(f"{platform}: status={status or 'MISSING'}")
            continue
        parse = row.get("parse")
        if not isinstance(parse, dict) or parse.get("ok") is not True:
            problems.append(f"{platform}: PASS row does not contain a successful production parse")
        fixture_url = str(row.get("fixture_url") or row.get("fixtureUrl") or "").strip()
        if not fixture_url.startswith(("http://", "https://")):
            problems.append(f"{platform}: PASS row has no live HTTP(S) fixture")

        # PASS is produced by platform-smoke.py only after expected primary media
        # probes succeed. Require at least one positive media/resource probe too,
        # preventing a malformed hand-written report from bypassing the gate.
        probe_keys = ("video", "audio", "cover", "subtitle")
        positive_probe = any(
            isinstance(row.get(key), dict) and row[key].get("ok") is True
            for key in probe_keys
        )
        if not positive_probe:
            problems.append(f"{platform}: PASS row has no successful real resource probe")

    for critical in sorted(CRITICAL_PLATFORMS):
        if critical not in seen or str(seen[critical].get("status") or "").upper() != "PASS":
            problems.append(f"critical platform did not pass: {critical}")
    return problems


def run_live_gate(
    *,
    api_base: str,
    timeout: int,
    workers: int,
    output_dir: Path,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(SMOKE_SCRIPT),
        "--api-base",
        api_base,
        "--timeout",
        str(timeout),
        "--workers",
        str(workers),
        "--output-dir",
        str(output_dir),
    ]
    completed = subprocess.run(command, cwd=ROOT, check=False)
    report_path = output_dir / "platform-smoke.json"
    if completed.returncode != 0:
        print(f"platform smoke runner exited with {completed.returncode}", file=sys.stderr)
        return completed.returncode or 1
    if not report_path.is_file():
        print("platform smoke did not produce platform-smoke.json", file=sys.stderr)
        return 1
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"could not read platform smoke report: {exc}", file=sys.stderr)
        return 1

    problems = evaluate_report(payload)
    if problems:
        print("33-platform release gate FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print(f"33-platform release gate PASSED ({EXPECTED_PLATFORM_COUNT}/{EXPECTED_PLATFORM_COUNT}).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--api-base",
        default=os.environ.get("PLATFORM_SMOKE_API_BASE", "https://downloader-api.bhwa233.com"),
    )
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("PLATFORM_SMOKE_TIMEOUT", "30")))
    parser.add_argument("--workers", type=int, default=int(os.environ.get("PLATFORM_SMOKE_WORKERS", "2")))
    parser.add_argument("--output-dir", default="platform-release-gate-artifacts")
    args = parser.parse_args()
    return run_live_gate(
        api_base=args.api_base,
        timeout=max(5, min(args.timeout, 120)),
        workers=max(1, min(args.workers, 8)),
        output_dir=Path(args.output_dir),
    )


if __name__ == "__main__":
    raise SystemExit(main())
