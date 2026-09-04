from __future__ import annotations

import statistics
import subprocess
from dataclasses import dataclass
from pathlib import Path

from media_cleanup import CleanupRegion, MediaCleanupError, MediaProbe

TEMPORAL_SAMPLE_COUNT = 3
TEMPORAL_MIN_DURATION_SECONDS = 2.0
TEMPORAL_IOU_THRESHOLD = 0.30


@dataclass(frozen=True)
class GrayFrame:
    width: int
    height: int
    pixels: bytes

    def validate(self) -> "GrayFrame":
        if self.width < 8 or self.height < 8:
            raise MediaCleanupError("Suggestion frame is too small")
        if len(self.pixels) != self.width * self.height:
            raise MediaCleanupError("Suggestion frame pixel buffer size is invalid")
        return self


@dataclass(frozen=True)
class CleanupRegionSuggestion:
    region: CleanupRegion
    confidence: float
    source: str
    profile: str


_PROFILE_ALIASES = {
    "doubao": "bottom-right-compact",
    "豆包": "bottom-right-compact",
    "gemini": "bottom-right-wide",
    "google-gemini": "bottom-right-wide",
    "bottom-right-compact": "bottom-right-compact",
    "bottom-right-wide": "bottom-right-wide",
    "auto": "auto",
    "": "auto",
}


def normalize_suggestion_profile(value: str | None) -> str:
    key = (value or "auto").strip().lower()
    return _PROFILE_ALIASES.get(key, "auto")


def _default_seek_seconds(probe: MediaProbe) -> float:
    if probe.media_kind != "video" or probe.duration_seconds <= 0:
        return 0.0
    return min(1.0, probe.duration_seconds / 2.0)


def temporal_sample_times(probe: MediaProbe, *, sample_count: int = TEMPORAL_SAMPLE_COUNT) -> tuple[float, ...]:
    """Return bounded interior sample times for static visible-overlay detection."""
    if probe.media_kind != "video" or probe.duration_seconds < TEMPORAL_MIN_DURATION_SECONDS:
        return (_default_seek_seconds(probe),)
    count = max(2, min(int(sample_count), 5))
    duration = max(0.0, float(probe.duration_seconds))
    fractions = tuple((index + 1) / (count + 1) for index in range(count))
    return tuple(round(max(0.0, min(duration - 0.05, duration * fraction)), 3) for fraction in fractions)


