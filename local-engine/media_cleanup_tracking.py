from __future__ import annotations

import hashlib
import json
import math
import subprocess
import threading
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from media_cleanup import (
    CleanupRegion,
    MediaCleanupCancelled,
    MediaCleanupError,
    MediaCleanupResult,
    MediaProbe,
    ProgressCallback,
    _parse_progress_seconds,
    _tool_path,
    _validate_input,
    _validate_output,
    probe_media,
)
from media_cleanup_suggestions import GrayFrame, extract_gray_frame

DEFAULT_TRACK_SAMPLE_COUNT = 9
MIN_TRACK_SAMPLE_COUNT = 3
MAX_TRACK_SAMPLE_COUNT = 17
DEFAULT_TRACK_MIN_CONFIDENCE = 0.48
MAX_TRACK_SEARCH_RADIUS = 160
MIN_TRACK_TEMPLATE_CONTRAST = 7.0


@dataclass(frozen=True)
class TrackKeyframe:
    time_seconds: float
    region: CleanupRegion
    confidence: float

    def validate(self, *, frame_width: int, frame_height: int) -> "TrackKeyframe":
        region = self.region.validate()
        if self.time_seconds < 0 or not math.isfinite(self.time_seconds):
            raise MediaCleanupError("Tracking keyframe time must be a finite non-negative value")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise MediaCleanupError("Tracking keyframe confidence must be between 0 and 1")
        if region.x + region.width > frame_width or region.y + region.height > frame_height:
            raise MediaCleanupError("Tracking keyframe region exceeds the source frame")
        return self


@dataclass(frozen=True)
class OverlayTrack:
    frame_width: int
    frame_height: int
    keyframes: tuple[TrackKeyframe, ...]

    def validate(self) -> "OverlayTrack":
        if self.frame_width < 2 or self.frame_height < 2:
            raise MediaCleanupError("Tracked frame dimensions are invalid")
        if len(self.keyframes) < 2:
            raise MediaCleanupError("A tracked overlay requires at least two keyframes")
        previous = -1.0
        width = None
        height = None
        for keyframe in self.keyframes:
            keyframe.validate(frame_width=self.frame_width, frame_height=self.frame_height)
            if keyframe.time_seconds <= previous:
                raise MediaCleanupError("Tracking keyframes must be strictly increasing in time")
            previous = keyframe.time_seconds
            width = keyframe.region.width if width is None else width
            height = keyframe.region.height if height is None else height
            if keyframe.region.width != width or keyframe.region.height != height:
                raise MediaCleanupError("Tracked delogo regions must keep a constant size")
        return self

    @property
    def region_width(self) -> int:
        return self.keyframes[0].region.width

    @property
    def region_height(self) -> int:
        return self.keyframes[0].region.height


