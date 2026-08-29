#!/usr/bin/env python3
"""Live probe for the optional Galaxy Xiaohongshu resolver.

The probe intentionally uses only the Python standard library so it can run in
GitHub Actions or on an operator workstation without installing the resolver.
It never prints the Bearer token and never stores returned media URLs in the
artifact report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_MEDIA_SUFFIXES = ("xhscdn.com", "xiaohongshu.com")
DEFAULT_OUTPUT = Path("platform-smoke-artifacts/xhs-resolver-live-smoke.json")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def resolver_endpoint(raw: str) -> str:
    value = raw.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("XHS_RESOLVER_URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("XHS_RESOLVER_URL must not contain embedded credentials")

    path = parsed.path.rstrip("/")
    if not path.endswith("/xhs/detail"):
        path = f"{path}/xhs/detail" if path else "/xhs/detail"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def normalize_suffixes(raw: str | None) -> tuple[str, ...]:
    values = []
    for item in (raw or "").split(","):
        item = item.strip().lower().lstrip(".").rstrip(".")
        if item:
            values.append(item)
    return tuple(values) or DEFAULT_MEDIA_SUFFIXES


def host_allowed(url: str, suffixes: tuple[str, ...]) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().rstrip(".")
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes)


def as_url_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str):
        return [match.group(0).rstrip(",;") for match in URL_RE.finditer(value)]
    return []


def extract_media(detail: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    structured = detail.get("媒体")
    media: list[dict[str, Any]] = []

    if isinstance(structured, list):
        for index, item in enumerate(structured, start=1):
            if not isinstance(item, dict):
                continue
            url = item.get("地址")
            if not isinstance(url, str) or not url.strip():
                continue
            media.append(
                {
                    "index": item.get("序号") or index,
                    "kind": str(item.get("类型") or "未知"),
                    "url": url.strip(),
                }
            )
        if media:
            return "structured-media", media

    download_urls = as_url_list(detail.get("下载地址"))
    if download_urls:
        work_type = str(detail.get("作品类型") or "未知")
        kind = "视频" if work_type == "视频" else "图片"
        for index, url in enumerate(download_urls, start=1):
            media.append({"index": index, "kind": kind, "url": url})
        return "legacy-download-address", media

    return "unknown", []


def read_limited(response, max_bytes: int) -> bytes:  # noqa: ANN001
    data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise RuntimeError(f"resolver response exceeded {max_bytes} bytes")
    return data


def post_resolver(
    endpoint: str,
    source_url: str,
    token: str,
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    body = json.dumps({"url": source_url, "download": False}, ensure_ascii=False).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(endpoint, data=body, headers=headers, method="POST")
    opener = build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(response.getcode())
            raw = read_limited(response, DEFAULT_MAX_RESPONSE_BYTES)
    except HTTPError as error:
        raw = read_limited(error, DEFAULT_MAX_RESPONSE_BYTES)
        message = raw.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"resolver returned HTTP {error.code}: {message}") from error
    except URLError as error:
        raise RuntimeError(f"resolver request failed: {error.reason}") from error

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("resolver returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise RuntimeError("resolver returned a non-object JSON payload")
    return status, payload


def probe_media(
    media_url: str,
    source_url: str,
    suffixes: tuple[str, ...],
    timeout: float,
) -> dict[str, Any]:
    if not host_allowed(media_url, suffixes):
        raise RuntimeError("resolver returned a media host outside XHS_MEDIA_HOST_SUFFIXES")

    request = Request(
        media_url,
        headers={
            "Accept": "*/*",
            "Range": "bytes=0-1023",
            "Referer": source_url,
            "User-Agent": DEFAULT_USER_AGENT,
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            status = int(response.getcode())
            if not host_allowed(final_url, suffixes):
                raise RuntimeError("media redirect escaped XHS_MEDIA_HOST_SUFFIXES")
            sample = response.read(1024)
            return {
                "status": status,
                "bytesRead": len(sample),
                "finalHost": urlsplit(final_url).hostname,
                "contentType": response.headers.get("Content-Type"),
                "contentRange": response.headers.get("Content-Range"),
            }
    except HTTPError as error:
        raise RuntimeError(f"media range probe returned HTTP {error.code}") from error
    except URLError as error:
        raise RuntimeError(f"media range probe failed: {error.reason}") from error


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe a deployed Galaxy XHS resolver")
    parser.add_argument("--resolver-url", default=os.getenv("XHS_RESOLVER_URL", ""))
    parser.add_argument("--source-url", default=os.getenv("XHS_SMOKE_URL", ""))
    parser.add_argument("--token", default=os.getenv("XHS_RESOLVER_TOKEN", ""))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("XHS_SMOKE_TIMEOUT", DEFAULT_TIMEOUT)))
    parser.add_argument("--output", type=Path, default=Path(os.getenv("XHS_SMOKE_OUTPUT", str(DEFAULT_OUTPUT))))
    parser.add_argument("--fetch-media", action="store_true")
    parser.add_argument("--allow-missing-config", action="store_true")
    args = parser.parse_args()

    fetch_media = args.fetch_media or parse_bool(os.getenv("XHS_SMOKE_FETCH_MEDIA"))
    allow_missing = args.allow_missing_config or parse_bool(os.getenv("XHS_SMOKE_ALLOW_MISSING"))
    started = time.time()

    if not args.resolver_url.strip() or not args.source_url.strip():
        report = {
            "status": "skipped" if allow_missing else "failed",
            "reason": "XHS_RESOLVER_URL and XHS_SMOKE_URL are required",
            "durationMs": round((time.time() - started) * 1000),
        }
        write_report(args.output, report)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if allow_missing else 2

    report: dict[str, Any] = {
        "status": "failed",
        "resolverHost": None,
        "sourceHost": None,
        "schema": None,
        "workType": None,
        "mediaCount": 0,
        "mediaHosts": [],
        "mediaProbe": None,
    }

    try:
        endpoint = resolver_endpoint(args.resolver_url)
        source = urlsplit(args.source_url)
        if source.scheme not in {"http", "https"} or not source.hostname:
            raise RuntimeError("XHS_SMOKE_URL must be an absolute http(s) URL")
        if not (
            source.hostname == "xiaohongshu.com"
            or source.hostname.endswith(".xiaohongshu.com")
            or source.hostname == "xhslink.com"
            or source.hostname.endswith(".xhslink.com")
            or source.hostname == "xhslink.cn"
            or source.hostname.endswith(".xhslink.cn")
        ):
            raise RuntimeError("XHS_SMOKE_URL is not a Xiaohongshu URL")

        report["resolverHost"] = urlsplit(endpoint).hostname
        report["sourceHost"] = source.hostname

        status, payload = post_resolver(endpoint, args.source_url, args.token, args.timeout)
        if status < 200 or status >= 300:
            raise RuntimeError(f"resolver returned unexpected HTTP {status}")
        detail = payload.get("data")
        if not isinstance(detail, dict):
            message = payload.get("message") or payload.get("error") or "missing data"
            raise RuntimeError(f"resolver did not return work detail: {message}")

        schema, media = extract_media(detail)
        if not media:
            raise RuntimeError("resolver returned no downloadable media")

        suffixes = normalize_suffixes(os.getenv("XHS_MEDIA_HOST_SUFFIXES"))
        for item in media:
            if not host_allowed(item["url"], suffixes):
                raise RuntimeError("resolver returned a media host outside XHS_MEDIA_HOST_SUFFIXES")

        hosts = sorted({urlsplit(item["url"]).hostname for item in media if urlsplit(item["url"]).hostname})
        report.update(
            {
                "schema": schema,
                "workType": detail.get("作品类型"),
                "mediaCount": len(media),
                "mediaHosts": hosts,
            }
        )

        if fetch_media:
            preferred = next((item for item in media if item["kind"] == "视频"), media[0])
            report["mediaProbe"] = probe_media(preferred["url"], args.source_url, suffixes, args.timeout)

        report["status"] = "passed"
    except Exception as error:  # noqa: BLE001 - smoke report must serialize failures
        report["error"] = str(error)
    finally:
        report["durationMs"] = round((time.time() - started) * 1000)
        write_report(args.output, report)
        print(json.dumps(report, ensure_ascii=False))

    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
