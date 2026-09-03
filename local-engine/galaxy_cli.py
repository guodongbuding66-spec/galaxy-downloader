from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_ENDPOINT = "http://127.0.0.1:17837"
TERMINAL_STATES = {"completed", "failed", "cancelled"}


class GalaxyCliError(RuntimeError):
    pass


def _validated_endpoint(value: object) -> str:
    raw = str(value or DEFAULT_ENDPOINT).strip().rstrip("/")
    try:
        parsed = urlparse(raw)
    except ValueError as exc:
        raise GalaxyCliError("invalid API endpoint") from exc
    if parsed.username is not None or parsed.password is not None or not parsed.hostname:
        raise GalaxyCliError("invalid API endpoint")
    host = parsed.hostname.lower()
    loopback = host in {"127.0.0.1", "::1", "localhost"}
    if parsed.scheme == "http" and not loopback:
        raise GalaxyCliError("remote API endpoints must use HTTPS")
    if parsed.scheme not in {"http", "https"}:
        raise GalaxyCliError("API endpoint must use HTTP(S)")
    return raw


def _load_token_file(path: object) -> str:
    raw = str(path or "").strip()
    if not raw:
        return str(os.getenv("GALAXY_HEADLESS_TOKEN") or "").strip()
    try:
        token = Path(raw).expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise GalaxyCliError(f"could not read token file: {exc}") from exc
    return token


def _request(
    endpoint: str,
    path: str,
    *,
    token: str = "",
    payload: dict[str, Any] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    url = endpoint.rstrip("/") + path
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=max(2, min(int(timeout), 3600))) as response:  # noqa: S310
            data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise GalaxyCliError("API response is too large")
    except urllib.error.HTTPError as exc:
        detail = exc.read(256_000).decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("error") if isinstance(parsed, dict) else detail
        except ValueError:
            message = detail
        raise GalaxyCliError(f"API {exc.code}: {message}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GalaxyCliError(str(exc)) from exc
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GalaxyCliError("API returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise GalaxyCliError("API response must be a JSON object")
    return parsed


def _print(payload: object, *, compact: bool = False) -> None:
    if compact:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def _download_payload(args) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sourceUrl": args.url,
        "includeAudio": not args.no_audio,
        "includeSubtitle": bool(args.subtitles),
        "includeCover": bool(args.cover),
        "collectionMode": "all" if args.playlist else "single",
        "concurrentFragments": args.fragments,
        "rateLimitMbps": args.rate_limit_mbps,
    }
    if args.video_format_id:
        payload["videoFormatId"] = args.video_format_id
    if args.audio_format_id:
        payload["audioFormatId"] = args.audio_format_id
    if args.subtitle_language:
        payload["subtitleLanguages"] = list(dict.fromkeys(args.subtitle_language))[:16]
    return payload


def _wait_for_job(endpoint: str, token: str, job_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, min(int(timeout), 7 * 24 * 3600))
    previous_state = ""
    while time.monotonic() < deadline:
        response = _request(endpoint, f"/v1/jobs/{job_id}", token=token, timeout=30)
        job = response.get("job") if isinstance(response.get("job"), dict) else {}
        state = str(job.get("state") or "")
        if state != previous_state and sys.stderr.isatty():
            print(
                f"{state or 'unknown'} {float(job.get('progress') or 0):.1f}% {job.get('detail') or ''}",
                file=sys.stderr,
            )
            previous_state = state
        if state in TERMINAL_STATES:
            return response
        time.sleep(1.0)
    raise GalaxyCliError("timed out while waiting for job completion")


def run_cli_self_test() -> None:
    assert _validated_endpoint("http://127.0.0.1:17837") == "http://127.0.0.1:17837"
    assert _validated_endpoint("https://downloads.example.test/api") == "https://downloads.example.test/api"
    try:
        _validated_endpoint("http://downloads.example.test")
    except GalaxyCliError:
        pass
    else:
        raise AssertionError("remote plaintext API endpoint was accepted")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="galaxy", description="Galaxy Local Engine CLI")
    parser.add_argument(
        "--endpoint",
        default=os.getenv("GALAXY_API_URL", DEFAULT_ENDPOINT),
        help="Headless API endpoint (remote endpoints must use HTTPS)",
    )
    parser.add_argument(
        "--token-file",
        default=os.getenv("GALAXY_HEADLESS_TOKEN_FILE", ""),
        help="Read bearer token from a file; otherwise GALAXY_HEADLESS_TOKEN is used",
    )
    parser.add_argument("--compact", action="store_true", help="Print compact JSON")
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show API and queue status")

    parse = sub.add_parser("parse", help="Parse one media URL")
    parse.add_argument("url")

    download = sub.add_parser("download", help="Queue one download")
    download.add_argument("url")
    download.add_argument("--video-format-id")
    download.add_argument("--audio-format-id")
    download.add_argument("--no-audio", action="store_true")
    download.add_argument("--subtitles", action="store_true")
    download.add_argument("--subtitle-language", action="append", default=[])
    download.add_argument("--cover", action="store_true")
    download.add_argument("--playlist", action="store_true")
    download.add_argument("--fragments", type=int, default=4)
    download.add_argument("--rate-limit-mbps", type=int, default=0)
    download.add_argument("--wait", action="store_true")
    download.add_argument("--timeout", type=int, default=24 * 3600)

    job = sub.add_parser("job", help="Show one queued/running/completed job")
    job.add_argument("job_id")

    wait = sub.add_parser("wait", help="Wait for a job to finish")
    wait.add_argument("job_id")
    wait.add_argument("--timeout", type=int, default=24 * 3600)

    serve = sub.add_parser("serve", help="Start the headless API in this process")
    serve.add_argument("--host", default=os.getenv("GALAXY_HEADLESS_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.getenv("GALAXY_HEADLESS_PORT", "17837")))
    serve.add_argument("--download-dir", default=os.getenv("GALAXY_DOWNLOAD_DIR", ""))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        run_cli_self_test()
        print("Galaxy CLI self-test passed")
        return 0
    if args.command == "serve":
        from headless_service import main as service_main

        service_args = ["--host", args.host, "--port", str(args.port)]
        if args.download_dir:
            service_args.extend(["--download-dir", args.download_dir])
        return service_main(service_args)
    if not args.command:
        parser.print_help()
        return 2

    try:
        endpoint = _validated_endpoint(args.endpoint)
        token = _load_token_file(args.token_file)
        if args.command == "status":
            result = _request(endpoint, "/v1/status", token=token)
        elif args.command == "parse":
            result = _request(endpoint, "/v1/parse", token=token, payload={"sourceUrl": args.url}, timeout=90)
        elif args.command == "download":
            result = _request(endpoint, "/v1/download", token=token, payload=_download_payload(args), timeout=90)
            if args.wait:
                job = result.get("job") if isinstance(result.get("job"), dict) else {}
                job_id = str(job.get("id") or "")
                if not job_id:
                    raise GalaxyCliError("download response did not contain a job id")
                result = _wait_for_job(endpoint, token, job_id, args.timeout)
        elif args.command == "job":
            result = _request(endpoint, f"/v1/jobs/{args.job_id}", token=token)
        elif args.command == "wait":
            result = _wait_for_job(endpoint, token, args.job_id, args.timeout)
        else:
            raise GalaxyCliError("unknown command")
        _print(result, compact=bool(args.compact))
        job = result.get("job") if isinstance(result, dict) and isinstance(result.get("job"), dict) else {}
        return 1 if str(job.get("state") or "") == "failed" else 0
    except GalaxyCliError as exc:
        print(f"galaxy: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
