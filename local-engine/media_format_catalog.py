from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

_FORMAT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_VIDEO_OPTIONS = 40
MAX_AUDIO_OPTIONS = 30


class MediaFormatError(ValueError):
    pass


@dataclass(frozen=True)
class MediaFormatOption:
    id: str
    format_id: str
    label: str
    stream_type: str
    extension: str | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    video_bitrate: float | None
    audio_bitrate: float | None
    total_bitrate: float | None
    filesize: int | None
    filesize_approx: int | None
    dynamic_range: str | None
    protocol: str | None
    language: str | None
    audio_channels: int | None
    sample_rate: int | None
    format_note: str | None
    feature_tags: tuple[str, ...]


@dataclass(frozen=True)
class MediaFormatCatalog:
    video_options: tuple[MediaFormatOption, ...]
    audio_options: tuple[MediaFormatOption, ...]
    default_video_id: str | None
    default_audio_id: str | None


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _int(value: object) -> int | None:
    number = _number(value)
    return int(round(number)) if number is not None else None


def _text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _codec(value: object) -> str | None:
    text = _text(value)
    if text is None or text.lower() == "none":
        return None
    return text


def _has_video(item: dict[str, Any]) -> bool:
    return _codec(item.get("vcodec")) is not None


def _has_audio(item: dict[str, Any]) -> bool:
    return _codec(item.get("acodec")) is not None


def _has_download_url(item: dict[str, Any]) -> bool:
    value = item.get("url")
    return isinstance(value, str) and bool(value.strip())


def validate_format_id(value: object) -> str:
    format_id = str(value or "").strip()
    if not _FORMAT_ID_PATTERN.fullmatch(format_id):
        raise MediaFormatError(f"unsafe or unsupported media format id: {format_id or '<empty>'}")
    return format_id


def _stream_type(item: dict[str, Any]) -> str:
    has_video = _has_video(item)
    has_audio = _has_audio(item)
    if has_video and has_audio:
        return "muxed"
    if has_video:
        return "video-only"
    if has_audio:
        return "audio-only"
    return "unknown"


def _filesize(item: dict[str, Any], key: str) -> int | None:
    value = _int(item.get(key))
    return value if value is not None and value > 0 else None


def _format_note(item: dict[str, Any]) -> str | None:
    return _text(item.get("format_note") or item.get("format"))


def _feature_text(item: dict[str, Any]) -> str:
    values = (
        item.get("format_note"),
        item.get("format"),
        item.get("format_id"),
        item.get("dynamic_range"),
        item.get("vcodec"),
        item.get("acodec"),
        item.get("resolution"),
    )
    return " ".join(str(value) for value in values if value is not None).strip().lower()


def _feature_tags(item: dict[str, Any], *, media_kind: str) -> tuple[str, ...]:
    """Derive only capabilities that are evidenced by extractor metadata.

    Bilibili exposes premium variants through height/dynamic-range/format-note
    metadata. The same conservative rules are useful for other yt-dlp sources,
    so the format catalog stays platform-neutral: a capability is advertised
    only when the returned format itself contains evidence for it. Codec names
    such as E-AC-3 alone are intentionally not treated as Atmos, and generic
    high sample rates are intentionally not treated as Hi-Res.
    """
    text = _feature_text(item)
    result: list[str] = []

    def add(tag: str) -> None:
        if tag not in result:
            result.append(tag)

    if media_kind == "video":
        height = _int(item.get("height")) or 0
        if height >= 4320:
            add("8k")
        elif height >= 2160:
            add("4k")

        dynamic_range = str(item.get("dynamic_range") or "").strip().lower()
        dolby_vision = any(
            marker in text
            for marker in (
                "dolby vision",
                "dolbyvision",
                "杜比视界",
                "dvhe",
                "dvh1",
            )
        ) or dynamic_range in {"dv", "dovi", "dolby vision"}
        hdr = dolby_vision or any(
            marker in text
            for marker in (
                "hdr",
                "hdr10",
                "hlg",
                "hdr 真彩",
                "hdr真彩",
            )
        )
        if dolby_vision:
            add("dolby-vision")
        if hdr:
            add("hdr")

    if media_kind == "audio":
        if any(
            marker in text
            for marker in (
                "hi-res",
                "hi res",
                "hires",
                "hi‐res",
                "高解析",
            )
        ):
            add("hi-res")
        if any(marker in text for marker in ("dolby atmos", "atmos", "杜比全景声")):
            add("dolby-atmos")

    return tuple(result)


