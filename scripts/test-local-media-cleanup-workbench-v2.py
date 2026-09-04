from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import media_cleanup_workbench as legacy
from media_cleanup import CleanupRegion, MediaCleanupError
from media_cleanup_workbench_v2 import (
    MODE_IMAGE_INPAINT,
    MODE_VIDEO_STATIC,
    MODE_VIDEO_TRACKED,
    install_media_cleanup_workbench_v2_patch,
    normalize_workbench_mode,
    run_media_cleanup_workbench_v2_self_test,
    validate_workbench_regions,
    workbench_mode_values,
)


def main() -> None:
    run_media_cleanup_workbench_v2_self_test()

    assert dict(workbench_mode_values("image"))["智能修复（Inpainting）"] == MODE_IMAGE_INPAINT
    video = dict(workbench_mode_values("video"))
    assert video["固定水印区域"] == MODE_VIDEO_STATIC
    assert video["移动水印跟踪"] == MODE_VIDEO_TRACKED
    assert normalize_workbench_mode("image", MODE_VIDEO_TRACKED) == MODE_IMAGE_INPAINT
    assert normalize_workbench_mode("video", "") == MODE_VIDEO_STATIC

    one = (CleanupRegion(10, 12, 80, 32),)
    assert validate_workbench_regions("video", MODE_VIDEO_TRACKED, one) == one
    try:
        validate_workbench_regions(
            "video",
            MODE_VIDEO_TRACKED,
            (CleanupRegion(1, 2, 20, 20), CleanupRegion(40, 50, 20, 20)),
        )
    except MediaCleanupError:
        pass
    else:
        raise AssertionError("moving tracking accepted multiple regions")

    install_media_cleanup_workbench_v2_patch()
    assert getattr(legacy, "_galaxy_media_cleanup_v2_patched", False) is True
    assert legacy._show_workbench.__module__ == "media_cleanup_workbench_v2"
    print("Media cleanup workbench 2.0 self-test passed")


if __name__ == "__main__":
    main()
