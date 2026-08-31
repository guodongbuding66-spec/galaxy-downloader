from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import document_policy  # noqa: E402
from dynamic_document import parse_dynamic_web_document  # noqa: E402


document_policy.install_document_policy()

FIXTURES = ROOT / "fixtures" / "document-live-targets.json"
BLOCKED_TOKENS = (
    "captcha",
    "challenge",
    "robot",
    "automated access",
    "access denied",
    "forbidden",
    "verify you are human",
    "unusual traffic",
    "security check",
    "http 403",
    "http 429",
    "http 503",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "service unavailable",
)


def _payload_detail(payload: dict[str, Any]) -> str:
    return " ".join(
        str(payload.get(key) or "")
        for key in ("code", "error", "message", "status", "details")
    ).strip()


def _has_media_signal(data: dict[str, Any]) -> bool:
    images = data.get("images") if isinstance(data.get("images"), list) else []
    videos = data.get("videos") if isinstance(data.get("videos"), list) else []
    text = str(data.get("markdownContent") or data.get("textContent") or data.get("desc") or "").strip()
    return bool(images or videos or len(text) >= 20)


def _validate_success(target: dict[str, Any], payload: dict[str, Any], stage: str) -> None:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"{target['name']}: {stage} returned success without data")
    actual_platform = str(data.get("platform") or "")
    expected_platform = str(target.get("platform") or "")
    if actual_platform != expected_platform:
        raise RuntimeError(
            f"{target['name']}: expected platform {expected_platform!r}, got {actual_platform!r}"
        )
    if not _has_media_signal(data):
        raise RuntimeError(f"{target['name']}: {stage} returned success without document media/text")
    images = len(data.get("images") or []) if isinstance(data.get("images"), list) else 0
    videos = len(data.get("videos") or []) if isinstance(data.get("videos"), list) else 0
    print(f"PASS    {target['name']} via {stage}: platform={actual_platform} images={images} videos={videos}")


def _is_allowed_block(target: dict[str, Any], attempts: list[dict[str, Any]]) -> bool:
    if not target.get("allow_blocked"):
        return False
    detail = " ".join(_payload_detail(item).lower() for item in attempts)
    return any(token in detail for token in BLOCKED_TOKENS)


def run_target(target: dict[str, Any]) -> str:
    source_url = str(target["url"])
    attempts: list[dict[str, Any]] = []

    static = document_policy.parse_web_document(source_url, "none")
    attempts.append(static)
    if static.get("success"):
        _validate_success(target, static, "static")
        return "passed"

    dynamic = parse_dynamic_web_document(source_url, "none")
    attempts.append(dynamic)
    if dynamic.get("success"):
        _validate_success(target, dynamic, "cdp")
        return "passed"

    if _is_allowed_block(target, attempts):
        print(f"BLOCKED {target['name']}: {_payload_detail(attempts[-1])[:320]}")
        return "blocked"

    details = " | ".join(_payload_detail(item)[:500] for item in attempts)
    raise RuntimeError(f"{target['name']}: no valid document result and no recognized platform block: {details}")


def main() -> int:
    targets = json.loads(FIXTURES.read_text(encoding="utf-8"))
    if not isinstance(targets, list) or not targets:
        raise RuntimeError("Document live smoke fixture list is empty")

    counts = {"passed": 0, "blocked": 0, "failed": 0}
    failures: list[str] = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        try:
            outcome = run_target(target)
            counts[outcome] += 1
        except Exception as exc:  # noqa: BLE001
            counts["failed"] += 1
            failures.append(str(exc))
            print(f"FAIL    {target.get('name', 'unknown')}: {exc}")

    print(
        f"Document live smoke summary: passed={counts['passed']} blocked={counts['blocked']} failed={counts['failed']}"
    )
    if failures:
        print("\n".join(f" - {failure}" for failure in failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
