from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import desktop_hooks
import media_cleanup_batch_ui


class FakeWindow:
    def close_app(self) -> None:
        return None


class FreshWindow:
    def close_app(self) -> None:
        return None


def main() -> None:
    media_cleanup_batch_ui.run_media_cleanup_batch_ui_self_test()

    media_cleanup_batch_ui.install_media_cleanup_batch_ui(FakeWindow)
    media_cleanup_batch_ui.install_media_cleanup_batch_ui(FakeWindow)
    assert getattr(FakeWindow, "_galaxy_media_cleanup_batch_ui_installed", False) is True
    assert desktop_hooks.registered_after_build_ui_hooks(FakeWindow).count("media-cleanup-batch-ui") == 1
    assert desktop_hooks.registered_before_close_hooks(FakeWindow).count("media-cleanup-batch-ui") == 1

    desktop_hooks._install_builtin_runtime_hooks(FreshWindow)
    desktop_hooks._install_builtin_runtime_hooks(FreshWindow)
    assert getattr(FreshWindow, "_galaxy_builtin_runtime_hooks_installed", False) is True
    assert getattr(FreshWindow, "_galaxy_media_cleanup_batch_ui_installed", False) is True
    assert desktop_hooks.registered_after_build_ui_hooks(FreshWindow).count("media-cleanup-batch-ui") == 1
    assert desktop_hooks.registered_before_close_hooks(FreshWindow).count("media-cleanup-batch-ui") == 1

    specs = media_cleanup_batch_ui.build_batch_specs(
        ("/tmp/a.png", "/tmp/b.mp4"),
        mode="auto",
        x=10,
        y=12,
        width=100,
        height=60,
    )
    assert len(specs) == 2
    assert all(item["regions"][0]["width"] == 100 for item in specs)

    print("Media cleanup Batch Task Center desktop contract passed")


if __name__ == "__main__":
    main()
