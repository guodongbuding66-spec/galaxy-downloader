from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _engine_module():
    import engine

    return engine


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _download_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "sourceUrl": args.url,
        "videoQuality": args.video,
        "audioQuality": args.audio,
        "includeAudio": not args.video_only,
        "includeSubtitle": args.subtitles,
        "subtitleLanguage": args.subtitle_language or None,
        "includeCover": args.cover,
        "browser": args.browser,
        "collectionMode": "all" if args.collection else "single",
        "bandwidthLimitKbps": max(0, int(args.limit_kbps or 0)),
    }


def command_download(args: argparse.Namespace) -> int:
    engine = _engine_module()
    try:
        job = engine.job_from_payload(_download_payload(args))
    except (TypeError, ValueError) as exc:
        print(f"invalid download request: {exc}", file=sys.stderr)
        return 2
    payload = engine.job_to_payload(job)
    from bridge import post_job_to_running_engine

    if post_job_to_running_engine(payload, timeout=max(0.2, min(float(args.timeout), 10.0))):
        print("accepted by running Galaxy Local Engine")
        return 0
    print("Galaxy Local Engine is not running or rejected the job", file=sys.stderr)
    return 3


def command_status(_args: argparse.Namespace) -> int:
    from bridge import BRIDGE_BASE_URL, bridge_is_running

    print(_json({"running": bridge_is_running(), "bridge": BRIDGE_BASE_URL}))
    return 0


def command_history(args: argparse.Namespace) -> int:
    engine = _engine_module()
    from job_history import load_history

    rows = load_history(engine)[: max(1, min(int(args.limit), 500))]
    print(_json(rows))
    return 0


def command_library(args: argparse.Namespace) -> int:
    engine = _engine_module()
    from media_library import list_media_items, search_media_items, sync_media_library

    if args.sync:
        sync_media_library(engine)
    rows = (
        search_media_items(engine, args.query, limit=args.limit)
        if args.query
        else list_media_items(engine, limit=args.limit, media_type=args.type)
    )
    print(_json(rows))
    return 0


def command_subscriptions(_args: argparse.Namespace) -> int:
    engine = _engine_module()
    from subscriptions import load_subscriptions

    safe_rows = []
    for item in load_subscriptions(engine):
        safe_rows.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "sourceUrl": item.get("sourceUrl"),
                "enabled": bool(item.get("enabled", True)),
                "autoDownload": bool(item.get("autoDownload", False)),
                "intervalMinutes": int(item.get("intervalMinutes") or 60),
                "lastCheckedAt": item.get("lastCheckedAt"),
                "lastError": item.get("lastError"),
            }
        )
    print(_json(safe_rows))
    return 0


def command_doctor(_args: argparse.Namespace) -> int:
    engine = _engine_module()
    from ai_models import ai_model_status
    from content_providers import provider_status
    from managed_tool_registry import public_managed_tool_registry
    from transfer_center import transfer_status

    try:
        registry = public_managed_tool_registry(engine)
    except Exception as exc:  # noqa: BLE001
        registry = {"error": type(exc).__name__}
    payload = {
        "version": getattr(engine, "VERSION", "unknown"),
        "appDir": str(Path(engine.app_dir())),
        "downloadDir": str(Path(engine.default_download_dir())),
        "tools": registry,
        "ai": ai_model_status(engine),
        "providers": provider_status(engine),
        "transfers": transfer_status(engine),
    }
    print(_json(payload))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="galaxy", description="Galaxy Local Engine CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    download = sub.add_parser("download", help="submit a download to a running Local Engine")
    download.add_argument("url")
    download.add_argument("--video", default="best")
    download.add_argument("--audio", default="best")
    download.add_argument("--video-only", action="store_true")
    download.add_argument("--subtitles", action="store_true")
    download.add_argument("--subtitle-language", default="")
    download.add_argument("--cover", action="store_true")
    download.add_argument("--collection", action="store_true")
    download.add_argument("--browser", default="none")
    download.add_argument("--limit-kbps", type=int, default=0)
    download.add_argument("--timeout", type=float, default=1.5)
    download.set_defaults(handler=command_download)

    status = sub.add_parser("status", help="show local bridge status")
    status.set_defaults(handler=command_status)

    history = sub.add_parser("history", help="print privacy-safe local history")
    history.add_argument("--limit", type=int, default=50)
    history.set_defaults(handler=command_history)

    library = sub.add_parser("library", help="list/search the local media library")
    library.add_argument("--query", default="")
    library.add_argument("--type", choices=("video", "audio", "image", "other"), default=None)
    library.add_argument("--limit", type=int, default=100)
    library.add_argument("--sync", action="store_true")
    library.set_defaults(handler=command_library)

    subscriptions = sub.add_parser("subscriptions", help="list subscriptions")
    subscriptions.set_defaults(handler=command_subscriptions)

    doctor = sub.add_parser("doctor", help="show dependency/provider readiness")
    doctor.set_defaults(handler=command_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


def run_cli_self_test() -> None:
    parser = build_parser()
    parsed = parser.parse_args(["download", "https://example.com/video", "--video", "1080p", "--subtitles"])
    assert parsed.url == "https://example.com/video"
    assert parsed.video == "1080p"
    assert parsed.subtitles is True
    payload = _download_payload(parsed)
    assert payload["sourceUrl"] == "https://example.com/video"
    assert payload["includeSubtitle"] is True
    assert payload["bandwidthLimitKbps"] == 0


if __name__ == "__main__":
    raise SystemExit(main())
