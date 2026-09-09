from __future__ import annotations

import json
import math
import re
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

MAX_INFO_JSON_BYTES = 8 * 1024 * 1024
MAX_TITLE_CHARS = 500
MAX_DESCRIPTION_CHARS = 12_000
MAX_STUDIO_CHARS = 300
MAX_ID_CHARS = 200
MAX_LIST_ITEMS = 64
MAX_LIST_ITEM_CHARS = 160
MAX_THUMBNAIL_URL_CHARS = 2_000
MAX_SEASON_NUMBER = 9_999
MAX_EPISODE_NUMBER = 999_999
EXTRACTOR_TYPE_RE = re.compile(r"[^a-z0-9_-]+")


class NfoSidecarError(RuntimeError):
    pass


def _bounded_text(value: object, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit]


def _bounded_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    raw_values = sorted(value, key=lambda item: str(item)) if isinstance(value, set) else value
    result: list[str] = []
    for raw in raw_values:
        item = _bounded_text(raw, MAX_LIST_ITEM_CHARS)
        if not item or item in result:
            continue
        result.append(item)
        if len(result) >= MAX_LIST_ITEMS:
            break
    return tuple(result)


def _safe_thumbnail_url(value: object) -> str:
    text = _bounded_text(value, MAX_THUMBNAIL_URL_CHARS)
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def _normalized_date(value: object) -> str:
    text = _bounded_text(value, 32)
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    return ""


def _runtime_minutes(value: object) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(seconds) or seconds <= 0 or seconds > 31 * 24 * 60 * 60:
        return ""
    return str(max(1, int(round(seconds / 60))))


def _bounded_nonnegative_integer(value: object, maximum: int) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return ""
        number = int(value)
    else:
        text = _bounded_text(value, 16)
        if not re.fullmatch(r"\d+", text):
            return ""
        number = int(text)
    if number < 0 or number > maximum:
        return ""
    return str(number)


def _episode_metadata(info: dict[str, Any]) -> tuple[bool, str, str, str, str, str]:
    series = _bounded_text(info.get("series"), MAX_TITLE_CHARS)
    episode_title = _bounded_text(info.get("episode"), MAX_TITLE_CHARS)
    episode_id = _bounded_text(info.get("episode_id"), MAX_ID_CHARS)
    season_number = _bounded_nonnegative_integer(info.get("season_number"), MAX_SEASON_NUMBER)
    episode_number = _bounded_nonnegative_integer(info.get("episode_number"), MAX_EPISODE_NUMBER)
    is_episode = bool(series and (episode_title or episode_id or episode_number))
    return is_episode, series, episode_title, episode_id, season_number, episode_number


def _extractor_id_type(info: dict[str, Any]) -> str:
    raw = _bounded_text(info.get("extractor_key") or info.get("extractor"), 80).lower()
    if "bilibili" in raw:
        return "bilibili"
    cleaned = EXTRACTOR_TYPE_RE.sub("-", raw).strip("-")[:32]
    return cleaned or "media"


def parse_info_json(value: bytes | str) -> dict[str, Any]:
    if isinstance(value, bytes):
        raw = value
    else:
        raw = str(value).encode("utf-8")
    if not raw:
        raise NfoSidecarError("metadata JSON is empty")
    if len(raw) > MAX_INFO_JSON_BYTES:
        raise NfoSidecarError("metadata JSON exceeds the 8 MiB safety limit")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NfoSidecarError("metadata JSON is not valid UTF-8") from exc
    try:
        payload = json.loads(decoded)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise NfoSidecarError("metadata JSON is malformed") from exc
    if not isinstance(payload, dict):
        raise NfoSidecarError("metadata JSON root must be an object")
    return payload


def _append_text(parent: ET.Element, tag: str, text: str, **attributes: str) -> None:
    if not text:
        return
    child = ET.SubElement(parent, tag, attributes)
    child.text = text


