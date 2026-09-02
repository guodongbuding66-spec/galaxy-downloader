from __future__ import annotations

import statistics
import subprocess
from dataclasses import dataclass
from pathlib import Path

from media_cleanup import CleanupRegion, MediaCleanupError, MediaProbe


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


def build_gray_frame_command(ffmpeg_path: Path, source: Path, probe: MediaProbe) -> list[str]:
    seek = 0.0
    if probe.media_kind == "video" and probe.duration_seconds > 0:
        seek = min(1.0, probe.duration_seconds / 2.0)
    command = [str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if seek > 0:
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
) -> GrayFrame:
    command = build_gray_frame_command(ffmpeg_path, source, probe)
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


def suggest_visible_overlay_for_media(
    ffmpeg_path: Path,
    source: Path,
    probe: MediaProbe,
    *,
    provider_hint: str | None = None,
    timeout_seconds: float = 30.0,
) -> tuple[CleanupRegionSuggestion, ...]:
    frame = extract_gray_frame(
        ffmpeg_path,
        source,
        probe,
        timeout_seconds=timeout_seconds,
    )
    return suggest_visible_overlay_regions(frame, provider_hint=provider_hint)


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
    fallback = suggest_visible_overlay_regions(
        GrayFrame(width, height, bytes([32] * (width * height))),
        provider_hint="doubao",
    )
    assert fallback and fallback[0].source == "profile"
    assert normalize_suggestion_profile("Gemini") == "bottom-right-wide"
