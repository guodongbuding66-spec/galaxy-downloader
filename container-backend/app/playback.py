from __future__ import annotations

import asyncio
import os
import urllib.parse
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse

from . import main as core

router = APIRouter()

PLAYBACK_CONCURRENCY = max(1, int(os.getenv("PLAYBACK_CONCURRENCY", "8")))
PLAYBACK_QUEUE_TIMEOUT_SECONDS = max(
    0.1,
    float(os.getenv("PLAYBACK_QUEUE_TIMEOUT_SECONDS", "10")),
)
PLAYBACK_MAX_REDIRECTS = max(0, min(8, int(os.getenv("PLAYBACK_MAX_REDIRECTS", "4"))))
PLAYBACK_CONNECT_TIMEOUT_SECONDS = max(
    1.0,
    float(os.getenv("PLAYBACK_CONNECT_TIMEOUT_SECONDS", "15")),
)
PLAYBACK_READ_TIMEOUT_SECONDS = max(
    5.0,
    float(os.getenv("PLAYBACK_READ_TIMEOUT_SECONDS", "60")),
)

playback_slots = asyncio.Semaphore(PLAYBACK_CONCURRENCY)

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SAFE_UPSTREAM_REQUEST_HEADERS = {
    "accept",
    "accept-language",
    "origin",
    "referer",
    "user-agent",
}
_SAFE_UPSTREAM_RESPONSE_HEADERS = {
    "accept-ranges",
    "content-length",
    "content-range",
    "content-type",
    "etag",
    "last-modified",
}
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _direct_http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate.startswith(("https://", "http://")):
        return None
    try:
        parsed = urllib.parse.urlsplit(candidate)
    except ValueError:
        return None
    if not parsed.hostname:
        return None
    path = parsed.path.lower()
    if path.endswith(".m3u8") or path.endswith(".mpd"):
        return None
    return candidate


def _is_progressive_format(fmt: dict[str, Any]) -> bool:
    if not _direct_http_url(fmt.get("url")):
        return False
    protocol = str(fmt.get("protocol") or "").lower()
    return not any(marker in protocol for marker in ("m3u8", "dash", "ism"))


def _video_score(fmt: dict[str, Any]) -> tuple[int, int, float, float, float]:
    ext = str(fmt.get("ext") or "").lower()
    compatibility = 2 if ext == "mp4" else 1 if ext == "webm" else 0
    return (
        compatibility,
        int(_number(fmt.get("height"))),
        _number(fmt.get("fps")),
        _number(fmt.get("tbr")),
        _number(fmt.get("filesize") or fmt.get("filesize_approx")),
    )


def _audio_score(fmt: dict[str, Any]) -> tuple[int, float, float, float]:
    ext = str(fmt.get("ext") or "").lower()
    compatibility = 2 if ext in {"m4a", "mp3", "aac"} else 1 if ext in {"webm", "opus", "ogg"} else 0
    return (
        compatibility,
        _number(fmt.get("abr")),
        _number(fmt.get("tbr")),
        _number(fmt.get("filesize") or fmt.get("filesize_approx")),
    )


def _preview_candidate(info: dict[str, Any], media_type: str) -> dict[str, Any] | None:
    formats = [
        fmt
        for fmt in info.get("formats") or []
        if isinstance(fmt, dict) and _is_progressive_format(fmt)
    ]

    # Some extractors put the selected progressive media on the top-level JSON
    # rather than repeating it in formats. Treat that as another candidate.
    if _is_progressive_format(info):
        formats.append(info)

    if media_type == "audio":
        audio_only = [
            fmt
            for fmt in formats
            if core.format_has_audio(fmt) and not core.format_has_video(fmt)
        ]
        if audio_only:
            return max(audio_only, key=_audio_score)
        muxed = [fmt for fmt in formats if core.format_has_audio(fmt)]
        return max(muxed, key=_audio_score, default=None)

    # Preview prefers a single muxed progressive stream. It may be lower than
    # the final download quality, but it starts immediately and carries audio.
    # Final-file downloads continue to use best video + best audio + FFmpeg.
    muxed = [
        fmt
        for fmt in formats
        if core.format_has_video(fmt) and core.format_has_audio(fmt)
    ]
    if muxed:
        return max(muxed, key=_video_score)
    return None


