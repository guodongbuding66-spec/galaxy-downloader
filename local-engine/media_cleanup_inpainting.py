from __future__ import annotations

import hashlib
import json
import threading
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageStat

from media_cleanup import (
    MAX_CLEANUP_REGIONS,
    CleanupRegion,
    MediaCleanupCancelled,
    MediaCleanupError,
    MediaCleanupResult,
    ProgressCallback,
    SUPPORTED_IMAGE_SUFFIXES,
)

DEFAULT_INPAINT_ITERATIONS = 28
MIN_INPAINT_ITERATIONS = 4
MAX_INPAINT_ITERATIONS = 96
MAX_INPAINT_COVERAGE = 0.50


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".cleanup.json")


def _slot_available(output: Path) -> bool:
    return not output.exists() and not _manifest_path(output).exists()


def _default_output_path(source: Path) -> Path:
    first = source.with_name(f"{source.stem}.inpainted{source.suffix.lower()}")
    if _slot_available(first):
        return first
    for index in range(2, 10_000):
        candidate = source.with_name(
            f"{source.stem}.inpainted-{index}{source.suffix.lower()}"
        )
        if _slot_available(candidate):
            return candidate
    raise MediaCleanupError("Could not allocate a non-destructive inpainting output path")


def _validate_source(input_path: Path) -> Path:
    source = input_path.expanduser().resolve()
    if not source.is_file():
        raise MediaCleanupError("Input image file does not exist")
    if source.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        raise MediaCleanupError("Image inpainting supports JPG, PNG and WebP images only")
    if source.is_symlink():
        raise MediaCleanupError("Image inpainting input cannot be a symbolic link")
    return source


def _validate_output(source: Path, output_path: Path | None) -> Path:
    explicit = output_path is not None
    output = (output_path or _default_output_path(source)).expanduser().resolve()
    if output == source:
        raise MediaCleanupError("Image inpainting must not overwrite the original image")
    if output.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        raise MediaCleanupError("Image inpainting output must be JPG, PNG or WebP")
    if output.is_symlink():
        raise MediaCleanupError("Image inpainting output cannot be a symbolic link")
    output.parent.mkdir(parents=True, exist_ok=True)
    if explicit and not _slot_available(output):
        raise MediaCleanupError("Image inpainting output already exists; choose a new file name")
    return output


def _normalize_regions(
    regions: Iterable[CleanupRegion],
    *,
    width: int,
    height: int,
) -> tuple[CleanupRegion, ...]:
    normalized = tuple(region.validate() for region in regions)
    if not normalized:
        raise MediaCleanupError("At least one image inpainting region is required")
    if len(normalized) > MAX_CLEANUP_REGIONS:
        raise MediaCleanupError(
            f"At most {MAX_CLEANUP_REGIONS} image inpainting regions are supported"
        )
    frame_area = max(1, width * height)
    covered = 0
    for region in normalized:
        if region.x + region.width > width or region.y + region.height > height:
            raise MediaCleanupError(
                f"Image inpainting region {region} exceeds the {width}x{height} image"
            )
        covered += region.width * region.height
    if covered / frame_area > MAX_INPAINT_COVERAGE:
        raise MediaCleanupError(
            "Image inpainting regions cover too much of the frame for reliable reconstruction"
        )
    return normalized