@dataclass(frozen=True)
class _PatchSignature:
    values: tuple[int, ...]
    contrast: float


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bounded_sample_count(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_TRACK_SAMPLE_COUNT
    return max(MIN_TRACK_SAMPLE_COUNT, min(parsed, MAX_TRACK_SAMPLE_COUNT))


def _validate_region_for_frame(region: CleanupRegion, frame: GrayFrame) -> CleanupRegion:
    region = region.validate()
    if region.x + region.width > frame.width or region.y + region.height > frame.height:
        raise MediaCleanupError("Tracked visible-overlay region exceeds the frame")
    if region.width < 6 or region.height < 6:
        raise MediaCleanupError("Tracked visible-overlay region is too small")
    return region


def tracking_sample_times(
    probe: MediaProbe,
    *,
    anchor_seconds: float,
    sample_count: int = DEFAULT_TRACK_SAMPLE_COUNT,
) -> tuple[float, ...]:
    if probe.media_kind != "video":
        raise MediaCleanupError("Temporal visible-overlay tracking requires a video")
    duration = max(0.0, float(probe.duration_seconds))
    if duration <= 0:
        raise MediaCleanupError("Temporal tracking requires a video with a known duration")
    count = _bounded_sample_count(sample_count)
    end = max(0.0, duration - min(0.05, duration / 4.0))
    anchor = max(0.0, min(float(anchor_seconds), end))
    if end <= 0.01:
        return (0.0, anchor if anchor > 0 else end)

    evenly_spaced = [end * index / (count - 1) for index in range(count)]
    values = evenly_spaced + [anchor]
    unique = sorted({round(max(0.0, min(end, value)), 3) for value in values})
    if len(unique) < 2:
        unique = [0.0, round(end, 3)]
    return tuple(unique)


def _signature_points(region: CleanupRegion) -> tuple[tuple[int, int], ...]:
    cols = max(4, min(9, region.width // 3))
    rows = max(4, min(7, region.height // 3))
    points: list[tuple[int, int]] = []
    for row in range(rows):
        y = 1 + round((region.height - 3) * row / max(1, rows - 1))
        for col in range(cols):
            x = 1 + round((region.width - 3) * col / max(1, cols - 1))
            points.append((x, y))
    return tuple(points)


def _gradient_at(frame: GrayFrame, x: int, y: int) -> int:
    width = frame.width
    pixels = frame.pixels
    center = y * width + x
    horizontal = abs(pixels[center + 1] - pixels[center - 1])
    vertical = abs(pixels[center + width] - pixels[center - width])
    return min(255, horizontal + vertical)


def _patch_signature(frame: GrayFrame, region: CleanupRegion) -> _PatchSignature:
    region = _validate_region_for_frame(region, frame)
    values = tuple(
        _gradient_at(frame, region.x + px, region.y + py)
        for px, py in _signature_points(region)
    )
    if not values:
        raise MediaCleanupError("Could not build a tracking signature")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    contrast = math.sqrt(variance)
    return _PatchSignature(values=values, contrast=contrast)


def _signature_error(
    frame: GrayFrame,
    region: CleanupRegion,
    reference: _PatchSignature,
) -> float:
    values = tuple(
        _gradient_at(frame, region.x + px, region.y + py)
        for px, py in _signature_points(region)
    )
    if len(values) != len(reference.values):
        raise MediaCleanupError("Tracking signature shape changed unexpectedly")
    return sum(abs(left - right) for left, right in zip(values, reference.values)) / len(values)


def _candidate_positions(center: int, radius: int, lower: int, upper: int, step: int) -> tuple[int, ...]:
    start = max(lower, center - radius)
    end = min(upper, center + radius)
    if start > end:
        return ()
    values = list(range(start, end + 1, max(1, step)))
    for item in (start, center, end):
        bounded = max(lower, min(upper, item))
        if bounded not in values:
            values.append(bounded)
    return tuple(sorted(set(values)))


def _search_region(
    frame: GrayFrame,
    previous: CleanupRegion,
    reference: _PatchSignature,
    *,
    search_radius: int,
) -> tuple[CleanupRegion, float]:
    frame.validate()
    previous = _validate_region_for_frame(previous, frame)
    max_x = frame.width - previous.width
    max_y = frame.height - previous.height
    radius = max(2, min(int(search_radius), MAX_TRACK_SEARCH_RADIUS))
    coarse_step = max(2, min(8, radius // 6 or 2))

    def evaluate(xs: Iterable[int], ys: Iterable[int]) -> list[tuple[float, int, int, CleanupRegion]]:
        scored: list[tuple[float, int, int, CleanupRegion]] = []
        for y in ys:
            for x in xs:
                candidate = CleanupRegion(x, y, previous.width, previous.height)
                error = _signature_error(frame, candidate, reference)
                distance = abs(x - previous.x) + abs(y - previous.y)
                scored.append((error, distance, x + y, candidate))
        scored.sort(key=lambda item: (item[0], item[1], item[2]))
        return scored

    coarse = evaluate(
        _candidate_positions(previous.x, radius, 0, max_x, coarse_step),
        _candidate_positions(previous.y, radius, 0, max_y, coarse_step),
    )
    if not coarse:
        raise MediaCleanupError("Tracking search window did not contain a valid region")
    coarse_best = coarse[0][3]
    refine_radius = max(2, coarse_step + 1)
    refined = evaluate(
        _candidate_positions(coarse_best.x, refine_radius, 0, max_x, 1),
        _candidate_positions(coarse_best.y, refine_radius, 0, max_y, 1),
    )
    best_error, _distance, _tie, best = refined[0]
    second_error = refined[1][0] if len(refined) > 1 else best_error + 6.0

    scale = max(28.0, reference.contrast * 2.4 + 16.0)
    absolute = max(0.0, min(1.0, 1.0 - best_error / scale))
    separation = max(0.0, min(1.0, (second_error - best_error) / max(6.0, best_error + 4.0)))
    confidence = max(0.0, min(1.0, absolute * (0.82 + 0.18 * separation)))
    return best, round(confidence, 4)


def track_gray_frames(
    frames: tuple[tuple[float, GrayFrame], ...],
    initial_region: CleanupRegion,
    *,
    anchor_index: int,
    search_radius: int,
    min_confidence: float = DEFAULT_TRACK_MIN_CONFIDENCE,
) -> OverlayTrack:
    if len(frames) < 2:
        raise MediaCleanupError("Temporal tracking requires at least two sampled frames")
    if anchor_index < 0 or anchor_index >= len(frames):
        raise MediaCleanupError("Tracking anchor index is outside the sampled frames")
    width = frames[0][1].width
    height = frames[0][1].height
    previous_time = -1.0
    for time_seconds, frame in frames:
        frame.validate()
        if frame.width != width or frame.height != height:
            raise MediaCleanupError("Tracking frames changed dimensions")
        if time_seconds <= previous_time:
            raise MediaCleanupError("Tracking frame timestamps must be strictly increasing")
        previous_time = time_seconds

    initial_region = _validate_region_for_frame(initial_region, frames[anchor_index][1])
    reference = _patch_signature(frames[anchor_index][1], initial_region)
    if reference.contrast < MIN_TRACK_TEMPLATE_CONTRAST:
        raise MediaCleanupError("Selected visible-overlay region has insufficient visual structure to track safely")
    threshold = max(0.0, min(1.0, float(min_confidence)))

    tracked: dict[int, TrackKeyframe] = {
        anchor_index: TrackKeyframe(frames[anchor_index][0], initial_region, 1.0)
    }

    previous = initial_region
    for index in range(anchor_index + 1, len(frames)):
        region, confidence = _search_region(
            frames[index][1], previous, reference, search_radius=search_radius
        )
        if confidence < threshold:
            raise MediaCleanupError(
                f"Visible-overlay tracking lost confidence at {frames[index][0]:.3f}s ({confidence:.2f})"
            )
        tracked[index] = TrackKeyframe(frames[index][0], region, confidence)
        previous = region

    previous = initial_region
    for index in range(anchor_index - 1, -1, -1):
        region, confidence = _search_region(
            frames[index][1], previous, reference, search_radius=search_radius
        )
        if confidence < threshold:
            raise MediaCleanupError(
                f"Visible-overlay tracking lost confidence at {frames[index][0]:.3f}s ({confidence:.2f})"
            )
        tracked[index] = TrackKeyframe(frames[index][0], region, confidence)
        previous = region

    keyframes = tuple(tracked[index] for index in range(len(frames)))
    return OverlayTrack(width, height, keyframes).validate()


def track_visible_overlay_for_video(
    ffmpeg_path: Path,
    source: Path,
    probe: MediaProbe,
    initial_region: CleanupRegion,
    *,
    anchor_seconds: float,
    sample_count: int = DEFAULT_TRACK_SAMPLE_COUNT,
    search_radius: int | None = None,
    min_confidence: float = DEFAULT_TRACK_MIN_CONFIDENCE,
    timeout_seconds: float = 60.0,
) -> OverlayTrack:
    if probe.media_kind != "video":
        raise MediaCleanupError("Temporal visible-overlay tracking requires a video")
    times = tracking_sample_times(probe, anchor_seconds=anchor_seconds, sample_count=sample_count)
    anchor = min(range(len(times)), key=lambda index: abs(times[index] - anchor_seconds))
    per_frame_timeout = max(3.0, float(timeout_seconds) / max(1, len(times)))
    frames = tuple(
        (
            time_seconds,
            extract_gray_frame(
                ffmpeg_path,
                source,
                probe,
                timeout_seconds=per_frame_timeout,
                seek_seconds=time_seconds,
            ),
        )
        for time_seconds in times
    )
    radius = search_radius
    if radius is None:
        radius = max(12, min(MAX_TRACK_SEARCH_RADIUS, round(max(probe.width, probe.height) * 0.06)))
    return track_gray_frames(
        frames,
        initial_region,
        anchor_index=anchor,
        search_radius=radius,
        min_confidence=min_confidence,
    )


def _format_number(value: float) -> str:
    rendered = f"{value:.6f}".rstrip("0").rstrip(".")
    return rendered if rendered else "0"


def _linear_segment(start: TrackKeyframe, end: TrackKeyframe, axis: str) -> str:
    left = float(getattr(start.region, axis))
    right = float(getattr(end.region, axis))
    duration = end.time_seconds - start.time_seconds
    if abs(right - left) < 1e-9 or duration <= 1e-9:
        return _format_number(left)
    return (
        f"{_format_number(left)}+({_format_number(right - left)})*"
        f"(t-{_format_number(start.time_seconds)})/{_format_number(duration)}"
    )


def build_piecewise_track_expression(track: OverlayTrack, axis: str) -> str:
    track = track.validate()
    if axis not in {"x", "y"}:
        raise MediaCleanupError("Tracked expression axis must be x or y")
    keyframes = track.keyframes
    expression = _format_number(float(getattr(keyframes[-1].region, axis)))
    for index in range(len(keyframes) - 2, -1, -1):
        start = keyframes[index]
        end = keyframes[index + 1]
        segment = _linear_segment(start, end, axis)
        expression = f"if(lt(t,{_format_number(end.time_seconds)}),{segment},{expression})"
    first = keyframes[0]
    first_value = _format_number(float(getattr(first.region, axis)))
    return f"if(lt(t,{_format_number(first.time_seconds)}),{first_value},{expression})"


def build_tracked_delogo_filter(track: OverlayTrack) -> str:
    track = track.validate()
    x_expr = build_piecewise_track_expression(track, "x")
    y_expr = build_piecewise_track_expression(track, "y")
    return (
        f"delogo=x='{x_expr}':y='{y_expr}':w={track.region_width}:"
        f"h={track.region_height}:show=0"
    )


def build_tracked_cleanup_command(
    ffmpeg_path: Path,
    source: Path,
    output: Path,
    track: OverlayTrack,
) -> list[str]:
    suffix = output.suffix.lower()
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-n",
        "-i",
        str(source),
        "-vf",
        build_tracked_delogo_filter(track),
        "-map_metadata",
        "0",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
    ]
    if suffix == ".webm":
        command.extend(["-c:v", "libvpx-vp9", "-crf", "18", "-b:v", "0", "-c:a", "libopus"])
    else:
        command.extend(["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "192k"])
        if suffix in {".mp4", ".mov"}:
            command.extend(["-movflags", "+faststart"])
    command.extend(["-progress", "pipe:1", "-nostats", str(output)])
    return command


def _tracked_manifest_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".cleanup.json")


def _write_tracked_manifest(
    source: Path,
    output: Path,
    track: OverlayTrack,
    source_sha256: str,
    output_sha256: str,
) -> Path:
    manifest = _tracked_manifest_path(output)
    temporary = manifest.with_name(f".{manifest.name}.{uuid.uuid4().hex}.part")
    payload = {
        "schemaVersion": 1,
        "operation": "visible-overlay-cleanup",
        "method": "ffmpeg-delogo-temporal-track",
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mediaKind": "video",
        "sourceFile": source.name,
        "outputFile": output.name,
        "sourceSha256": source_sha256,
        "outputSha256": output_sha256,
        "frameSize": {"width": track.frame_width, "height": track.frame_height},
        "regionSize": {"width": track.region_width, "height": track.region_height},
        "keyframes": [
            {
                "timeSeconds": round(item.time_seconds, 3),
                "x": item.region.x,
                "y": item.region.y,
                "confidence": round(item.confidence, 4),
            }
            for item in track.keyframes
        ],
        "note": (
            "A visible overlay region was tracked over time and edited frame-by-frame. "
            "This tool does not target invisible provenance or authenticity markers."
        ),
    }
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(manifest)
    except Exception:
        with suppress(OSError):
            temporary.unlink()
        raise
    return manifest


def cleanup_tracked_visible_overlay(
    ffmpeg_directory: Path,
    input_path: Path,
    track: OverlayTrack,
    *,
    output_path: Path | None = None,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> MediaCleanupResult:
    source, media_kind = _validate_input(input_path)
    if media_kind != "video":
        raise MediaCleanupError("Temporal tracked cleanup supports video inputs only")
    track = track.validate()
    output = _validate_output(source, output_path, "video")
    ffmpeg_path = _tool_path(ffmpeg_directory, "ffmpeg")
    ffprobe_path = _tool_path(ffmpeg_directory, "ffprobe")
    probe = probe_media(ffprobe_path, source, "video")
    if probe.width != track.frame_width or probe.height != track.frame_height:
        raise MediaCleanupError("Tracked overlay frame size does not match the source video")
    if track.keyframes[-1].time_seconds > probe.duration_seconds + 0.25:
        raise MediaCleanupError("Tracked overlay extends beyond the source duration")

    source_sha256 = _sha256(source)
    if cancel_event is not None and cancel_event.is_set():
        raise MediaCleanupCancelled("Temporal visible-overlay cleanup was cancelled")
    if progress_callback:
        progress_callback(0.0, "Preparing temporal visible-overlay cleanup")

    command = build_tracked_cleanup_command(ffmpeg_path, source, output, track)
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise MediaCleanupError(f"Could not start FFmpeg: {exc}") from exc

    cancel_watch_stop = threading.Event()
    cancel_watch: threading.Thread | None = None
    if cancel_event is not None:
        def watch_cancel() -> None:
            while not cancel_watch_stop.wait(0.1):
                if not cancel_event.is_set():
                    continue
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                return

        cancel_watch = threading.Thread(target=watch_cancel, name="GalaxyMediaCleanupTrackCancel", daemon=True)
        cancel_watch.start()

    stderr = ""
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                seconds = _parse_progress_seconds(raw_line.strip())
                if seconds is not None and probe.duration_seconds > 0 and progress_callback:
                    percent = max(0.0, min(99.0, seconds / probe.duration_seconds * 100.0))
                    progress_callback(percent, "Cleaning tracked video frames")
        return_code = process.wait()
        stderr = process.stderr.read() if process.stderr is not None else ""
        if cancel_event is not None and cancel_event.is_set():
            raise MediaCleanupCancelled("Temporal visible-overlay cleanup was cancelled")
    except BaseException:
        if process.poll() is None:
            process.kill()
        output.unlink(missing_ok=True)
        raise
    finally:
        cancel_watch_stop.set()
        if cancel_watch is not None:
            cancel_watch.join(timeout=0.5)

    if return_code != 0:
        output.unlink(missing_ok=True)
        detail = (stderr or "FFmpeg tracked cleanup failed").strip()[-800:]
        raise MediaCleanupError(detail)
    if not output.is_file() or output.stat().st_size <= 0:
        raise MediaCleanupError("Tracked cleanup finished without producing an output file")

    output_sha256 = _sha256(output)
    manifest = _write_tracked_manifest(source, output, track, source_sha256, output_sha256)
    if progress_callback:
        progress_callback(100.0, "Temporal visible-overlay cleanup complete")
    return MediaCleanupResult(
        input_path=source,
        output_path=output,
        manifest_path=manifest,
        regions=(track.keyframes[0].region,),
        media_kind="video",
        source_sha256=source_sha256,
        output_sha256=output_sha256,
    )


def run_media_cleanup_tracking_self_test() -> None:
    width, height = 96, 64
    overlay_width, overlay_height = 18, 14
    positions = ((14, 18), (18, 19), (23, 21), (29, 23), (34, 25))

    def make_frame(offset_x: int, offset_y: int) -> GrayFrame:
        pixels = bytearray(width * height)
        for y in range(height):
            for x in range(width):
                pixels[y * width + x] = 45 + ((x * 2 + y * 3) % 18)
        for py in range(overlay_height):
            for px in range(overlay_width):
                if px in {2, 3, 8, 9, 14, 15} or py in {3, 4, 9, 10}:
                    value = 210 if (px + py) % 2 else 175
                    x = offset_x + px
                    y = offset_y + py
                    pixels[y * width + x] = value
        return GrayFrame(width, height, bytes(pixels)).validate()

    frames = tuple((index * 1.5, make_frame(x, y)) for index, (x, y) in enumerate(positions))
    initial = CleanupRegion(positions[2][0], positions[2][1], overlay_width, overlay_height)
    track = track_gray_frames(
        frames,
        initial,
        anchor_index=2,
        search_radius=12,
        min_confidence=0.35,
    )
    assert len(track.keyframes) == len(positions)
    for keyframe, expected in zip(track.keyframes, positions):
        assert abs(keyframe.region.x - expected[0]) <= 1, (keyframe.region, expected)
        assert abs(keyframe.region.y - expected[1]) <= 1, (keyframe.region, expected)
    assert min(item.confidence for item in track.keyframes) >= 0.35

    x_expression = build_piecewise_track_expression(track, "x")
    y_expression = build_piecewise_track_expression(track, "y")
    assert "lt(t," in x_expression and "t-" in x_expression
    assert "lt(t," in y_expression and "t-" in y_expression
    filter_chain = build_tracked_delogo_filter(track)
    assert filter_chain.startswith("delogo=x='")
    assert f":w={overlay_width}:h={overlay_height}:show=0" in filter_chain

    command = build_tracked_cleanup_command(
        Path("ffmpeg.exe"), Path("input.mp4"), Path("output.mp4"), track
    )
    assert "-vf" in command and filter_chain in command
    assert "-progress" in command and "libx264" in command
    assert command[-1] == "output.mp4"

    probe = MediaProbe(width=1920, height=1080, duration_seconds=12.0, media_kind="video")
    times = tracking_sample_times(probe, anchor_seconds=1.0, sample_count=7)
    assert times[0] == 0.0
    assert 1.0 in times
    assert times[-1] <= 12.0
    assert len(times) >= 7

    flat = GrayFrame(width, height, bytes([50] * (width * height))).validate()
    try:
        track_gray_frames(
            ((0.0, flat), (1.0, flat)),
            CleanupRegion(10, 10, overlay_width, overlay_height),
            anchor_index=0,
            search_radius=8,
        )
    except MediaCleanupError as exc:
        assert "insufficient visual structure" in str(exc)
    else:
        raise AssertionError("flat low-contrast overlay region was accepted for tracking")