def render_nfo(info: dict[str, Any]) -> str:
    is_episode, series, episode_title, episode_id, season_number, episode_number = _episode_metadata(info)
    root = ET.Element("episodedetails" if is_episode else "movie")

    title = _bounded_text(
        (episode_title if is_episode else None)
        or info.get("title")
        or info.get("fulltitle")
        or info.get("id"),
        MAX_TITLE_CHARS,
    )
    if not title:
        raise NfoSidecarError("metadata does not contain a usable title")
    _append_text(root, "title", title)

    if is_episode:
        _append_text(root, "showtitle", series)
        _append_text(root, "season", season_number)
        _append_text(root, "episode", episode_number)

    description = _bounded_text(info.get("description"), MAX_DESCRIPTION_CHARS)
    _append_text(root, "plot", description)

    studio = _bounded_text(
        info.get("channel") or info.get("uploader") or info.get("creator"),
        MAX_STUDIO_CHARS,
    )
    _append_text(root, "studio", studio)

    release_date = _normalized_date(info.get("release_date") or info.get("upload_date"))
    _append_text(root, "aired" if is_episode else "premiered", release_date)

    runtime = _runtime_minutes(info.get("duration"))
    _append_text(root, "runtime", runtime)

    media_id = episode_id if is_episode and episode_id else _bounded_text(info.get("id"), MAX_ID_CHARS)
    if media_id:
        _append_text(
            root,
            "uniqueid",
            media_id,
            type=_extractor_id_type(info),
            default="true",
        )

    for category in _bounded_list(info.get("categories")):
        _append_text(root, "genre", category)
    for tag in _bounded_list(info.get("tags")):
        _append_text(root, "tag", tag)

    thumbnail = _safe_thumbnail_url(info.get("thumbnail"))
    _append_text(root, "thumb", thumbnail)

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'


def nfo_output_path(info_json_path: Path) -> Path:
    path = Path(info_json_path)
    suffix = ".info.json"
    if path.name.lower().endswith(suffix):
        return path.with_name(f"{path.name[:-len(suffix)]}.nfo")
    return path.with_suffix(".nfo")


def convert_info_json_file(
    info_json_path: Path,
    *,
    remove_source: bool = False,
) -> Path:
    source = Path(info_json_path)
    try:
        if source.is_symlink() or not source.is_file():
            raise NfoSidecarError("metadata JSON input must be a regular file")
        if source.stat().st_size > MAX_INFO_JSON_BYTES:
            raise NfoSidecarError("metadata JSON exceeds the 8 MiB safety limit")
        raw = source.read_bytes()
    except OSError as exc:
        raise NfoSidecarError(f"could not read metadata JSON: {exc}") from exc

    target = nfo_output_path(source)
    if target.is_symlink():
        raise NfoSidecarError("refusing to replace a symlinked NFO output")

    text = render_nfo(parse_info_json(raw))
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        temporary.replace(target)
        temporary = None
        if remove_source:
            source.unlink()
        return target
    except OSError as exc:
        raise NfoSidecarError(f"could not write NFO sidecar: {exc}") from exc
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink()


def run_nfo_sidecar_self_test() -> None:
    info = {
        "id": "BV1demo",
        "extractor_key": "BiliBili",
        "title": "Demo & <video>",
        "description": "Line one & line two",
        "uploader": "Demo UP",
        "upload_date": "20260909",
        "duration": 125,
        "categories": ["Technology"],
        "tags": ["demo", "demo", "test"],
        "thumbnail": "https://i.example.test/cover.jpg",
    }
    rendered = render_nfo(info)
    assert rendered.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<movie>')
    assert "<title>Demo &amp; &lt;video&gt;</title>" in rendered
    assert '<uniqueid type="bilibili" default="true">BV1demo</uniqueid>' in rendered
    assert "<premiered>2026-09-09</premiered>" in rendered
    assert "<runtime>2</runtime>" in rendered
    assert rendered.count("<tag>demo</tag>") == 1

    episode = {
        "id": "267851",
        "extractor_key": "BiliBiliBangumi",
        "title": "1 残酷",
        "series": "鬼灭之刃",
        "series_id": "4358",
        "season": "立志篇",
        "season_id": "26801",
        "season_number": 1,
        "episode": "残酷",
        "episode_id": "267851",
        "episode_number": 1,
        "upload_date": "20190406",
        "duration": 1425.256,
    }
    rendered_episode = render_nfo(episode)
    assert rendered_episode.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<episodedetails>')
    assert "<title>残酷</title>" in rendered_episode
    assert "<showtitle>鬼灭之刃</showtitle>" in rendered_episode
    assert "<season>1</season>" in rendered_episode
    assert "<episode>1</episode>" in rendered_episode
    assert "<aired>2019-04-06</aired>" in rendered_episode
    assert '<uniqueid type="bilibili" default="true">267851</uniqueid>' in rendered_episode
