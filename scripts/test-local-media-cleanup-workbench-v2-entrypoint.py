from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import media_cleanup_workbench as legacy
from media_cleanup_workbench_v2 import install_media_cleanup_workbench_v2_patch


def main() -> None:
    install_media_cleanup_workbench_v2_patch()
    assert getattr(legacy, "_galaxy_media_cleanup_v2_patched", False) is True
    assert legacy._show_workbench.__module__ == "media_cleanup_workbench_v2"
    print("Workbench 2.0 entrypoint activation contract passed")


if __name__ == "__main__":
    main()
