from __future__ import annotations

import math
import shutil
import statistics
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from media_cleanup import (
    CleanupRegion,
    MediaCleanupError,
    MediaProbe,
    _tool_path,
    _validate_input,
    probe_media,
)

ANALYSIS_MAX_WIDTH = 480
ANALYSIS_MAX_HEIGHT = 320
MAX_SUGGESTIONS = 4
MIN_CONFIDENCE = 0.58


@dataclass(frozen=True)
class AnalysisPlan:
    media_kind: str
    source_width: int
    source_height: int
    analysis_width: int
    analysis_height: int
    seek_seconds: float = 0.0


@dataclass(frozen=True)
class OverlaySuggestion:
    region: CleanupRegion
    confidence: float
    position: str
    reason: str


@dataclass(frozen=True)
class _Zone:
    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    location_prior: float


ZONES = (
    _Zone("右下角", 0.52, 0.62, 1.00, 1.00, 0.14),
    _Zone("左下角", 0.00, 0.62, 0.48, 1.00, 0.12),
    _Zone("右上角", 0.52, 0.00, 1.00, 0.38, 0.10),
    _Zone("左上角", 0.00, 0.00, 0.48, 0.38, 0.10),
    _Zone("底部中间", 0.18, 0.72, 0.82, 1.00, 0.08),
)


def _fit_analysis_size(width: int, height: int) -> tuple[int, int]:
    if width < 2 or height < 2:
        raise MediaCleanupError("Media dimensions are invalid for overlay analysis")
    scale = min(1.0, ANALYSIS_MAX_WIDTH / width, ANALYSIS_MAX_HEIGHT / height)
    return max(2, int(round(width * scale))), max(2, int(round(height * scale)))


def build_analysis_plan(probe: MediaProbe) -> AnalysisPlan:
    width, height = _fit_analysis_size(probe.width, probe.height)
    seek = 0.0
    if probe.media_kind == "video" and probe.duration_seconds > 0:
        # Most generated-video visible watermarks are present from the first
        # seconds onward. A one-second sample avoids title-card fades while
        # keeping suggestion latency low on long files.
        seek = min(1.0, probe.duration_seconds / 2.0)
    return AnalysisPlan(
        media_kind=probe.media_kind,
        source_width=probe.width,
        source_height=probe.height,
        analysis_width=width,
        analysis_height=height,
        seek_seconds=max(0.0, seek),
    )


def build_analysis_command(
    ffmpeg_path: Path,
    source: Path,
    output_ppm: Path,
    plan: AnalysisPlan,
) -> list[str]:
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
    ]
    if plan.media_kind == "video" and plan.seek_seconds > 0:
        command.extend(["-ss", f"{plan.seek_seconds:.3f}"])
    command.extend(
        [
            "-i",
            str(source),
            "-vf",
            f"scale={plan.analysis_width}:{plan.analysis_height}",
            "-frames:v",
            "1",
            "-an",
            "-sn",
            "-f",
            "image2",
            "-vcodec",
            "ppm",
            str(output_ppm),
        ]
    )
    return command


def _read_ppm_token(data: bytes, offset: int) -> tuple[bytes, int]:
    size = len(data)
    while offset < size:
        value = data[offset]
        if value in b" \t\r\n":
            offset += 1
            continue
        if value == ord("#"):
            newline = data.find(b"\n", offset)
            if newline < 0:
                raise MediaCleanupError("Invalid PPM comment")
            offset = newline + 1
            continue
        break
    start = offset
    while offset < size and data[offset] not in b" \t\r\n#":
        offset += 1
    if start == offset:
        raise MediaCleanupError("Invalid PPM header")
    return data[start:offset], offset


