#!/usr/bin/env python3
"""Require all 33 public Galaxy Downloader platforms to pass a live media probe."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

EXPECTED_PLATFORM_COUNT = 33
STATUS_KEYS = ("PASS", "PARTIAL", "FAIL", "SKIP")


def load_catalog_platforms(repo_root: Path) -> set[str]:
    source = (repo_root / "src/components/downloader/platform-support.ts").read_text(encoding="utf-8")
    match = re.search(
        r"const\s+PLATFORM_SUPPORT_CATALOG[^=]*=\s*\[(.*?)\];",
        source,
        flags=re.DOTALL,
    )
    if not match:
        raise RuntimeError("could not locate PLATFORM_SUPPORT_CATALOG")
    return set(re.findall(r"'([^']+)'", match.group(1)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output-dir", default="platform-smoke-artifacts")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = repo_root / args.output_dir
    smoke_script = repo_root / "scripts/platform-smoke.py"

    command = [
        sys.executable,
        str(smoke_script),
        "--api-base",
        args.api_base,
        "--timeout",
        str(args.timeout),
        "--workers",
        str(args.workers),
        "--output-dir",
        str(output_dir),
    ]
    completed = subprocess.run(command, cwd=repo_root, check=False)
    if completed.returncode != 0:
        print(f"platform smoke runner exited with {completed.returncode}", file=sys.stderr)
        return completed.returncode

    report_path = output_dir / "platform-smoke.json"
    if not report_path.exists():
        print("platform smoke report was not generated", file=sys.stderr)
        return 2

    report = json.loads(report_path.read_text(encoding="utf-8"))
    results = report.get("results")
    if not isinstance(results, list):
        print("platform smoke report has no results list", file=sys.stderr)
        return 2

    result_platforms = {
        item.get("platform")
        for item in results
        if isinstance(item, dict) and isinstance(item.get("platform"), str)
    }
    catalog_platforms = load_catalog_platforms(repo_root)

    counts = {
        key: sum(1 for item in results if isinstance(item, dict) and item.get("status") == key)
        for key in STATUS_KEYS
    }
    total = len(results)

    violations: list[str] = []
    if len(catalog_platforms) != EXPECTED_PLATFORM_COUNT:
        violations.append(
            f"frontend catalog contains {len(catalog_platforms)} platforms; expected {EXPECTED_PLATFORM_COUNT}"
        )
    if total != EXPECTED_PLATFORM_COUNT:
        violations.append(f"smoke report contains {total} platforms; expected {EXPECTED_PLATFORM_COUNT}")
    if result_platforms != catalog_platforms:
        missing = sorted(catalog_platforms - result_platforms)
        unexpected = sorted(result_platforms - catalog_platforms)
        if missing:
            violations.append("missing smoke platforms: " + ", ".join(missing))
        if unexpected:
            violations.append("unexpected smoke platforms: " + ", ".join(unexpected))
    if counts["PASS"] != EXPECTED_PLATFORM_COUNT:
        violations.append(
            "all-platform gate requires 33 PASS results; "
            f"got PASS={counts['PASS']} PARTIAL={counts['PARTIAL']} FAIL={counts['FAIL']} SKIP={counts['SKIP']}"
        )

    gate = {
        "expectedPlatforms": EXPECTED_PLATFORM_COUNT,
        "catalogPlatforms": len(catalog_platforms),
        "resultPlatforms": total,
        "counts": counts,
        "passed": not violations,
        "violations": violations,
    }
    (output_dir / "platform-release-gate.json").write_text(
        json.dumps(gate, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Release gate:", json.dumps(gate, ensure_ascii=False))
    if violations:
        for violation in violations:
            print(f"GATE FAIL: {violation}", file=sys.stderr)
        return 1

    print("GATE PASS: all 33 supported platforms parsed and returned readable media bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