def _format_request_headers(info: dict[str, Any], fmt: dict[str, Any]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for source in (info.get("http_headers"), fmt.get("http_headers")):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            normalized = str(key).lower()
            if normalized not in _SAFE_UPSTREAM_REQUEST_HEADERS:
                continue
            if isinstance(value, str) and value.strip():
                merged[key] = value.strip()

    if not any(key.lower() == "user-agent" for key in merged):
        merged["User-Agent"] = _DEFAULT_USER_AGENT
    merged.setdefault("Accept", "*/*")
    return merged


def _fallback_download_url(source_url: str, media_type: str) -> str:
    query = urllib.parse.urlencode(
        {
            "url": source_url,
            "type": media_type,
            "quality": "best",
        }
    )
    return f"/api/download?{query}"


async def _resolve_preview(
    source_url: str,
    media_type: str,
) -> tuple[str, dict[str, str]] | None:
    if not await core.acquire_capacity(core.parse_slots, core.PARSE_QUEUE_TIMEOUT_SECONDS):
        raise TimeoutError("Parser capacity is busy")
    try:
        info = await asyncio.to_thread(core.parse_with_ytdlp, source_url)
    finally:
        core.parse_slots.release()

    candidate = _preview_candidate(info, media_type)
    if not candidate:
        return None
    target = _direct_http_url(candidate.get("url"))
    if not target:
        return None
    return target, _format_request_headers(info, candidate)


async def _open_validated_upstream(
    target_url: str,
    method: str,
    headers: dict[str, str],
) -> tuple[httpx.AsyncClient, httpx.Response]:
    timeout = httpx.Timeout(
        connect=PLAYBACK_CONNECT_TIMEOUT_SECONDS,
        read=PLAYBACK_READ_TIMEOUT_SECONDS,
        write=PLAYBACK_READ_TIMEOUT_SECONDS,
        pool=PLAYBACK_CONNECT_TIMEOUT_SECONDS,
    )
    client = httpx.AsyncClient(
        follow_redirects=False,
        timeout=timeout,
        trust_env=False,
    )
    current = target_url

    try:
        for redirect_index in range(PLAYBACK_MAX_REDIRECTS + 1):
            # Revalidate every hop. This blocks obvious private/reserved redirect
            # targets and keeps the relay from becoming a generic open proxy.
            current = await asyncio.to_thread(core.validate_public_source_url, current)
            request = client.build_request(method, current, headers=headers)
            response = await client.send(request, stream=True)

            if response.status_code not in _REDIRECT_STATUSES:
                return client, response

            location = response.headers.get("location", "").strip()
            if not location or redirect_index >= PLAYBACK_MAX_REDIRECTS:
                return client, response

            await response.aclose()
            current = urllib.parse.urljoin(current, location)
    except Exception:
        await client.aclose()
        raise

    await client.aclose()
    raise RuntimeError("Playback redirect resolution failed")


def _response_headers(upstream: httpx.Response, request_id: str) -> dict[str, str]:
    headers: dict[str, str] = {
        "X-Request-Id": request_id,
        "Cache-Control": "private, no-store",
        "Cross-Origin-Resource-Policy": "cross-origin",
        "X-Content-Type-Options": "nosniff",
    }
    for key, value in upstream.headers.items():
        if key.lower() in _SAFE_UPSTREAM_RESPONSE_HEADERS:
            headers[key] = value
    return headers


async def _relay_body(
    upstream: httpx.Response,
    client: httpx.AsyncClient,
) -> AsyncIterator[bytes]:
    try:
        async for chunk in upstream.aiter_raw():
            if chunk:
                yield chunk
    finally:
        await upstream.aclose()
        await client.aclose()
        playback_slots.release()


@router.api_route("/api/play", methods=["GET", "HEAD"])
async def play_media(
    request: Request,
    url: str = Query(..., min_length=8, max_length=core.MAX_SOURCE_URL_LENGTH),
    media_type: str = Query(default="video", alias="type"),
    x_request_id: str | None = Header(default=None),
):
    if media_type not in {"video", "audio"}:
        return core.api_error_response(
            "BAD_REQUEST",
            400,
            "type must be video or audio",
            x_request_id or "unknown",
        )

    request_id = x_request_id or "unknown"
    try:
        source_url = await asyncio.to_thread(core.validate_public_source_url, url)
    except Exception as exc:
        if hasattr(exc, "status_code"):
            return core.api_error_response(
                "BAD_REQUEST",
                int(getattr(exc, "status_code", 400)),
                str(getattr(exc, "detail", "Invalid source URL")),
                request_id,
            )
        return core.api_error_response("BAD_REQUEST", 400, "Invalid source URL", request_id)

    try:
        resolved = await _resolve_preview(source_url, media_type)
    except TimeoutError:
        return core.api_error_response(
            "BACKEND_BUSY",
            503,
            "Playback parser capacity is busy. Please retry shortly.",
            request_id,
            retry_after=5,
        )
    except Exception as exc:
        if hasattr(exc, "status_code"):
            status = int(getattr(exc, "status_code", 502))
            detail = core.public_error_message(exc, "playback")
            return core.api_error_response("PLAYBACK_FAILED", status, detail, request_id)
        return core.api_error_response(
            "PLAYBACK_FAILED",
            502,
            "Media provider playback resolution failed upstream.",
            request_id,
        )

    # If the provider exposes only separate DASH streams, keep the old merged
    # download path as a compatibility fallback. Progressive/muxed providers use
    # the range-aware relay below and start without downloading the whole file.
    if not resolved:
        return RedirectResponse(
            _fallback_download_url(source_url, media_type),
            status_code=307,
            headers={"X-Request-Id": request_id, "Cache-Control": "no-store"},
        )

    if not await core.acquire_capacity(playback_slots, PLAYBACK_QUEUE_TIMEOUT_SECONDS):
        return core.api_error_response(
            "BACKEND_BUSY",
            503,
            "Playback capacity is busy. Please retry shortly.",
            request_id,
            retry_after=5,
        )

    target_url, upstream_headers = resolved
    incoming_range = request.headers.get("range", "").strip()
    if incoming_range:
        upstream_headers["Range"] = incoming_range

    client: httpx.AsyncClient | None = None
    upstream: httpx.Response | None = None
    try:
        client, upstream = await _open_validated_upstream(
            target_url,
            request.method,
            upstream_headers,
        )
        headers = _response_headers(upstream, request_id)

        if request.method == "HEAD":
            status_code = upstream.status_code
            await upstream.aclose()
            await client.aclose()
            playback_slots.release()
            return Response(status_code=status_code, headers=headers)

        if upstream.status_code >= 400:
            status_code = upstream.status_code
            await upstream.aclose()
            await client.aclose()
            playback_slots.release()
            return core.api_error_response(
                "PLAYBACK_UPSTREAM_FAILED",
                502 if status_code >= 500 else status_code,
                f"Playback media returned HTTP {status_code}.",
                request_id,
            )

        return StreamingResponse(
            _relay_body(upstream, client),
            status_code=upstream.status_code,
            headers=headers,
        )
    except Exception:
        if upstream is not None:
            await upstream.aclose()
        if client is not None:
            await client.aclose()
        playback_slots.release()
        return core.api_error_response(
            "PLAYBACK_FAILED",
            502,
            "Unable to relay the resolved media stream.",
            request_id,
        )
