from __future__ import annotations

import json
import math
import os
import re
import xml.etree.ElementTree as ET
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Collection, Sequence

MAX_XML_BYTES = 32 * 1024 * 1024
MAX_COMMENTS = 100_000
MAX_TEXT_CHARS = 500
MAX_ASS_DIMENSION = 7680
DEFAULT_ASS_WIDTH = 1920
DEFAULT_ASS_HEIGHT = 1080
SCROLL_DURATION_SECONDS = 8.0
FIXED_DURATION_SECONDS = 5.0
MIN_FONT_SIZE = 12
MAX_FONT_SIZE = 96
DANGEROUS_XML_RE = re.compile(br"<!\s*(?:doctype|entity)\b", re.IGNORECASE)
SUPPORTED_OUTPUT_FORMATS = frozenset({"ass", "json"})


class BilibiliDanmakuConversionError(ValueError):
    pass


@dataclass(frozen=True)
class DanmakuComment:
    time: float
    mode: int
    font_size: int
    color: int
    timestamp: int | None
    pool: int | None
    user_hash: str | None
    row_id: str | None
    text: str


def _bounded_xml_bytes(data: bytes | str) -> bytes:
    if isinstance(data, str):
        encoded = data.encode("utf-8")
    elif isinstance(data, bytes):
        encoded = data
    else:
        raise BilibiliDanmakuConversionError("danmaku XML must be bytes or text")
    if not encoded:
        raise BilibiliDanmakuConversionError("danmaku XML is empty")
    if len(encoded) > MAX_XML_BYTES:
        raise BilibiliDanmakuConversionError(
            f"danmaku XML exceeds the {MAX_XML_BYTES} byte safety limit"
        )
    if DANGEROUS_XML_RE.search(encoded):
        raise BilibiliDanmakuConversionError("DOCTYPE/ENTITY declarations are not allowed")
    return encoded


def _optional_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_comment(element: ET.Element) -> DanmakuComment | None:
    raw = str(element.attrib.get("p") or "")
    fields = raw.split(",")
    if len(fields) < 4:
        return None
    try:
        time_value = float(fields[0])
        mode = int(fields[1])
        font_size = int(fields[2])
        color = int(fields[3])
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(time_value) or time_value < 0:
        return None
    if color < 0 or color > 0xFFFFFF:
        return None
    text = "".join(element.itertext()).replace("\x00", "").strip()
    if not text:
        return None
    text = text[:MAX_TEXT_CHARS]
    return DanmakuComment(
        time=round(time_value, 3),
        mode=mode,
        font_size=max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, font_size)),
        color=color,
        timestamp=_optional_int(fields[4] if len(fields) > 4 else None),
        pool=_optional_int(fields[5] if len(fields) > 5 else None),
        user_hash=(fields[6].strip()[:128] or None) if len(fields) > 6 else None,
        row_id=(fields[7].strip()[:128] or None) if len(fields) > 7 else None,
        text=text,
    )


def parse_bilibili_danmaku_xml(data: bytes | str) -> list[DanmakuComment]:
    encoded = _bounded_xml_bytes(data)
    try:
        root = ET.fromstring(encoded)
    except ET.ParseError as exc:
        raise BilibiliDanmakuConversionError(f"invalid danmaku XML: {exc}") from exc

    comments: list[DanmakuComment] = []
    for element in root.iter("d"):
        parsed = _parse_comment(element)
        if parsed is None:
            continue
        comments.append(parsed)
        if len(comments) > MAX_COMMENTS:
            raise BilibiliDanmakuConversionError(
                f"danmaku XML exceeds the {MAX_COMMENTS} comment safety limit"
            )
    return comments