def _video_label(item: dict[str, Any], format_id: str) -> str:
    parts: list[str] = []
    height = _int(item.get("height"))
    width = _int(item.get("width"))
    if height and height > 0:
        parts.append(f"{height}p")
    elif width and width > 0:
        parts.append(f"{width}px")
    else:
        parts.append(format_id)

    fps = _number(item.get("fps"))
    if fps and fps > 30:
        rounded = int(round(fps)) if abs(fps - round(fps)) < 0.01 else round(fps, 2)
        parts.append(f"{rounded}fps")

    feature_tags = _feature_tags(item, media_kind="video")
    if "8k" in feature_tags:
        parts.append("8K")
    elif "4k" in feature_tags:
        parts.append("4K")
    if "dolby-vision" in feature_tags:
        parts.append("DOLBY VISION")
    elif "hdr" in feature_tags:
        dynamic_range = _text(item.get("dynamic_range"))
        parts.append(dynamic_range.upper() if dynamic_range else "HDR")

    vcodec = _codec(item.get("vcodec"))
    if vcodec:
        parts.append(vcodec.split(".", 1)[0].upper())

    ext = _text(item.get("ext"))
    if ext:
        parts.append(ext.upper())

    if _has_audio(item):
        parts.append("含音频")
    return " · ".join(parts)


def _audio_label(item: dict[str, Any], format_id: str) -> str:
    parts: list[str] = []
    abr = _number(item.get("abr"))
    if abr and abr > 0:
        parts.append(f"{int(round(abr))} kbps")
    else:
        parts.append(format_id)

    feature_tags = _feature_tags(item, media_kind="audio")
    if "hi-res" in feature_tags:
        parts.append("HI-RES")
    if "dolby-atmos" in feature_tags:
        parts.append("DOLBY ATMOS")

    acodec = _codec(item.get("acodec"))
    if acodec:
        parts.append(acodec.split(".", 1)[0].upper())

    ext = _text(item.get("ext"))
    if ext:
        parts.append(ext.upper())

    language = _text(item.get("language"))
    if language:
        parts.append(language)
    return " · ".join(parts)


def _option(item: dict[str, Any], *, media_kind: str) -> MediaFormatOption:
    format_id = validate_format_id(item.get("format_id"))
    label = _video_label(item, format_id) if media_kind == "video" else _audio_label(item, format_id)
    return MediaFormatOption(
        id=f"{media_kind}:{format_id}",
        format_id=format_id,
        label=label,
        stream_type=_stream_type(item),
        extension=_text(item.get("ext")),
        width=_int(item.get("width")),
        height=_int(item.get("height")),
        fps=_number(item.get("fps")),
        video_codec=_codec(item.get("vcodec")),
        audio_codec=_codec(item.get("acodec")),
        video_bitrate=_number(item.get("vbr")),
        audio_bitrate=_number(item.get("abr")),
        total_bitrate=_number(item.get("tbr")),
        filesize=_filesize(item, "filesize"),
        filesize_approx=_filesize(item, "filesize_approx"),
        dynamic_range=_text(item.get("dynamic_range")),
        protocol=_text(item.get("protocol")),
        language=_text(item.get("language")),
        audio_channels=_int(item.get("audio_channels")),
        sample_rate=_int(item.get("asr")),
        format_note=_format_note(item),
        feature_tags=_feature_tags(item, media_kind=media_kind),
    )


def _video_score(item: dict[str, Any]) -> tuple[float, float, float, float, float]:
    return (
        _number(item.get("height")) or 0.0,
        _number(item.get("fps")) or 0.0,
        _number(item.get("vbr")) or _number(item.get("tbr")) or 0.0,
        1.0 if not _has_audio(item) else 0.0,
        _number(item.get("filesize") or item.get("filesize_approx")) or 0.0,
    )


def _audio_score(item: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        _number(item.get("abr")) or _number(item.get("tbr")) or 0.0,
        _number(item.get("asr")) or 0.0,
        _number(item.get("audio_channels")) or 0.0,
        _number(item.get("filesize") or item.get("filesize_approx")) or 0.0,
    )


def _dedupe_sorted(
    items: Iterable[dict[str, Any]],
    *,
    media_kind: str,
    limit: int,
) -> tuple[MediaFormatOption, ...]:
    score = _video_score if media_kind == "video" else _audio_score
    candidates = sorted(items, key=score, reverse=True)
    result: list[MediaFormatOption] = []
    seen: set[str] = set()
    for item in candidates:
        try:
            option = _option(item, media_kind=media_kind)
        except MediaFormatError:
            continue
        if option.format_id in seen:
            continue
        seen.add(option.format_id)
        result.append(option)
        if len(result) >= limit:
            break
    return tuple(result)


