from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
MAX_CLEANUP_REGIONS = 16
MAX_REGION_COORDINATE = 100_000


class MediaCleanupError(RuntimeError):
    pass


class MediaCleanupCancelled(MediaCleanupError):
    pass


@dataclass(frozen=True)
class CleanupRegion:
    x: int
    y: int
    width: int
    height: int

    def validate(self) -> "CleanupRegion":
        values = (self.x, self.y, self.width, self.height)
        if any(not isinstance(value, int) for value in values):
            raise MediaCleanupError("Cleanup region values must be integers")
        if self.x < 0 or self.y < 0:
            raise MediaCleanupError("Cleanup region coordinates must be non-negative")
        if self.width < 2 or self.height < 2:
            raise MediaCleanupError("Cleanup region width and height must be at least 2 pixels")
        if any(value > MAX_REGION_COORDINATE for value in values):
            raise MediaCleanupError("Cleanup region is outside the supported coordinate range")
        return self


@dataclass(frozen=True)
class MediaProbe:
    width: int
    height: int
    duration_seconds: float
    media_kind: str


@dataclass(frozen=True)
class MediaCleanupResult:
    input_path: Path
    output_path: Path
    manifest_path: Path
    regions: tuple[CleanupRegion, ...]
    media_kind: str
    source_sha256: str
    output_sha256: str


ProgressCallback = Callable[[float, str], None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tool_path(ffmpeg_dir: Path, tool: str) -> Path:
    exe_name = f"{tool}.exe"
    for name in (exe_name, tool):
        candidate = ffmpeg_dir / name
        if candidate.exists() and candidate.is_file():
            return candidate
    raise MediaCleanupError(f"Required {tool} executable was not found in {ffmpeg_dir}")


def _validate_input(path: Path) -> tuple[Path, str]:
    source = path.expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise MediaCleanupError("Input media file does not exist")
    suffix = source.suffix.lower()
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return source, "image"
    if suffix in SUPPORTED_VIDEO_SUFFIXES:
        return source, "video"
    raise MediaCleanupError(f"Unsupported cleanup media type: {suffix or '(no extension)'}")


def _normalize_regions(regions: Iterable[CleanupRegion]) -> tuple[CleanupRegion, ...]:
    normalized = tuple(region.validate() for region in regions)
    if not normalized:
        raise MediaCleanupError("At least one cleanup region is required")
    if len(normalized) > MAX_CLEANUP_REGIONS:
        raise MediaCleanupError(f"At most {MAX_CLEANUP_REGIONS} cleanup regions are supported")
    return normalized


def _manifest_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".cleanup.json")


def _output_slot_available(output: Path) -> bool:
    return not output.exists() and not _manifest_path(output).exists()


def _default_output_path(source: Path, media_kind: str) -> Path:
    suffix = ".mp4" if media_kind == "video" else source.suffix.lower()
    base = source.with_name(f"{source.stem}.cleaned{suffix}")
    if _output_slot_available(base):
        return base
    for index in range(2, 10_000):
        candidate = source.with_name(f"{source.stem}.cleaned-{index}{suffix}")
        if _output_slot_available(candidate):
            return candidate
    raise MediaCleanupError("Could not allocate a non-destructive cleanup output path")


def _validate_output(source: Path, output_path: Path | None, media_kind: str) -> Path:
    explicit_output = output_path is not None
    output = (output_path or _default_output_path(source, media_kind)).expanduser().resolve()
    if output == source:
        raise MediaCleanupError("Cleanup output must not overwrite the original media file")
    if media_kind == "image" and output.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        raise MediaCleanupError("Image cleanup output must be JPG, PNG or WebP")
    if media_kind == "video" and output.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise MediaCleanupError("Video cleanup output must be MP4, MOV, MKV or WebM")
    output.parent.mkdir(parents=True, exist_ok=True)
    if explicit_output and not _output_slot_available(output):
        raise MediaCleanupError("Cleanup output already exists; choose a new file name")
    return output