def parse_ppm(data: bytes) -> tuple[int, int, bytes]:
    magic, offset = _read_ppm_token(data, 0)
    width_raw, offset = _read_ppm_token(data, offset)
    height_raw, offset = _read_ppm_token(data, offset)
    max_raw, offset = _read_ppm_token(data, offset)
    if magic != b"P6":
        raise MediaCleanupError("Overlay analysis frame must be binary PPM (P6)")
    try:
        width = int(width_raw)
        height = int(height_raw)
        max_value = int(max_raw)
    except ValueError as exc:
        raise MediaCleanupError("Invalid PPM dimensions") from exc
    if width < 2 or height < 2 or max_value != 255:
        raise MediaCleanupError("Unsupported PPM frame")
    while offset < len(data) and data[offset] in b" \t\r\n":
        offset += 1
    expected = width * height * 3
    pixels = data[offset : offset + expected]
    if len(pixels) != expected:
        raise MediaCleanupError("PPM frame is truncated")
    return width, height, pixels


def generate_analysis_frame(
    ffmpeg_path: Path,
    source: Path,
    output_ppm: Path,
    plan: AnalysisPlan,
) -> Path:
    output_ppm.parent.mkdir(parents=True, exist_ok=True)
    command = build_analysis_command(ffmpeg_path, source, output_ppm, plan)
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False)
    except OSError as exc:
        raise MediaCleanupError(f"Could not start FFmpeg overlay analyzer: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaCleanupError("Timed out while preparing overlay analysis frame") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "FFmpeg analysis failed").strip()[-600:]
        raise MediaCleanupError(f"Could not prepare overlay analysis frame: {detail}")
    if not output_ppm.exists() or output_ppm.stat().st_size <= 0:
        raise MediaCleanupError("Overlay analyzer did not produce an analysis frame")
    return output_ppm


def _luma(pixels: bytes, width: int, height: int) -> list[int]:
    expected = width * height * 3
    if len(pixels) != expected:
        raise MediaCleanupError("RGB analysis frame size does not match dimensions")
    result = [0] * (width * height)
    for index in range(width * height):
        base = index * 3
        r = pixels[base]
        g = pixels[base + 1]
        b = pixels[base + 2]
        result[index] = (77 * r + 150 * g + 29 * b) >> 8
    return result


def _edge_map(gray: list[int], width: int, height: int) -> list[int]:
    edges = [0] * (width * height)
    for y in range(1, height - 1):
        row = y * width
        before = (y - 1) * width
        after = (y + 1) * width
        for x in range(1, width - 1):
            gx = abs(gray[row + x + 1] - gray[row + x - 1])
            gy = abs(gray[after + x] - gray[before + x])
            edges[row + x] = min(255, gx + gy)
    return edges


def _percentile(values: list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return float(ordered[index])


def _zone_bounds(zone: _Zone, width: int, height: int) -> tuple[int, int, int, int]:
    x1 = min(width - 2, max(0, int(math.floor(zone.x1 * width))))
    y1 = min(height - 2, max(0, int(math.floor(zone.y1 * height))))
    x2 = min(width, max(x1 + 2, int(math.ceil(zone.x2 * width))))
    y2 = min(height, max(y1 + 2, int(math.ceil(zone.y2 * height))))
    return x1, y1, x2, y2


def _mean(values: Iterable[int]) -> float:
    values_list = list(values)
    return statistics.fmean(values_list) if values_list else 0.0


def _suggest_in_zone(
    edges: list[int],
    width: int,
    height: int,
    zone: _Zone,
) -> tuple[int, int, int, int, float] | None:
    x1, y1, x2, y2 = _zone_bounds(zone, width, height)
    zone_width = x2 - x1
    zone_height = y2 - y1
    values = [edges[y * width + x] for y in range(y1, y2) for x in range(x1, x2)]
    if not values:
        return None
    zone_mean = _mean(values)
    deviation = statistics.pstdev(values) if len(values) > 1 else 0.0
    threshold = max(24.0, _percentile(values, 0.82), zone_mean + deviation * 0.65)

    row_hits = [0] * zone_height
    col_hits = [0] * zone_width
    active_count = 0
    for local_y, y in enumerate(range(y1, y2)):
        base = y * width
        for local_x, x in enumerate(range(x1, x2)):
            if edges[base + x] < threshold:
                continue
            row_hits[local_y] += 1
            col_hits[local_x] += 1
            active_count += 1

    if active_count < max(10, int(zone_width * zone_height * 0.003)):
        return None

    min_row_hits = max(2, int(zone_width * 0.035))
    min_col_hits = max(2, int(zone_height * 0.045))
    active_rows = [index for index, count in enumerate(row_hits) if count >= min_row_hits]
    active_cols = [index for index, count in enumerate(col_hits) if count >= min_col_hits]
    if not active_rows or not active_cols:
        return None

    raw_left = x1 + min(active_cols)
    raw_right = x1 + max(active_cols) + 1
    raw_top = y1 + min(active_rows)
    raw_bottom = y1 + max(active_rows) + 1
    pad_x = max(2, int(round(width * 0.008)))
    pad_y = max(2, int(round(height * 0.008)))
    left = max(0, raw_left - pad_x)
    right = min(width, raw_right + pad_x)
    top = max(0, raw_top - pad_y)
    bottom = min(height, raw_bottom + pad_y)
    box_width = right - left
    box_height = bottom - top
    if box_width < 4 or box_height < 4:
        return None

    area_fraction = (box_width * box_height) / float(width * height)
    if area_fraction < 0.001 or area_fraction > 0.18:
        return None
    aspect = box_width / max(1.0, float(box_height))
    if aspect < 0.18 or aspect > 14.0:
        return None

    box_values = [edges[y * width + x] for y in range(top, bottom) for x in range(left, right)]
    box_mean = _mean(box_values)
    contrast = box_mean / max(1.0, zone_mean)
    density = sum(1 for value in box_values if value >= threshold) / max(1, len(box_values))

    # Favor compact overlays: common visible AI-service marks and creator logos
    # are typically a few percent of the frame, while large detailed scenery in
    # a corner should receive a lower prior and remain only a suggestion.
    if area_fraction <= 0.045:
        compact_score = 0.18
    elif area_fraction <= 0.09:
        compact_score = 0.10
    else:
        compact_score = 0.02
    contrast_score = min(0.28, max(0.0, (contrast - 0.9) * 0.20))
    density_score = min(0.30, density * 1.15)
    edge_score = min(0.16, box_mean / 255.0 * 0.22)
    confidence = min(0.99, 0.16 + zone.location_prior + compact_score + contrast_score + density_score + edge_score)
    if confidence < MIN_CONFIDENCE:
        return None
    return left, top, right, bottom, confidence


def _iou(a: CleanupRegion, b: CleanupRegion) -> float:
    left = max(a.x, b.x)
    top = max(a.y, b.y)
    right = min(a.x + a.width, b.x + b.width)
    bottom = min(a.y + a.height, b.y + b.height)
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    union = a.width * a.height + b.width * b.height - intersection
    return intersection / union if union > 0 else 0.0


def _scale_region(
    left: int,
    top: int,
    right: int,
    bottom: int,
    plan: AnalysisPlan,
) -> CleanupRegion:
    sx = int(math.floor(left * plan.source_width / plan.analysis_width))
    sy = int(math.floor(top * plan.source_height / plan.analysis_height))
    ex = int(math.ceil(right * plan.source_width / plan.analysis_width))
    ey = int(math.ceil(bottom * plan.source_height / plan.analysis_height))
    sx = min(max(sx, 0), plan.source_width - 2)
    sy = min(max(sy, 0), plan.source_height - 2)
    ex = min(max(ex, sx + 2), plan.source_width)
    ey = min(max(ey, sy + 2), plan.source_height)
    return CleanupRegion(sx, sy, ex - sx, ey - sy).validate()


def suggest_from_rgb(
    pixels: bytes,
    width: int,
    height: int,
    plan: AnalysisPlan,
    *,
    max_suggestions: int = MAX_SUGGESTIONS,
) -> tuple[OverlaySuggestion, ...]:
    if width != plan.analysis_width or height != plan.analysis_height:
        raise MediaCleanupError("Analysis frame dimensions do not match the suggestion plan")
    if max_suggestions < 1 or max_suggestions > MAX_SUGGESTIONS:
        raise MediaCleanupError(f"max_suggestions must be between 1 and {MAX_SUGGESTIONS}")
    gray = _luma(pixels, width, height)
    edges = _edge_map(gray, width, height)
    candidates: list[OverlaySuggestion] = []
    for zone in ZONES:
        match = _suggest_in_zone(edges, width, height, zone)
        if match is None:
            continue
        left, top, right, bottom, confidence = match
        region = _scale_region(left, top, right, bottom, plan)
        reason = f"{zone.name}检测到紧凑的高边缘/高局部对比覆盖层候选"
        candidate = OverlaySuggestion(
            region=region,
            confidence=round(float(confidence), 3),
            position=zone.name,
            reason=reason,
        )
        if any(_iou(candidate.region, existing.region) >= 0.45 for existing in candidates):
            continue
        candidates.append(candidate)
    candidates.sort(key=lambda item: item.confidence, reverse=True)
    return tuple(candidates[:max_suggestions])


def suggest_visible_overlay_regions(
    ffmpeg_directory: Path,
    source_path: Path,
    *,
    max_suggestions: int = MAX_SUGGESTIONS,
) -> tuple[OverlaySuggestion, ...]:
    source, media_kind = _validate_input(source_path)
    ffmpeg_path = _tool_path(ffmpeg_directory, "ffmpeg")
    ffprobe_path = _tool_path(ffmpeg_directory, "ffprobe")
    probe = probe_media(ffprobe_path, source, media_kind)
    plan = build_analysis_plan(probe)
    temp_dir = Path(tempfile.mkdtemp(prefix="galaxy-overlay-suggest-"))
    try:
        frame_path = temp_dir / "analysis.ppm"
        generate_analysis_frame(ffmpeg_path, source, frame_path, plan)
        width, height, pixels = parse_ppm(frame_path.read_bytes())
        return suggest_from_rgb(
            pixels,
            width,
            height,
            plan,
            max_suggestions=max_suggestions,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _synthetic_frame(width: int, height: int) -> bytes:
    pixels = bytearray([96, 104, 112] * (width * height))

    def set_pixel(x: int, y: int, value: int) -> None:
        if x < 0 or y < 0 or x >= width or y >= height:
            return
        base = (y * width + x) * 3
        pixels[base : base + 3] = bytes((value, value, value))

    # Text/logo-like strokes in the bottom-right corner.
    start_x = int(width * 0.70)
    start_y = int(height * 0.78)
    for row in range(3):
        y = start_y + row * 8
        for x in range(start_x, min(width - 5, start_x + int(width * 0.20))):
            if (x - start_x) % 7 not in {0, 1}:
                set_pixel(x, y, 238)
                set_pixel(x, y + 1, 238)
    for x in range(start_x, min(width - 5, start_x + int(width * 0.20)), 12):
        for y in range(start_y, min(height - 5, start_y + int(height * 0.12))):
            set_pixel(x, y, 230)
    return bytes(pixels)


def run_media_cleanup_suggestion_self_test() -> None:
    plan = AnalysisPlan("image", 1280, 720, 320, 180, 0.0)
    pixels = _synthetic_frame(plan.analysis_width, plan.analysis_height)
    suggestions = suggest_from_rgb(pixels, plan.analysis_width, plan.analysis_height, plan)
    assert suggestions
    assert suggestions[0].position in {"右下角", "底部中间"}
    assert suggestions[0].confidence >= MIN_CONFIDENCE
    region = suggestions[0].region
    assert region.x >= 1280 // 2
    assert region.y >= 720 // 2
    assert region.x + region.width <= 1280
    assert region.y + region.height <= 720

    ppm = b"P6\n# demo\n2 2\n255\n" + bytes(range(12))
    width, height, decoded = parse_ppm(ppm)
    assert (width, height) == (2, 2)
    assert decoded == bytes(range(12))

    video_plan = build_analysis_plan(MediaProbe(1920, 1080, 20.0, "video"))
    command = build_analysis_command(
        Path("ffmpeg.exe"),
        Path("input.mp4"),
        Path("analysis.ppm"),
        video_plan,
    )
    assert "-ss" in command
    assert "ppm" in command
    assert command[-1] == "analysis.ppm"