def build_gray_frame_command(
    ffmpeg_path: Path,
    source: Path,
    probe: MediaProbe,
    *,
    seek_seconds: float | None = None,
) -> list[str]:
    seek = _default_seek_seconds(probe) if seek_seconds is None else max(0.0, float(seek_seconds))
    if probe.duration_seconds > 0:
        seek = min(seek, max(0.0, probe.duration_seconds - 0.01))
    command = [str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if probe.media_kind == "video" and seek > 0:
        command.extend(["-ss", f"{seek:.3f}"])
    command.extend(
        [
            "-i",
            str(source),
            "-vf",
            "format=gray",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "pipe:1",
        ]
    )
    return command


def extract_gray_frame(
    ffmpeg_path: Path,
    source: Path,
    probe: MediaProbe,
    *,
    timeout_seconds: float = 30.0,
    seek_seconds: float | None = None,
) -> GrayFrame:
    command = build_gray_frame_command(
        ffmpeg_path,
        source,
        probe,
        seek_seconds=seek_seconds,
    )
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(1.0, float(timeout_seconds)),
            check=False,
        )
    except OSError as exc:
        raise MediaCleanupError(f"Could not start FFmpeg suggestion renderer: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaCleanupError("Timed out while analyzing a cleanup suggestion frame") from exc

    if completed.returncode != 0:
        detail_bytes = completed.stderr or b""
        detail = detail_bytes.decode("utf-8", errors="replace").strip()[-600:]
        raise MediaCleanupError(f"Could not render cleanup suggestion frame: {detail or 'FFmpeg failed'}")

    pixels = bytes(completed.stdout or b"")
    expected_size = probe.width * probe.height
    if len(pixels) != expected_size:
        raise MediaCleanupError(
            f"Suggestion renderer returned {len(pixels)} bytes; expected {expected_size}"
        )
    return GrayFrame(probe.width, probe.height, pixels).validate()


def _region_iou(left: CleanupRegion, right: CleanupRegion) -> float:
    ix1 = max(left.x, right.x)
    iy1 = max(left.y, right.y)
    ix2 = min(left.x + left.width, right.x + right.width)
    iy2 = min(left.y + left.height, right.y + right.height)
    intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if intersection <= 0:
        return 0.0
    union = left.width * left.height + right.width * right.height - intersection
    return intersection / union if union > 0 else 0.0


def merge_temporal_suggestions(
    suggestions_by_frame: tuple[tuple[CleanupRegionSuggestion, ...], ...],
    *,
    frame_width: int,
    frame_height: int,
    profile: str,
) -> tuple[CleanupRegionSuggestion, ...]:
    """Require a stable visible region across video samples before suggesting it.

    Profile-only fallbacks are deliberately excluded from consensus: they are
    hints, not evidence that an overlay is actually present in multiple frames.
    """
    indexed_evidence: list[tuple[int, CleanupRegionSuggestion]] = [
        (frame_index, suggestion)
        for frame_index, group in enumerate(suggestions_by_frame)
        for suggestion in group
        if suggestion.source == "edge-analysis"
    ]
    if len(indexed_evidence) < 2:
        return ()

    best: list[tuple[int, CleanupRegionSuggestion]] = []
    for candidate_frame, candidate in indexed_evidence:
        cluster = [
            (frame_index, other)
            for frame_index, other in indexed_evidence
            if frame_index == candidate_frame
            or _region_iou(candidate.region, other.region) >= TEMPORAL_IOU_THRESHOLD
        ]
        distinct_frames = {frame_index for frame_index, _item in cluster}
        best_frames = {frame_index for frame_index, _item in best}
        if len(distinct_frames) > len(best_frames):
            best = cluster
    required = max(2, (len(suggestions_by_frame) + 1) // 2)
    best_by_frame: dict[int, CleanupRegionSuggestion] = {}
    for frame_index, suggestion in best:
        current = best_by_frame.get(frame_index)
        if current is None or suggestion.confidence > current.confidence:
            best_by_frame[frame_index] = suggestion
    stable = list(best_by_frame.values())
    if len(stable) < required:
        return ()

    xs = sorted(item.region.x for item in stable)
    ys = sorted(item.region.y for item in stable)
    rights = sorted(item.region.x + item.region.width for item in stable)
    bottoms = sorted(item.region.y + item.region.height for item in stable)
    mid = len(stable) // 2
    x1 = xs[mid]
    y1 = ys[mid]
    x2 = rights[mid]
    y2 = bottoms[mid]
    x1 = max(0, min(x1, frame_width - 2))
    y1 = max(0, min(y1, frame_height - 2))
    x2 = max(x1 + 2, min(x2, frame_width))
    y2 = max(y1 + 2, min(y2, frame_height))
    region = CleanupRegion(x1, y1, x2 - x1, y2 - y1).validate()
    coverage = region.width * region.height / max(1, frame_width * frame_height)
    if coverage > 0.22:
        return ()

    support = len(stable) / max(1, len(suggestions_by_frame))
    confidence = statistics.mean(item.confidence for item in stable)
    confidence = max(0.45, min(0.98, confidence * 0.75 + support * 0.25))
    return (
        CleanupRegionSuggestion(
            region=region,
            confidence=round(confidence, 3),
            source="temporal-edge-analysis",
            profile=profile,
        ),
    )


def suggest_visible_overlay_for_media(
    ffmpeg_path: Path,
    source: Path,
    probe: MediaProbe,
    *,
    provider_hint: str | None = None,
    timeout_seconds: float = 30.0,
) -> tuple[CleanupRegionSuggestion, ...]:
    profile = normalize_suggestion_profile(provider_hint)
    sample_times = temporal_sample_times(probe)

    if len(sample_times) == 1:
        frame = extract_gray_frame(
            ffmpeg_path,
            source,
            probe,
            timeout_seconds=timeout_seconds,
            seek_seconds=sample_times[0],
        )
        return suggest_visible_overlay_regions(frame, provider_hint=provider_hint)

    per_sample_timeout = max(2.0, float(timeout_seconds) / len(sample_times))
    groups: list[tuple[CleanupRegionSuggestion, ...]] = []
    middle_frame: GrayFrame | None = None
    for index, seek in enumerate(sample_times):
        frame = extract_gray_frame(
            ffmpeg_path,
            source,
            probe,
            timeout_seconds=per_sample_timeout,
            seek_seconds=seek,
        )
        if index == len(sample_times) // 2:
            middle_frame = frame
        groups.append(suggest_visible_overlay_regions(frame, provider_hint=None))

    merged = merge_temporal_suggestions(
        tuple(groups),
        frame_width=probe.width,
        frame_height=probe.height,
        profile=profile,
    )
    if merged:
        return merged

    if profile != "auto" and middle_frame is not None:
        fallback = _profile_fallback(middle_frame, profile)
        return (fallback,) if fallback else ()
    return ()


def _zone_for_profile(width: int, height: int, profile: str) -> tuple[int, int, int, int]:
    if profile == "bottom-right-compact":
        left, top = 0.60, 0.68
    elif profile == "bottom-right-wide":
        left, top = 0.48, 0.68
    else:
        left, top = 0.50, 0.60
    x1 = max(0, min(width - 2, int(width * left)))
    y1 = max(0, min(height - 2, int(height * top)))
    return x1, y1, width, height


def _tile_edge_score(frame: GrayFrame, x1: int, y1: int, x2: int, y2: int) -> float:
    width = frame.width
    pixels = frame.pixels
    total = 0
    samples = 0
    for y in range(y1, max(y1, y2 - 1)):
        row = y * width
        next_row = (y + 1) * width
        for x in range(x1, max(x1, x2 - 1)):
            value = pixels[row + x]
            total += abs(value - pixels[row + x + 1])
            total += abs(value - pixels[next_row + x])
            samples += 2
    return total / samples if samples else 0.0


def _profile_fallback(frame: GrayFrame, profile: str) -> CleanupRegionSuggestion | None:
    if profile == "auto":
        return None
    x1, y1, x2, y2 = _zone_for_profile(frame.width, frame.height, profile)
    width = x2 - x1
    height = y2 - y1
    target_width = max(24, int(width * (0.58 if profile == "bottom-right-wide" else 0.42)))
    target_height = max(16, int(height * 0.38))
    region = CleanupRegion(
        max(x1, frame.width - target_width - max(6, frame.width // 100)),
        max(y1, frame.height - target_height - max(6, frame.height // 100)),
        min(target_width, frame.width - 2),
        min(target_height, frame.height - 2),
    ).validate()
    return CleanupRegionSuggestion(region=region, confidence=0.25, source="profile", profile=profile)


def suggest_visible_overlay_regions(
    frame: GrayFrame,
    *,
    provider_hint: str | None = None,
) -> tuple[CleanupRegionSuggestion, ...]:
    frame = frame.validate()
    profile = normalize_suggestion_profile(provider_hint)
    x1, y1, x2, y2 = _zone_for_profile(frame.width, frame.height, profile)

    cols = 12
    rows = 8
    tile_width = max(4, (x2 - x1) // cols)
    tile_height = max(4, (y2 - y1) // rows)
    scored: list[tuple[float, int, int, int, int]] = []
    for row in range(rows):
        ty1 = y1 + row * tile_height
        ty2 = y2 if row == rows - 1 else min(y2, ty1 + tile_height)
        for col in range(cols):
            tx1 = x1 + col * tile_width
            tx2 = x2 if col == cols - 1 else min(x2, tx1 + tile_width)
            if tx2 - tx1 < 2 or ty2 - ty1 < 2:
                continue
            scored.append((_tile_edge_score(frame, tx1, ty1, tx2, ty2), tx1, ty1, tx2, ty2))

    if not scored:
        fallback = _profile_fallback(frame, profile)
        return (fallback,) if fallback else ()

    baseline = statistics.median(score for score, *_bounds in scored)
    threshold = max(10.0, baseline * 1.75 + 2.0)
    active = [item for item in scored if item[0] >= threshold]
    if len(active) < 2:
        fallback = _profile_fallback(frame, profile)
        return (fallback,) if fallback else ()

    ax1 = min(item[1] for item in active)
    ay1 = min(item[2] for item in active)
    ax2 = max(item[3] for item in active)
    ay2 = max(item[4] for item in active)
    pad_x = max(4, frame.width // 100)
    pad_y = max(4, frame.height // 100)
    ax1 = max(0, ax1 - pad_x)
    ay1 = max(0, ay1 - pad_y)
    ax2 = min(frame.width, ax2 + pad_x)
    ay2 = min(frame.height, ay2 + pad_y)

    region = CleanupRegion(ax1, ay1, max(2, ax2 - ax1), max(2, ay2 - ay1)).validate()
    coverage = region.width * region.height / (frame.width * frame.height)
    if coverage > 0.22:
        fallback = _profile_fallback(frame, profile)
        return (fallback,) if fallback else ()

    strongest = max(item[0] for item in active)
    confidence = max(0.30, min(0.95, 0.35 + (strongest - threshold) / 80.0 + len(active) / 120.0))
    return (
        CleanupRegionSuggestion(
            region=region,
            confidence=round(confidence, 3),
            source="edge-analysis",
            profile=profile,
        ),
    )


def run_media_cleanup_suggestions_self_test() -> None:
    width, height = 320, 180
    pixels = bytearray([32] * (width * height))
    for y in range(140, 164):
        for x in range(236, 302):
            pixels[y * width + x] = 235 if (x // 4 + y // 4) % 2 == 0 else 32
    suggestions = suggest_visible_overlay_regions(GrayFrame(width, height, bytes(pixels)))
    assert suggestions
    suggestion = suggestions[0]
    assert suggestion.source == "edge-analysis"
    assert suggestion.region.x >= width // 2
    assert suggestion.region.y >= height // 2

    temporal = merge_temporal_suggestions(
        (
            (CleanupRegionSuggestion(CleanupRegion(230, 138, 72, 26), 0.70, "edge-analysis", "auto"),),
            (CleanupRegionSuggestion(CleanupRegion(232, 139, 70, 25), 0.74, "edge-analysis", "auto"),),
            (CleanupRegionSuggestion(CleanupRegion(12, 12, 50, 20), 0.80, "edge-analysis", "auto"),),
        ),
        frame_width=width,
        frame_height=height,
        profile="auto",
    )
    assert temporal and temporal[0].source == "temporal-edge-analysis"
    assert temporal[0].region.x >= width // 2

    fallback = suggest_visible_overlay_regions(
        GrayFrame(width, height, bytes([32] * (width * height))),
        provider_hint="doubao",
    )
    assert fallback and fallback[0].source == "profile"
    assert normalize_suggestion_profile("Gemini") == "bottom-right-wide"
