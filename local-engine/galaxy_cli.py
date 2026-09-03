from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_API_URL = "http://127.0.0.1:17837"
DEFAULT_TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = 64 * 1024
TERMINAL_JOB_STATES = frozenset({"completed", "failed", "cancelled"})
_JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
_SECRET_RE = re.compile(
    r"(?i)(authorization|api[-_ ]?key|token|secret|cookie|session|password)\s*[:=]\s*[^\s,;]+"
)


class GalaxyCliError(RuntimeError):
    pass


class GalaxyTransportError(GalaxyCliError):
    pass


class GalaxyApiError(GalaxyCliError):
    def __init__(self, status: int, detail: object) -> None:
        self.status = int(status)
        self.detail = _safe_detail(detail)
        super().__init__(f"API {self.status}: {self.detail}")


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise GalaxyTransportError(f"API redirect blocked ({int(code)})")


def _safe_detail(value: object, limit: int = 1200) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    text = _SECRET_RE.sub(r"\1=[REDACTED]", text)
    return text[:limit]


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def _bounded_float(value: object, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(low, min(parsed, high))


def _is_loopback(hostname: str) -> bool:
    clean = str(hostname or "").strip().lower().rstrip(".")
    if clean == "localhost":
        return True
    try:
        return ipaddress.ip_address(clean).is_loopback
    except ValueError:
        return False


def normalize_api_url(value: object, *, token: str = "") -> str:
    raw = str(value or DEFAULT_API_URL).strip()
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise GalaxyCliError("invalid Galaxy API URL") from exc
    scheme = parsed.scheme.lower()
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    if scheme not in {"http", "https"} or not hostname:
        raise GalaxyCliError("Galaxy API URL must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise GalaxyCliError("Galaxy API URL must not contain credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise GalaxyCliError("Galaxy API URL must point to the server root")
    loopback = _is_loopback(hostname)
    if scheme == "http" and not loopback:
        raise GalaxyCliError("plain HTTP is allowed only for loopback Galaxy API endpoints")
    if not loopback and len(str(token or "")) < 24:
        raise GalaxyCliError("a bearer token with at least 24 characters is required for non-loopback API endpoints")
    host = hostname
    if ":" in hostname and not hostname.startswith("["):
        host = f"[{hostname}]"
    try:
        if parsed.port:
            host = f"{host}:{parsed.port}"
    except ValueError as exc:
        raise GalaxyCliError("invalid Galaxy API port") from exc
    return urlunsplit((scheme, host, "", "", ""))


def _clean_job_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _JOB_ID_RE.fullmatch(clean):
        raise GalaxyCliError("invalid job id")
    return clean


def _clean_media_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _MEDIA_ID_RE.fullmatch(clean):
        raise GalaxyCliError("invalid media id")
    return clean


def _query_values(values: Sequence[str] | None, *, limit: int = 30, chars: int = 80) -> list[str]:
    result: list[str] = []
    for raw in values or ():
        for candidate in str(raw or "").replace("\r", "\n").replace(",", "\n").split("\n"):
            clean = " ".join(candidate.split()).strip()[:chars]
            if clean and clean not in result:
                result.append(clean)
            if len(result) >= limit:
                return result
    return result


@dataclass
class GalaxyApiClient:
    base_url: str = DEFAULT_API_URL
    token: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        self.token = str(self.token or "").strip()
        self.base_url = normalize_api_url(self.base_url, token=self.token)
        self.timeout_seconds = _bounded_float(self.timeout_seconds, DEFAULT_TIMEOUT_SECONDS, 1.0, 120.0)
        self._opener = build_opener(_NoRedirectHandler())

    def _url(self, path: str, query: Mapping[str, object] | None = None) -> str:
        if not path.startswith("/") or "\x00" in path or "?" in path or "#" in path:
            raise GalaxyCliError("invalid API path")
        suffix = ""
        if query:
            pairs: list[tuple[str, str]] = []
            for key, value in query.items():
                if value in (None, ""):
                    continue
                pairs.append((str(key), str(value)))
            if pairs:
                suffix = "?" + urlencode(pairs)
        return self.base_url + path + suffix

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        verb = str(method or "GET").upper()
        if verb not in {"GET", "POST"}:
            raise GalaxyCliError("unsupported API method")
        body: bytes | None = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "GalaxyCLI/2",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            body = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(body) > MAX_REQUEST_BYTES:
                raise GalaxyCliError("CLI request exceeds the 64 KB API request limit")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(self._url(path, query), method=verb, data=body, headers=headers)
        try:
            response = self._opener.open(request, timeout=self.timeout_seconds)
            try:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                status = int(getattr(response, "status", 200) or 200)
            finally:
                response.close()
        except GalaxyTransportError:
            raise
        except HTTPError as exc:
            try:
                raw = exc.read(MAX_RESPONSE_BYTES + 1)
            except OSError:
                raw = b""
            if len(raw) > MAX_RESPONSE_BYTES:
                raise GalaxyTransportError("Galaxy API error response exceeded 4 MB") from exc
            detail: object = exc.reason or "request failed"
            try:
                parsed = json.loads(raw.decode("utf-8")) if raw else {}
                if isinstance(parsed, dict):
                    detail = parsed.get("error") or parsed.get("message") or detail
            except (UnicodeDecodeError, ValueError):
                detail = _safe_detail(detail)
            raise GalaxyApiError(exc.code, detail) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise GalaxyTransportError(_safe_detail(getattr(exc, "reason", exc))) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise GalaxyTransportError("Galaxy API response exceeded 4 MB")
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError) as exc:
            raise GalaxyTransportError("Galaxy API returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise GalaxyTransportError("Galaxy API returned a non-object JSON response")
        if status >= 400 or parsed.get("ok") is False:
            raise GalaxyApiError(status, parsed.get("error") or "request failed")
        return parsed

    def get(self, path: str, *, query: Mapping[str, object] | None = None) -> dict[str, Any]:
        return self.request("GET", path, query=query)

    def post(self, path: str, *, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.request("POST", path, payload=payload)

    def wait_for_job(
        self,
        job_id: object,
        *,
        poll_seconds: float = 1.0,
        timeout_seconds: float = 3600.0,
    ) -> dict[str, Any]:
        clean = _clean_job_id(job_id)
        interval = _bounded_float(poll_seconds, 1.0, 0.2, 30.0)
        timeout = _bounded_float(timeout_seconds, 3600.0, 1.0, 86_400.0)
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        while True:
            last = self.get(f"/v1/jobs/{clean}")
            job = last.get("job") if isinstance(last.get("job"), dict) else {}
            state = str(job.get("state") or "").lower()
            if state in TERMINAL_JOB_STATES:
                return last
            if time.monotonic() >= deadline:
                raise GalaxyTransportError(f"timed out waiting for job {clean}")
            time.sleep(interval)


def _add_bool_pair(parser: argparse.ArgumentParser, positive: str, negative: str, dest: str, help_text: str) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(positive, dest=dest, action="store_true", help=help_text)
    group.add_argument(negative, dest=dest, action="store_false", help=argparse.SUPPRESS)
    parser.set_defaults(**{dest: None})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="galaxy", description="Galaxy Local Engine CLI 2.0")
    parser.add_argument("--api-url", default=os.getenv("GALAXY_HEADLESS_URL", DEFAULT_API_URL))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show headless service status")

    parse = sub.add_parser("parse", help="parse a public media URL")
    parse.add_argument("source_url")

    download = sub.add_parser("download", help="queue a media download")
    download.add_argument("source_url")
    download.add_argument("--video-format")
    download.add_argument("--audio-format")
    download.add_argument("--video-only", action="store_true")
    download.add_argument("--subtitle", action="store_true")
    download.add_argument("--subtitle-language", action="append", default=[])
    download.add_argument("--cover", action="store_true")
    download.add_argument("--collection", action="store_true")
    download.add_argument("--rate-limit-mbps", type=int, default=0)
    download.add_argument("--concurrent-fragments", type=int, default=4)
    download.add_argument("--wait", action="store_true")
    download.add_argument("--wait-timeout", type=float, default=3600.0)

    jobs = sub.add_parser("jobs", help="list recent jobs")
    jobs.add_argument("--limit", type=int, default=100)
    job = sub.add_parser("job", help="show one job")
    job.add_argument("job_id")
    for name in ("cancel", "pause", "resume", "retry"):
        action = sub.add_parser(name, help=f"{name} a job")
        action.add_argument("job_id")
    wait = sub.add_parser("wait", help="wait for a job to finish")
    wait.add_argument("job_id")
    wait.add_argument("--poll-seconds", type=float, default=1.0)
    wait.add_argument("--timeout-seconds", type=float, default=3600.0)

    media = sub.add_parser("media", help="list/search Media Library")
    media.add_argument("--query", default="")
    media.add_argument("--type", choices=("video", "audio", "image", "other"))
    media.add_argument("--limit", type=int, default=100)
    media.add_argument("--offset", type=int, default=0)
    sub.add_parser("media-summary", help="show Media Library summary")
    sub.add_parser("media-sync", help="sync Media Library from durable history")

    transcript = sub.add_parser("transcript", help="list transcript segments")
    transcript.add_argument("media_id")
    transcript.add_argument("--limit", type=int, default=1000)
    search = sub.add_parser("transcript-search", help="search transcript index")
    search.add_argument("--query", default="")
    search.add_argument("--media-id", default="")
    search.add_argument("--speaker", default="")
    search.add_argument("--start", type=float)
    search.add_argument("--end", type=float)
    search.add_argument("--limit", type=int, default=100)
    index = sub.add_parser("transcript-index", help="index a managed SRT transcript")
    index.add_argument("media_id")
    relabel = sub.add_parser("transcript-relabel", help="rename a speaker label")
    relabel.add_argument("media_id")
    relabel.add_argument("old_label")
    relabel.add_argument("new_label")
    export = sub.add_parser("transcript-export", help="export a transcript")
    export.add_argument("media_id")
    export.add_argument("--format", choices=("txt", "md", "srt", "vtt", "json", "csv"), default="txt")
    export.add_argument("--basename", default="")
    export.add_argument("--no-speaker", action="store_true")

    sub.add_parser("subscriptions", help="list subscriptions")
    subscription = sub.add_parser("subscription", help="show one subscription")
    subscription.add_argument("subscription_id")
    create = sub.add_parser("subscription-create", help="create a subscription")
    create.add_argument("source_url")
    create.add_argument("--title", default="")
    create.add_argument("--browser", choices=("none", "edge", "chrome", "firefox", "brave", "chromium", "opera", "vivaldi"), default="none")
    create.add_argument("--interval", type=int, default=60)
    create.add_argument("--auto-download", action="store_true")
    create.add_argument("--disabled", action="store_true")
    create.add_argument("--video-quality", default="best")
    create.add_argument("--audio-quality", default="best")
    create.add_argument("--video-only", action="store_true")

    update = sub.add_parser("subscription-update", help="update subscription settings")
    update.add_argument("subscription_id")
    update.add_argument("--source-url")
    update.add_argument("--title")
    update.add_argument("--browser", choices=("none", "edge", "chrome", "firefox", "brave", "chromium", "opera", "vivaldi"))
    update.add_argument("--interval", type=int)
    update.add_argument("--video-quality")
    update.add_argument("--audio-quality")
    _add_bool_pair(update, "--enable", "--disable", "enabled", "enable subscription")
    _add_bool_pair(update, "--auto-download", "--no-auto-download", "auto_download", "enable automatic approval")
    _add_bool_pair(update, "--include-audio", "--video-only", "include_audio", "include audio")

    delete = sub.add_parser("subscription-delete", help="delete a subscription")
    delete.add_argument("subscription_id")
    rules = sub.add_parser("subscription-rules", help="show Subscription V2 rules")
    rules.add_argument("subscription_id")
    set_rules = sub.add_parser("subscription-set-rules", help="update Subscription V2 rules")
    set_rules.add_argument("subscription_id")
    set_rules.add_argument("--include", action="append")
    set_rules.add_argument("--exclude", action="append")
    set_rules.add_argument("--latest", type=int)
    set_rules.add_argument("--tag", action="append")
    set_rules.add_argument("--profile")
    set_rules.add_argument("--filename")
    _add_bool_pair(set_rules, "--manual-review", "--no-manual-review", "manual_review", "require manual review")
    _add_bool_pair(set_rules, "--auto-download", "--no-auto-download", "rule_auto_download", "enable rule auto-download")

    items = sub.add_parser("subscription-items", help="list Subscription V2 items")
    items.add_argument("subscription_id")
    items.add_argument("--state", choices=("waiting", "approved", "queued", "downloading", "completed", "failed", "skipped"))
    items.add_argument("--present", choices=("true", "false", "any"), default="any")
    items.add_argument("--limit", type=int, default=200)
    counts = sub.add_parser("subscription-counts", help="show Subscription V2 state counts")
    counts.add_argument("subscription_id")
    transition = sub.add_parser("subscription-transition", help="transition one Subscription V2 item")
    transition.add_argument("subscription_id")
    transition.add_argument("entry_id")
    transition.add_argument("state", choices=("waiting", "approved", "queued", "downloading", "completed", "failed", "skipped"))
    transition.add_argument("--reason", default="cli")
    reconcile = sub.add_parser("subscription-reconcile", help="reconcile Subscription V2 item state")
    reconcile.add_argument("subscription_id")
    reconcile.add_argument("--retry-failed", action="store_true")
    reconcile.add_argument("--max-attempts", type=int, default=3)
    return parser


def _subscription_update_payload(args: argparse.Namespace) -> dict[str, Any]:
    fields = {
        "sourceUrl": args.source_url,
        "title": args.title,
        "browser": args.browser,
        "intervalMinutes": args.interval,
        "videoQuality": args.video_quality,
        "audioQuality": args.audio_quality,
        "enabled": args.enabled,
        "autoDownload": args.auto_download,
        "includeAudio": args.include_audio,
    }
    return {key: value for key, value in fields.items() if value is not None}


def _subscription_rules_payload(args: argparse.Namespace) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "latestN": args.latest,
        "profile": args.profile,
        "filename": args.filename,
        "manualReview": args.manual_review,
        "autoDownload": args.rule_auto_download,
    }
    if args.include is not None:
        fields["includeKeywords"] = _query_values(args.include)
    if args.exclude is not None:
        fields["excludeKeywords"] = _query_values(args.exclude)
    if args.tag is not None:
        fields["tags"] = _query_values(args.tag)
    return {key: value for key, value in fields.items() if value is not None}


def execute(args: argparse.Namespace, client: GalaxyApiClient) -> dict[str, Any]:
    command = args.command
    if command == "status":
        return client.get("/v1/status")
    if command == "parse":
        return client.post("/v1/parse", payload={"sourceUrl": args.source_url})
    if command == "download":
        payload: dict[str, Any] = {
            "sourceUrl": args.source_url,
            "includeAudio": not args.video_only,
            "includeSubtitle": bool(args.subtitle),
            "includeCover": bool(args.cover),
            "collectionMode": "collection" if args.collection else "single",
            "rateLimitMbps": max(0, int(args.rate_limit_mbps or 0)),
            "concurrentFragments": _bounded_int(args.concurrent_fragments, 4, 1, 8),
        }
        if args.video_format:
            payload["videoFormatId"] = args.video_format
        if args.audio_format:
            payload["audioFormatId"] = args.audio_format
        languages = _query_values(args.subtitle_language, limit=16, chars=32)
        if languages:
            payload["subtitleLanguages"] = languages
        result = client.post("/v1/download", payload=payload)
        if args.wait:
            job = result.get("job") if isinstance(result.get("job"), dict) else {}
            return client.wait_for_job(job.get("id"), timeout_seconds=args.wait_timeout)
        return result
    if command == "jobs":
        result = client.get("/v1/jobs")
        rows = result.get("jobs") if isinstance(result.get("jobs"), list) else []
        result["jobs"] = rows[: _bounded_int(args.limit, 100, 1, 500)]
        return result
    if command == "job":
        return client.get(f"/v1/jobs/{_clean_job_id(args.job_id)}")
    if command in {"cancel", "pause", "resume", "retry"}:
        return client.post(f"/v1/jobs/{_clean_job_id(args.job_id)}/{command}")
    if command == "wait":
        return client.wait_for_job(args.job_id, poll_seconds=args.poll_seconds, timeout_seconds=args.timeout_seconds)
    if command == "media":
        return client.get(
            "/v1/media",
            query={
                "q": args.query,
                "type": args.type,
                "limit": _bounded_int(args.limit, 100, 1, 100),
                "offset": _bounded_int(args.offset, 0, 0, 10_000),
            },
        )
    if command == "media-summary":
        return client.get("/v1/media/summary")
    if command == "media-sync":
        return client.post("/v1/media/sync")
    if command == "transcript":
        media_id = _clean_media_id(args.media_id)
        return client.get(f"/v1/transcripts/{media_id}", query={"limit": _bounded_int(args.limit, 1000, 1, 5000)})
    if command == "transcript-search":
        media_id = _clean_media_id(args.media_id) if args.media_id else ""
        return client.get(
            "/v1/transcripts/search",
            query={
                "q": args.query,
                "mediaId": media_id,
                "speaker": args.speaker,
                "startSeconds": args.start,
                "endSeconds": args.end,
                "limit": _bounded_int(args.limit, 100, 1, 500),
            },
        )
    if command == "transcript-index":
        return client.post(f"/v1/transcripts/{_clean_media_id(args.media_id)}/index")
    if command == "transcript-relabel":
        return client.post(
            f"/v1/transcripts/{_clean_media_id(args.media_id)}/speakers/relabel",
            payload={"oldLabel": args.old_label, "newLabel": args.new_label},
        )
    if command == "transcript-export":
        return client.post(
            f"/v1/transcripts/{_clean_media_id(args.media_id)}/export",
            payload={"format": args.format, "basename": args.basename, "includeSpeaker": not args.no_speaker},
        )
    if command == "subscriptions":
        return client.get("/v1/subscriptions")
    if command == "subscription":
        return client.get(f"/v1/subscriptions/{args.subscription_id}")
    if command == "subscription-create":
        return client.post(
            "/v1/subscriptions",
            payload={
                "sourceUrl": args.source_url,
                "title": args.title,
                "browser": args.browser,
                "intervalMinutes": args.interval,
                "autoDownload": bool(args.auto_download),
                "enabled": not args.disabled,
                "videoQuality": args.video_quality,
                "audioQuality": args.audio_quality,
                "includeAudio": not args.video_only,
            },
        )
    if command == "subscription-update":
        payload = _subscription_update_payload(args)
        if not payload:
            raise GalaxyCliError("subscription-update requires at least one changed field")
        return client.post(f"/v1/subscriptions/{args.subscription_id}/update", payload=payload)
    if command == "subscription-delete":
        return client.post(f"/v1/subscriptions/{args.subscription_id}/delete")
    if command == "subscription-rules":
        return client.get(f"/v1/subscriptions/{args.subscription_id}/rules")
    if command == "subscription-set-rules":
        payload = _subscription_rules_payload(args)
        if not payload:
            raise GalaxyCliError("subscription-set-rules requires at least one changed rule")
        return client.post(f"/v1/subscriptions/{args.subscription_id}/rules", payload=payload)
    if command == "subscription-items":
        present = "" if args.present == "any" else args.present
        return client.get(
            f"/v1/subscriptions/{args.subscription_id}/items",
            query={"state": args.state, "present": present, "limit": _bounded_int(args.limit, 200, 1, 500)},
        )
    if command == "subscription-counts":
        return client.get(f"/v1/subscriptions/{args.subscription_id}/counts")
    if command == "subscription-transition":
        return client.post(
            f"/v1/subscriptions/{args.subscription_id}/items/transition",
            payload={"entryId": args.entry_id, "state": args.state, "reason": args.reason},
        )
    if command == "subscription-reconcile":
        return client.post(
            f"/v1/subscriptions/{args.subscription_id}/reconcile",
            payload={"retryFailed": bool(args.retry_failed), "maxAttempts": _bounded_int(args.max_attempts, 3, 1, 20)},
        )
    raise GalaxyCliError(f"unsupported command: {command}")


def run_cli(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None) -> tuple[argparse.Namespace, dict[str, Any]]:
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    env = os.environ if environ is None else environ
    token = str(env.get("GALAXY_HEADLESS_TOKEN") or "")
    api_url = args.api_url
    if environ is not None and "--api-url" not in (argv or ()):
        api_url = str(env.get("GALAXY_HEADLESS_URL") or DEFAULT_API_URL)
    client = GalaxyApiClient(api_url, token=token, timeout_seconds=args.timeout)
    return args, execute(args, client)


def _print_payload(payload: dict[str, Any], *, machine_json: bool) -> None:
    if machine_json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args, payload = run_cli(argv)
        _print_payload(payload, machine_json=bool(args.json))
        return 0
    except GalaxyApiError as exc:
        print(f"API {exc.status}: {exc.detail}", file=sys.stderr)
        return 3
    except GalaxyTransportError as exc:
        print(f"Transport error: {_safe_detail(exc)}", file=sys.stderr)
        return 4
    except GalaxyCliError as exc:
        print(f"CLI error: {_safe_detail(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
