from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from media_cleanup import MediaCleanupError, MediaProbe, _tool_path, _validate_input, probe_media
from media_cleanup_workbench import CleanupPreviewPlan, fit_preview_size, generate_preview_png

COMPARISON_GAP = 12
COMPARISON_LABEL_HEIGHT = 28


@dataclass(frozen=True)
class CleanupComparisonArtifact:
    source_path: Path
    output_path: Path
    comparison_path: Path
    media_kind: str
    seek_seconds: float
    preview_width: int
    preview_height: int


def comparison_seek_seconds(
    source_probe: MediaProbe,
    output_probe: MediaProbe,
    *,
    requested_seconds: float | None = None,
) -> float:
    if source_probe.media_kind != output_probe.media_kind:
        raise MediaCleanupError("Before/after comparison media kinds do not match")
    if source_probe.width != output_probe.width or source_probe.height != output_probe.height:
        raise MediaCleanupError("Before/after comparison frame dimensions do not match")
    if source_probe.media_kind != "video":
        return 0.0
    duration = min(source_probe.duration_seconds, output_probe.duration_seconds)
    if duration <= 0:
        raise MediaCleanupError("Before/after video comparison requires a known duration")
    if requested_seconds is None:
        requested = min(1.0, duration / 2.0)
    else:
        requested = max(0.0, float(requested_seconds))
    return max(0.0, min(requested, max(0.0, duration - 0.01)))


def build_comparison_preview_plan(
    source_probe: MediaProbe,
    output_probe: MediaProbe,
    *,
    requested_seconds: float | None = None,
    max_width: int = 720,
    max_height: int = 440,
) -> CleanupPreviewPlan:
    seek = comparison_seek_seconds(
        source_probe,
        output_probe,
        requested_seconds=requested_seconds,
    )
    width, height = fit_preview_size(
        source_probe.width,
        source_probe.height,
        max_width=max_width,
        max_height=max_height,
    )
    return CleanupPreviewPlan(
        media_kind=source_probe.media_kind,
        source_width=source_probe.width,
        source_height=source_probe.height,
        preview_width=width,
        preview_height=height,
        seek_seconds=seek,
    )


def _comparison_output_path(cleaned: Path) -> Path:
    first = cleaned.with_name(f"{cleaned.stem}.comparison.png")
    if not first.exists():
        return first
    for index in range(2, 10_000):
        candidate = cleaned.with_name(f"{cleaned.stem}.comparison-{index}.png")
        if not candidate.exists():
            return candidate
    raise MediaCleanupError("Could not allocate a non-destructive comparison image path")


def compose_comparison_png(
    before_png: Path,
    after_png: Path,
    output_png: Path,
    *,
    before_label: str = "Before",
    after_label: str = "After",
) -> Path:
    if output_png.exists():
        raise MediaCleanupError("Comparison output already exists")
    try:
        with Image.open(before_png) as before_opened, Image.open(after_png) as after_opened:
            before = before_opened.convert("RGB")
            after = after_opened.convert("RGB")
    except Exception as exc:
        raise MediaCleanupError(f"Could not read comparison preview images: {exc}") from exc
    if before.size != after.size:
        raise MediaCleanupError("Before/after preview image dimensions do not match")

    width, height = before.size
    canvas = Image.new(
        "RGB",
        (width * 2 + COMPARISON_GAP, height + COMPARISON_LABEL_HEIGHT),
        (24, 28, 36),
    )
    canvas.paste(before, (0, COMPARISON_LABEL_HEIGHT))
    canvas.paste(after, (width + COMPARISON_GAP, COMPARISON_LABEL_HEIGHT))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 7), before_label, fill=(235, 238, 244))
    draw.text((width + COMPARISON_GAP + 8, 7), after_label, fill=(235, 238, 244))
    divider_x = width + COMPARISON_GAP // 2
    draw.line(
        (divider_x, COMPARISON_LABEL_HEIGHT, divider_x, height + COMPARISON_LABEL_HEIGHT),
        fill=(160, 166, 178),
        width=1,
    )
    output_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_png, format="PNG", compress_level=6)
    if not output_png.is_file() or output_png.stat().st_size <= 0:
        raise MediaCleanupError("Before/after comparison renderer did not produce an image")
    return output_png


