from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

TILE = "#17191D"
BORDER = "#2D3036"
INK = "#F1F2F4"
ACCENT = "#6F8FFF"


def _scaled(value: float, scale: float) -> int:
    return round(value * scale)


def draw_icon(size: int) -> Image.Image:
    """Render the Galaxy native-workbench mark at one ICO source size."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = size / 256

    def box(values: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
        return tuple(_scaled(value, scale) for value in values)  # type: ignore[return-value]

    radius = max(2, _scaled(48, scale))
    border_width = max(1, _scaled(5, scale))
    draw.rounded_rectangle(box((18, 18, 238, 238)), radius=radius, fill=TILE, outline=BORDER, width=border_width)

    # Broken G: strong white silhouette with an open upper-right edge.
    g_width = max(2, _scaled(22, scale))
    draw.arc(box((53, 52, 190, 190)), start=42, end=322, fill=INK, width=g_width)
    draw.line(box((133, 132, 190, 132)), fill=INK, width=g_width)

    # One blue action accent for download + tray.
    arrow_width = max(2, _scaled(18, scale))
    draw.line(box((166, 72, 166, 151)), fill=ACCENT, width=arrow_width)
    draw.line(box((137, 124, 166, 154)), fill=ACCENT, width=arrow_width)
    draw.line(box((166, 154, 195, 124)), fill=ACCENT, width=arrow_width)
    tray_width = max(2, _scaled(14, scale))
    draw.line(box((132, 184, 200, 184)), fill=ACCENT, width=tray_width)
    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="local-engine/GalaxyLocalEngine.ico")
    parser.add_argument("--png-output", default="")
    args = parser.parse_args()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    base = draw_icon(256)
    base.save(
        target,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    if args.png_output:
        png_target = Path(args.png_output)
        png_target.parent.mkdir(parents=True, exist_ok=True)
        base.save(png_target, format="PNG")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
