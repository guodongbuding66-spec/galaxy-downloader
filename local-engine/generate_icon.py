from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

BG = "#0A0F1C"
VIOLET = "#8A6CFF"
VIOLET_SOFT = "#B4A5FF"
CYAN = "#35D4BC"


def draw_icon(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (10, 15, 28, 255))
    draw = ImageDraw.Draw(image)
    scale = size / 256

    def box(values: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return tuple(round(value * scale) for value in values)  # type: ignore[return-value]

    ring_width = max(2, round(20 * scale))
    orbit_width = max(1, round(8 * scale))
    arrow_width = max(2, round(22 * scale))

    draw.ellipse(box((54, 54, 202, 202)), outline=VIOLET, width=ring_width)
    draw.arc(box((28, 74, 228, 186)), start=198, end=342, fill=VIOLET_SOFT, width=orbit_width)
    draw.ellipse(box((194, 70, 216, 92)), fill=CYAN)

    draw.line(box((128, 62, 128, 137)), fill=CYAN, width=arrow_width)
    draw.line(box((94, 118, 128, 154)), fill=CYAN, width=arrow_width)
    draw.line(box((128, 154, 162, 118)), fill=CYAN, width=arrow_width)

    # Tiny lower spark makes the mark identifiable at 32/48px without adding
    # another generic download-arrow enclosure.
    draw.polygon(
        [
            (round(183 * scale), round(178 * scale)),
            (round(193 * scale), round(195 * scale)),
            (round(211 * scale), round(202 * scale)),
            (round(193 * scale), round(209 * scale)),
            (round(183 * scale), round(226 * scale)),
            (round(176 * scale), round(209 * scale)),
            (round(158 * scale), round(202 * scale)),
            (round(176 * scale), round(195 * scale)),
        ],
        fill=VIOLET_SOFT,
    )
    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="local-engine/GalaxyLocalEngine.ico")
    args = parser.parse_args()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    base = draw_icon(256)
    base.save(
        target,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