def render_cleanup_comparison(
    ffmpeg_directory: Path,
    source_path: Path,
    cleaned_path: Path,
    *,
    output_path: Path | None = None,
    seek_seconds: float | None = None,
) -> CleanupComparisonArtifact:
    source, source_kind = _validate_input(source_path)
    cleaned, cleaned_kind = _validate_input(cleaned_path)
    if source_kind != cleaned_kind:
        raise MediaCleanupError("Before/after comparison media kinds do not match")
    if source == cleaned:
        raise MediaCleanupError("Before/after comparison requires two different files")

    ffmpeg_path = _tool_path(ffmpeg_directory, "ffmpeg")
    ffprobe_path = _tool_path(ffmpeg_directory, "ffprobe")
    source_probe = probe_media(ffprobe_path, source, source_kind)
    cleaned_probe = probe_media(ffprobe_path, cleaned, cleaned_kind)
    plan = build_comparison_preview_plan(
        source_probe,
        cleaned_probe,
        requested_seconds=seek_seconds,
    )
    destination = (output_path or _comparison_output_path(cleaned)).expanduser().resolve()
    if destination.suffix.lower() != ".png":
        raise MediaCleanupError("Before/after comparison output must be PNG")
    if destination.exists():
        raise MediaCleanupError("Before/after comparison output already exists")

    with tempfile.TemporaryDirectory(prefix="galaxy-cleanup-compare-") as directory:
        temp = Path(directory)
        before_png = temp / "before.png"
        after_png = temp / "after.png"
        generate_preview_png(ffmpeg_path, source, before_png, plan)
        generate_preview_png(ffmpeg_path, cleaned, after_png, plan)
        compose_comparison_png(before_png, after_png, destination)

    return CleanupComparisonArtifact(
        source_path=source,
        output_path=cleaned,
        comparison_path=destination,
        media_kind=source_kind,
        seek_seconds=plan.seek_seconds,
        preview_width=plan.preview_width,
        preview_height=plan.preview_height,
    )


def run_media_cleanup_comparison_self_test() -> None:
    import tempfile

    source_probe = MediaProbe(1920, 1080, 20.0, "video")
    output_probe = MediaProbe(1920, 1080, 19.9, "video")
    plan = build_comparison_preview_plan(
        source_probe,
        output_probe,
        requested_seconds=5.5,
        max_width=640,
        max_height=360,
    )
    assert plan.seek_seconds == 5.5
    assert plan.preview_width == 640 and plan.preview_height == 360
    assert comparison_seek_seconds(
        MediaProbe(800, 600, 0.0, "image"),
        MediaProbe(800, 600, 0.0, "image"),
        requested_seconds=9.0,
    ) == 0.0

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        before = root / "before.png"
        after = root / "after.png"
        output = root / "comparison.png"
        Image.new("RGB", (80, 50), (40, 60, 90)).save(before)
        Image.new("RGB", (80, 50), (70, 90, 120)).save(after)
        compose_comparison_png(before, after, output)
        assert output.is_file() and output.stat().st_size > 0
        with Image.open(output) as rendered:
            assert rendered.size == (80 * 2 + COMPARISON_GAP, 50 + COMPARISON_LABEL_HEIGHT)
            assert rendered.getpixel((10, COMPARISON_LABEL_HEIGHT + 10)) == (40, 60, 90)
            assert rendered.getpixel((80 + COMPARISON_GAP + 10, COMPARISON_LABEL_HEIGHT + 10)) == (70, 90, 120)
        try:
            compose_comparison_png(before, after, output)
        except MediaCleanupError:
            pass
        else:
            raise AssertionError("existing comparison output was overwritten")

    try:
        comparison_seek_seconds(
            MediaProbe(1920, 1080, 3.0, "video"),
            MediaProbe(1280, 720, 3.0, "video"),
        )
    except MediaCleanupError:
        pass
    else:
        raise AssertionError("mismatched comparison dimensions were accepted")
