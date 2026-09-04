from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from media_cleanup import CleanupRegion, MediaCleanupError
from media_cleanup_workbench_v2 import (
    MODE_IMAGE_INPAINT,
    MODE_VIDEO_STATIC,
    MODE_VIDEO_TRACKED,
    normalize_workbench_mode,
    validate_workbench_regions,
    workbench_mode_values,
)


def main() -> None:
    image_values = workbench_mode_values("image")
    assert image_values == (("智能修复（Inpainting）", MODE_IMAGE_INPAINT),)
    video_values = dict(workbench_mode_values("video"))
    assert video_values == {
        "固定水印区域": MODE_VIDEO_STATIC,
        "移动水印跟踪": MODE_VIDEO_TRACKED,
    }
    assert normalize_workbench_mode("image", MODE_VIDEO_STATIC) == MODE_IMAGE_INPAINT
    assert normalize_workbench_mode("video", MODE_IMAGE_INPAINT) == MODE_VIDEO_STATIC
    assert validate_workbench_regions(
        "video", MODE_VIDEO_TRACKED, (CleanupRegion(3, 4, 20, 12),)
    ) == (CleanupRegion(3, 4, 20, 12),)
    try:
        workbench_mode_values("audio")
    except MediaCleanupError:
        pass
    else:
        raise AssertionError("unsupported workbench media kind was accepted")
    print("Media cleanup workbench 2.0 mode contract passed")


if __name__ == "__main__":
    main()