def _bounded_iterations(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_INPAINT_ITERATIONS
    return max(MIN_INPAINT_ITERATIONS, min(parsed, MAX_INPAINT_ITERATIONS))


def _working_mode(image: Image.Image) -> str:
    return "RGBA" if "A" in image.getbands() else "RGB"


def _border_mean(image: Image.Image, region: CleanupRegion) -> tuple[int, ...]:
    padding = max(3, min(12, max(region.width, region.height) // 8))
    left = max(0, region.x - padding)
    top = max(0, region.y - padding)
    right = min(image.width, region.x + region.width + padding)
    bottom = min(image.height, region.y + region.height + padding)
    crop = image.crop((left, top, right, bottom))
    mask = Image.new("L", crop.size, 255)
    draw = ImageDraw.Draw(mask)
    inner_left = region.x - left
    inner_top = region.y - top
    inner_right = inner_left + region.width - 1
    inner_bottom = inner_top + region.height - 1
    draw.rectangle(
        (inner_left, inner_top, inner_right, inner_bottom),
        fill=0,
    )
    stats = ImageStat.Stat(crop, mask=mask)
    means = stats.mean
    if not means or not any(stats.count):
        stats = ImageStat.Stat(crop)
        means = stats.mean
    if not means:
        raise MediaCleanupError("Could not sample pixels around an inpainting region")
    return tuple(max(0, min(255, int(round(value)))) for value in means)


def build_inpaint_mask(
    width: int,
    height: int,
    regions: tuple[CleanupRegion, ...],
) -> Image.Image:
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for region in regions:
        draw.rectangle(
            (
                region.x,
                region.y,
                region.x + region.width - 1,
                region.y + region.height - 1,
            ),
            fill=255,
        )
    return mask


def _seed_masked_pixels(
    original: Image.Image,
    regions: tuple[CleanupRegion, ...],
) -> Image.Image:
    working = original.copy()
    draw = ImageDraw.Draw(working)
    for region in regions:
        fill = _border_mean(original, region)
        draw.rectangle(
            (
                region.x,
                region.y,
                region.x + region.width - 1,
                region.y + region.height - 1,
            ),
            fill=fill,
        )
    return working


def diffusion_inpaint(
    image: Image.Image,
    regions: Iterable[CleanupRegion],
    *,
    iterations: int = DEFAULT_INPAINT_ITERATIONS,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[Image.Image, tuple[CleanupRegion, ...]]:
    original = image.convert(_working_mode(image))
    normalized = _normalize_regions(
        regions,
        width=original.width,
        height=original.height,
    )
    steps = _bounded_iterations(iterations)
    mask = build_inpaint_mask(original.width, original.height, normalized)
    working = _seed_masked_pixels(original, normalized)

    if cancel_event is not None and cancel_event.is_set():
        raise MediaCleanupCancelled("Image inpainting was cancelled")
    if progress_callback:
        progress_callback(5.0, "Preparing image inpainting mask")

    for index in range(steps):
        if cancel_event is not None and cancel_event.is_set():
            raise MediaCleanupCancelled("Image inpainting was cancelled")
        fraction = index / max(1, steps - 1)
        radius = 2.6 - 1.6 * fraction
        blurred = working.filter(ImageFilter.GaussianBlur(radius=max(0.9, radius)))
        # Keep every pixel outside the selected visible-overlay mask exactly
        # equal to the source while allowing neighboring source pixels to
        # diffuse inward over repeated iterations.
        working = Image.composite(blurred, original, mask)
        if progress_callback and (index == steps - 1 or index % 3 == 0):
            progress_callback(
                5.0 + (index + 1) / steps * 85.0,
                "Reconstructing selected image pixels",
            )
    return working, normalized


def _save_image(
    image: Image.Image,
    output: Path,
    *,
    source_info: dict,
) -> None:
    suffix = output.suffix.lower()
    format_name = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".webp": "WEBP",
    }[suffix]
    options: dict[str, object] = {}
    if format_name == "JPEG":
        if image.mode != "RGB":
            image = image.convert("RGB")
        options.update(quality=95, subsampling=0, optimize=True)
    elif format_name == "PNG":
        options.update(compress_level=6)
    elif format_name == "WEBP":
        options.update(quality=95, method=6)
    icc = source_info.get("icc_profile")
    exif = source_info.get("exif")
    if isinstance(icc, bytes):
        options["icc_profile"] = icc
    if isinstance(exif, bytes):
        options["exif"] = exif

    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.part")
    try:
        image.save(temporary, format=format_name, **options)
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise MediaCleanupError("Image inpainting did not produce a valid output file")
        temporary.replace(output)
    except Exception:
        with suppress(OSError):
            temporary.unlink()
        raise


def _write_manifest(
    source: Path,
    output: Path,
    regions: tuple[CleanupRegion, ...],
    source_sha256: str,
    output_sha256: str,
    iterations: int,
) -> Path:
    manifest = _manifest_path(output)
    temporary = manifest.with_name(f".{manifest.name}.{uuid.uuid4().hex}.part")
    payload = {
        "schemaVersion": 1,
        "operation": "visible-overlay-cleanup",
        "method": "pillow-diffusion-inpaint",
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mediaKind": "image",
        "sourceFile": source.name,
        "outputFile": output.name,
        "sourceSha256": source_sha256,
        "outputSha256": output_sha256,
        "iterations": iterations,
        "regions": [
            {"x": item.x, "y": item.y, "width": item.width, "height": item.height}
            for item in regions
        ],
        "note": (
            "Selected visible pixels were reconstructed from surrounding image content. "
            "This tool does not target invisible provenance or authenticity markers."
        ),
    }
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(manifest)
    except Exception:
        with suppress(OSError):
            temporary.unlink()
        raise
    return manifest


def inpaint_visible_overlay_image(
    input_path: Path,
    regions: Iterable[CleanupRegion],
    *,
    output_path: Path | None = None,
    iterations: int = DEFAULT_INPAINT_ITERATIONS,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> MediaCleanupResult:
    source = _validate_source(input_path)
    output = _validate_output(source, output_path)
    steps = _bounded_iterations(iterations)
    source_sha256 = _sha256(source)

    try:
        with Image.open(source) as opened:
            source_info = dict(opened.info)
            opened.load()
            rendered, normalized = diffusion_inpaint(
                opened,
                regions,
                iterations=steps,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )
    except MediaCleanupError:
        raise
    except MediaCleanupCancelled:
        raise
    except Exception as exc:
        raise MediaCleanupError(f"Could not decode image for inpainting: {exc}") from exc

    if cancel_event is not None and cancel_event.is_set():
        raise MediaCleanupCancelled("Image inpainting was cancelled")
    if progress_callback:
        progress_callback(92.0, "Writing inpainted image")

    try:
        _save_image(rendered, output, source_info=source_info)
        output_sha256 = _sha256(output)
        manifest = _write_manifest(
            source,
            output,
            normalized,
            source_sha256,
            output_sha256,
            steps,
        )
    except Exception:
        with suppress(OSError):
            output.unlink()
        raise

    if progress_callback:
        progress_callback(100.0, "Image inpainting complete")
    return MediaCleanupResult(
        input_path=source,
        output_path=output,
        manifest_path=manifest,
        regions=normalized,
        media_kind="image",
        source_sha256=source_sha256,
        output_sha256=output_sha256,
    )


def run_media_cleanup_inpainting_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "sample.png"
        image = Image.new("RGB", (80, 60))
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                pixels[x, y] = (60 + x, 70 + y, 100 + (x + y) // 4)
        overlay = CleanupRegion(30, 20, 16, 12)
        ImageDraw.Draw(image).rectangle((30, 20, 45, 31), fill=(0, 0, 0))
        image.save(source)
        before_outside = image.getpixel((5, 5))

        progress: list[float] = []
        result = inpaint_visible_overlay_image(
            source,
            (overlay,),
            iterations=12,
            progress_callback=lambda value, _message: progress.append(value),
        )
        assert result.input_path == source.resolve()
        assert result.output_path.is_file()
        assert result.output_path != source.resolve()
        assert result.manifest_path.is_file()
        assert result.source_sha256 != result.output_sha256
        assert progress and progress[-1] == 100.0

        with Image.open(result.output_path) as cleaned:
            cleaned.load()
            assert cleaned.getpixel((5, 5)) == before_outside
            center = cleaned.getpixel((38, 26))
            assert max(center[:3]) > 20

        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        assert manifest["method"] == "pillow-diffusion-inpaint"
        assert manifest["mediaKind"] == "image"
        assert manifest["regions"][0]["x"] == 30
        assert "invisible provenance" in manifest["note"]

        try:
            inpaint_visible_overlay_image(
                source,
                (CleanupRegion(75, 55, 10, 10),),
            )
        except MediaCleanupError:
            pass
        else:
            raise AssertionError("out-of-frame inpainting region was accepted")

        cancelled = threading.Event()
        cancelled.set()
        try:
            inpaint_visible_overlay_image(source, (overlay,), cancel_event=cancelled)
        except MediaCleanupCancelled:
            pass
        else:
            raise AssertionError("pre-cancelled image inpainting was not cancelled")

        occupied = root / "occupied.png"
        occupied.write_bytes(b"occupied")
        try:
            inpaint_visible_overlay_image(source, (overlay,), output_path=occupied)
        except MediaCleanupError:
            pass
        else:
            raise AssertionError("existing inpainting output was overwritten")