def probe_media(ffprobe_path: Path, source: Path, expected_kind: str) -> MediaProbe:
    command = [
        str(ffprobe_path),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:format=duration",
        "-of",
        "json",
        str(source),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except OSError as exc:
        raise MediaCleanupError(f"Could not start ffprobe: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaCleanupError("Timed out while reading media dimensions") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "ffprobe failed").strip()[-500:]
        raise MediaCleanupError(f"Could not inspect input media: {detail}")
    try:
        payload = json.loads(completed.stdout or "{}")
        stream = (payload.get("streams") or [])[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        duration = float((payload.get("format") or {}).get("duration") or 0.0)
    except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaCleanupError("Input media did not expose a usable video/image frame") from exc
    if width < 2 or height < 2:
        raise MediaCleanupError("Input media has invalid frame dimensions")
    if expected_kind == "image":
        duration = 0.0
    return MediaProbe(width=width, height=height, duration_seconds=max(0.0, duration), media_kind=expected_kind)


def _validate_regions_within_frame(regions: tuple[CleanupRegion, ...], probe: MediaProbe) -> None:
    for region in regions:
        if region.x + region.width > probe.width or region.y + region.height > probe.height:
            raise MediaCleanupError(
                f"Cleanup region {region} exceeds the {probe.width}x{probe.height} media frame"
            )


def build_delogo_filter(regions: tuple[CleanupRegion, ...]) -> str:
    return ",".join(
        f"delogo=x={region.x}:y={region.y}:w={region.width}:h={region.height}:show=0"
        for region in regions
    )


def build_cleanup_command(
    ffmpeg_path: Path,
    source: Path,
    output: Path,
    regions: tuple[CleanupRegion, ...],
    media_kind: str,
) -> list[str]:
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
        build_delogo_filter(regions),
        "-map_metadata",
        "0",
    ]
    suffix = output.suffix.lower()
    if media_kind == "image":
        command.extend(["-frames:v", "1"])
        if suffix in {".jpg", ".jpeg"}:
            command.extend(["-q:v", "2"])
        elif suffix == ".png":
            command.extend(["-c:v", "png", "-compression_level", "6"])
        elif suffix == ".webp":
            command.extend(["-c:v", "libwebp", "-quality", "95"])
    else:
        command.extend(["-map", "0:v:0", "-map", "0:a?"])
        if suffix == ".webm":
            command.extend(["-c:v", "libvpx-vp9", "-crf", "18", "-b:v", "0", "-c:a", "libopus"])
        else:
            command.extend(["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "192k"])
            if suffix in {".mp4", ".mov"}:
                command.extend(["-movflags", "+faststart"])
        command.extend(["-progress", "pipe:1", "-nostats"])
    command.append(str(output))
    return command


def _parse_progress_seconds(line: str) -> float | None:
    key, separator, value = line.partition("=")
    if not separator:
        return None
    try:
        if key == "out_time_us":
            return max(0.0, float(value) / 1_000_000.0)
        if key == "out_time_ms":
            # FFmpeg historically labels microseconds as out_time_ms. Prefer
            # out_time_us when present, but keep compatibility with older builds.
            return max(0.0, float(value) / 1_000_000.0)
    except ValueError:
        return None
    return None


def _write_manifest(
    source: Path,
    output: Path,
    regions: tuple[CleanupRegion, ...],
    media_kind: str,
    source_sha256: str,
    output_sha256: str,
) -> Path:
    manifest = _manifest_path(output)
    payload = {
        "schemaVersion": 1,
        "operation": "visible-overlay-cleanup",
        "method": "ffmpeg-delogo",
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mediaKind": media_kind,
        "sourceFile": source.name,
        "outputFile": output.name,
        "sourceSha256": source_sha256,
        "outputSha256": output_sha256,
        "regions": [
            {"x": region.x, "y": region.y, "width": region.width, "height": region.height}
            for region in regions
        ],
        "note": "Pixels were edited to remove a visible overlay. This tool does not target invisible provenance or authenticity markers.",
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def cleanup_visible_overlay(
    ffmpeg_directory: Path,
    input_path: Path,
    regions: Iterable[CleanupRegion],
    *,
    output_path: Path | None = None,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> MediaCleanupResult:
    source, media_kind = _validate_input(input_path)
    normalized_regions = _normalize_regions(regions)
    output = _validate_output(source, output_path, media_kind)
    ffmpeg_path = _tool_path(ffmpeg_directory, "ffmpeg")
    ffprobe_path = _tool_path(ffmpeg_directory, "ffprobe")
    probe = probe_media(ffprobe_path, source, media_kind)
    _validate_regions_within_frame(normalized_regions, probe)

    source_sha256 = _sha256(source)
    if cancel_event is not None and cancel_event.is_set():
        raise MediaCleanupCancelled("Visible overlay cleanup was cancelled")
    if progress_callback:
        progress_callback(0.0, "Preparing visible overlay cleanup")

    command = build_cleanup_command(ffmpeg_path, source, output, normalized_regions, media_kind)
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

        cancel_watch = threading.Thread(
            target=watch_cancel,
            name="GalaxyMediaCleanupCancel",
            daemon=True,
        )
        cancel_watch.start()

    try:
        if media_kind == "video" and process.stdout is not None:
            for raw_line in process.stdout:
                seconds = _parse_progress_seconds(raw_line.strip())
                if seconds is not None and probe.duration_seconds > 0:
                    percent = max(0.0, min(99.0, seconds / probe.duration_seconds * 100.0))
                    if progress_callback:
                        progress_callback(percent, "Cleaning video frames")

        return_code = process.wait()
        stderr = process.stderr.read() if process.stderr is not None else ""
        if cancel_event is not None and cancel_event.is_set():
            raise MediaCleanupCancelled("Visible overlay cleanup was cancelled")
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
        detail = (stderr or "FFmpeg cleanup failed").strip()[-800:]
        raise MediaCleanupError(detail)
    if not output.exists() or output.stat().st_size <= 0:
        raise MediaCleanupError("Cleanup finished without producing an output file")

    output_sha256 = _sha256(output)
    manifest = _write_manifest(
        source,
        output,
        normalized_regions,
        media_kind,
        source_sha256,
        output_sha256,
    )
    if progress_callback:
        progress_callback(100.0, "Visible overlay cleanup complete")
    return MediaCleanupResult(
        input_path=source,
        output_path=output,
        manifest_path=manifest,
        regions=normalized_regions,
        media_kind=media_kind,
        source_sha256=source_sha256,
        output_sha256=output_sha256,
    )


def run_media_cleanup_self_test() -> None:
    regions = (
        CleanupRegion(10, 20, 120, 48).validate(),
        CleanupRegion(300, 400, 80, 30).validate(),
    )
    filter_chain = build_delogo_filter(regions)
    assert filter_chain.count("delogo=") == 2
    assert "x=10:y=20:w=120:h=48" in filter_chain
    command = build_cleanup_command(
        Path("ffmpeg.exe"),
        Path("input.mp4"),
        Path("output.mp4"),
        regions,
        "video",
    )
    assert "-vf" in command
    assert "libx264" in command
    assert "-progress" in command
    assert "-n" in command
    assert "-y" not in command
    assert command[-1] == "output.mp4"
    image_command = build_cleanup_command(
        Path("ffmpeg.exe"),
        Path("input.png"),
        Path("output.png"),
        regions[:1],
        "image",
    )
    assert "-frames:v" in image_command
    assert "png" in image_command