def render_danmaku_json(comments: Sequence[DanmakuComment]) -> str:
    if len(comments) > MAX_COMMENTS:
        raise BilibiliDanmakuConversionError("too many danmaku comments")
    payload = {
        "schema": "galaxy.bilibili.danmaku.v1",
        "count": len(comments),
        "comments": [asdict(comment) for comment in comments],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _ass_timestamp(seconds: float) -> str:
    value = max(0.0, float(seconds))
    centiseconds = int(round(value * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _ass_color(rgb: int) -> str:
    red = (rgb >> 16) & 0xFF
    green = (rgb >> 8) & 0xFF
    blue = rgb & 0xFF
    return f"&H00{blue:02X}{green:02X}{red:02X}"


def _ass_escape(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r\n", r"\N")
        .replace("\r", r"\N")
        .replace("\n", r"\N")
    )


def _validated_resolution(width: int, height: int) -> tuple[int, int]:
    try:
        width_value = int(width)
        height_value = int(height)
    except (TypeError, ValueError) as exc:
        raise BilibiliDanmakuConversionError("invalid ASS canvas dimensions") from exc
    if not 320 <= width_value <= MAX_ASS_DIMENSION or not 240 <= height_value <= MAX_ASS_DIMENSION:
        raise BilibiliDanmakuConversionError("ASS canvas dimensions are outside safety limits")
    return width_value, height_value


def _lane_y(index: int, font_size: int, height: int) -> int:
    margin = max(24, font_size)
    usable = max(font_size, height - margin * 2)
    lane_height = max(font_size + 4, 24)
    lane_count = max(1, usable // lane_height)
    lane = index % lane_count
    return min(height - margin, margin + lane * lane_height)


def _estimated_text_width(text: str, font_size: int) -> int:
    # A deterministic upper-biased estimate keeps the text fully outside the
    # frame at both ends without requiring a font renderer in the Local Engine.
    units = sum(1.0 if ord(char) > 0x7F else 0.55 for char in text[:MAX_TEXT_CHARS])
    return max(font_size, int(math.ceil(units * font_size)))


def _ass_override(comment: DanmakuComment, index: int, width: int, height: int) -> tuple[str, float]:
    font_size = comment.font_size
    y = _lane_y(index, font_size, height)
    text_width = _estimated_text_width(comment.text, font_size)
    color = _ass_color(comment.color)
    common = f"\\fs{font_size}\\c{color}"

    if comment.mode == 5:  # top fixed
        return f"{{{common}\\an8\\pos({width // 2},{max(20, font_size)})}}", FIXED_DURATION_SECONDS
    if comment.mode == 4:  # bottom fixed
        return f"{{{common}\\an2\\pos({width // 2},{height - max(20, font_size)})}}", FIXED_DURATION_SECONDS
    if comment.mode == 6:  # left-to-right reverse scrolling
        return (
            f"{{{common}\\an7\\move({-text_width},{y},{width + text_width},{y})}}",
            SCROLL_DURATION_SECONDS,
        )
    # Modes 1/2/3 are standard right-to-left scrolling. Unknown modes degrade
    # to the same deterministic scrolling behavior rather than disappearing.
    return (
        f"{{{common}\\an7\\move({width + text_width},{y},{-text_width},{y})}}",
        SCROLL_DURATION_SECONDS,
    )


def render_danmaku_ass(
    comments: Sequence[DanmakuComment],
    *,
    width: int = DEFAULT_ASS_WIDTH,
    height: int = DEFAULT_ASS_HEIGHT,
) -> str:
    if len(comments) > MAX_COMMENTS:
        raise BilibiliDanmakuConversionError("too many danmaku comments")
    width, height = _validated_resolution(width, height)
    header = f"""[Script Info]
; Generated by Galaxy Local Engine
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Danmaku,Arial,25,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,1,0,7,0,0,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines: list[str] = []
    for index, comment in enumerate(comments):
        override, duration = _ass_override(comment, index, width, height)
        start = _ass_timestamp(comment.time)
        end = _ass_timestamp(comment.time + duration)
        lines.append(
            f"Dialogue: 0,{start},{end},Danmaku,,0,0,0,,{override}{_ass_escape(comment.text)}"
        )
    return header + "\n".join(lines) + ("\n" if lines else "")


def _normalized_formats(formats: Collection[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in formats:
        value = str(raw or "").strip().lower()
        if value not in SUPPORTED_OUTPUT_FORMATS:
            raise BilibiliDanmakuConversionError(f"unsupported danmaku output format: {value or raw!r}")
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise BilibiliDanmakuConversionError("at least one danmaku output format is required")
    return tuple(normalized)


def _atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def convert_danmaku_file(
    input_path: Path,
    *,
    formats: Collection[str] = ("ass", "json"),
    width: int = DEFAULT_ASS_WIDTH,
    height: int = DEFAULT_ASS_HEIGHT,
) -> dict[str, Path]:
    source = Path(input_path)
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise BilibiliDanmakuConversionError(f"could not read danmaku XML: {exc}") from exc
    if size > MAX_XML_BYTES:
        raise BilibiliDanmakuConversionError(
            f"danmaku XML exceeds the {MAX_XML_BYTES} byte safety limit"
        )
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise BilibiliDanmakuConversionError(f"could not read danmaku XML: {exc}") from exc

    comments = parse_bilibili_danmaku_xml(data)
    selected = _normalized_formats(formats)
    outputs: dict[str, Path] = {}
    for output_format in selected:
        target = source.with_suffix(f".{output_format}")
        content = (
            render_danmaku_ass(comments, width=width, height=height)
            if output_format == "ass"
            else render_danmaku_json(comments)
        )
        try:
            _atomic_write_text(target, content)
        except OSError as exc:
            raise BilibiliDanmakuConversionError(
                f"could not write {output_format.upper()} danmaku sidecar: {exc}"
            ) from exc
        outputs[output_format] = target
    return outputs


def run_bilibili_danmaku_conversion_self_test() -> None:
    sample = (
        '<i><d p="1.25,1,25,16711680,1700000000,0,user,row">Hello &amp; world</d>'
        '<d p="2.5,5,30,255">Top</d></i>'
    )
    comments = parse_bilibili_danmaku_xml(sample)
    assert len(comments) == 2
    assert comments[0].text == "Hello & world"
    assert _ass_color(0xFF0000) == "&H000000FF"
    assert "\\move(" in render_danmaku_ass(comments)
    assert '"schema": "galaxy.bilibili.danmaku.v1"' in render_danmaku_json(comments)