def build_media_format_catalog(
    formats: object,
    *,
    max_video_options: int = MAX_VIDEO_OPTIONS,
    max_audio_options: int = MAX_AUDIO_OPTIONS,
) -> MediaFormatCatalog:
    if max_video_options <= 0 or max_audio_options <= 0:
        raise MediaFormatError("media format catalog limits must be positive")
    source = formats if isinstance(formats, list) else []
    valid = [item for item in source if isinstance(item, dict) and _has_download_url(item)]

    video_items = [item for item in valid if _has_video(item)]
    audio_items = [item for item in valid if _has_audio(item) and not _has_video(item)]
    video_options = _dedupe_sorted(video_items, media_kind="video", limit=max_video_options)
    audio_options = _dedupe_sorted(audio_items, media_kind="audio", limit=max_audio_options)
    return MediaFormatCatalog(
        video_options=video_options,
        audio_options=audio_options,
        default_video_id=video_options[0].id if video_options else None,
        default_audio_id=audio_options[0].id if audio_options else None,
    )


def exact_format_selector(
    *,
    video_format_id: object | None = None,
    audio_format_id: object | None = None,
    include_audio: bool = True,
    selected_video_has_audio: bool = False,
) -> str:
    video = validate_format_id(video_format_id) if video_format_id is not None else None
    audio = validate_format_id(audio_format_id) if audio_format_id is not None else None
    if video is None and audio is None:
        raise MediaFormatError("at least one exact media format id is required")
    if video is None:
        return audio or ""
    if not include_audio or selected_video_has_audio or audio is None:
        return video
    return f"{video}+{audio}"


def public_media_format_option(option: MediaFormatOption) -> dict[str, object]:
    payload = asdict(option)
    return {
        "id": payload["id"],
        "formatId": payload["format_id"],
        "label": payload["label"],
        "streamType": payload["stream_type"],
        "extension": payload["extension"],
        "width": payload["width"],
        "height": payload["height"],
        "fps": payload["fps"],
        "videoCodec": payload["video_codec"],
        "audioCodec": payload["audio_codec"],
        "videoBitrate": payload["video_bitrate"],
        "audioBitrate": payload["audio_bitrate"],
        "totalBitrate": payload["total_bitrate"],
        "filesize": payload["filesize"],
        "filesizeApprox": payload["filesize_approx"],
        "dynamicRange": payload["dynamic_range"],
        "protocol": payload["protocol"],
        "language": payload["language"],
        "audioChannels": payload["audio_channels"],
        "sampleRate": payload["sample_rate"],
        "formatNote": payload["format_note"],
        "featureTags": list(payload["feature_tags"]),
    }


def public_media_format_catalog(catalog: MediaFormatCatalog) -> dict[str, object]:
    return {
        "videoOptions": [public_media_format_option(item) for item in catalog.video_options],
        "audioOptions": [public_media_format_option(item) for item in catalog.audio_options],
        "defaultVideoId": catalog.default_video_id,
        "defaultAudioId": catalog.default_audio_id,
    }


def run_media_format_catalog_self_test() -> None:
    catalog = build_media_format_catalog(
        [
            {
                "format_id": "137",
                "url": "https://media.example/video",
                "vcodec": "avc1.640028",
                "acodec": "none",
                "height": 1080,
                "fps": 30,
                "ext": "mp4",
                "vbr": 4500,
            },
            {
                "format_id": "251",
                "url": "https://media.example/audio",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 160,
                "ext": "webm",
            },
        ]
    )
    assert catalog.default_video_id == "video:137"
    assert catalog.default_audio_id == "audio:251"
    assert exact_format_selector(video_format_id="137", audio_format_id="251") == "137+251"
    public = public_media_format_catalog(catalog)
    assert "downloadUrl" not in str(public)

    premium = build_media_format_catalog(
        [
            {
                "format_id": "bili-8k-dv",
                "url": "https://media.example/8k",
                "vcodec": "hev1",
                "acodec": "none",
                "height": 4320,
                "dynamic_range": "DV",
                "format_note": "8K 超高清 杜比视界",
            },
            {
                "format_id": "bili-hires",
                "url": "https://media.example/hires",
                "vcodec": "none",
                "acodec": "flac",
                "format_note": "Hi-Res无损",
            },
        ]
    )
    assert premium.video_options[0].feature_tags == ("8k", "dolby-vision", "hdr")
    assert premium.audio_options[0].feature_tags == ("hi-res",)
