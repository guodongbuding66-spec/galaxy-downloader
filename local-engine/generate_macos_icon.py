from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from generate_icon import draw_icon

ICONSET_FILES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def generate_iconset(output_dir: Path) -> Path:
    target = output_dir.expanduser().resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    for filename, size in ICONSET_FILES.items():
        image = draw_icon(size)
        image.save(target / filename, format="PNG", optimize=True)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a macOS .iconset from the Galaxy Local Engine mark.")
    parser.add_argument("--output-dir", default="dist/GalaxyLocalEngine.iconset")
    args = parser.parse_args()
    target = generate_iconset(Path(args.output_dir))
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
