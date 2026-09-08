from __future__ import annotations

import importlib
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Iterator

from gallery_dl_manager import existing_managed_gallery_dl
from gallery_dl_runtime_dependencies import ensure_gallery_dl_runtime_dependencies


class GalleryDlRuntimeError(RuntimeError):
    pass


GALLERY_DL_RUNTIME_LOCK = threading.RLock()


def _clear_gallery_dl_modules() -> None:
    for name in tuple(sys.modules):
        if name == "gallery_dl" or name.startswith("gallery_dl."):
            sys.modules.pop(name, None)


def gallery_dl_runtime_busy() -> bool:
    acquired = GALLERY_DL_RUNTIME_LOCK.acquire(blocking=False)
    if acquired:
        GALLERY_DL_RUNTIME_LOCK.release()
        return False
    return True


@contextmanager
def managed_gallery_dl_modules(engine_module) -> Iterator[tuple[ModuleType, ModuleType, ModuleType]]:
    """Load the verified managed gallery-dl package for one serialized task.

    gallery-dl keeps process-global configuration and lazily imports extractor
    modules. Keep a runtime lock for the full job, load only from Galaxy's
    verified managed wheel directory, and remove those modules afterwards so a
    later explicit tool update cannot leave stale package code in memory.
    """
    with GALLERY_DL_RUNTIME_LOCK:
        root = existing_managed_gallery_dl(engine_module)
        if root is None:
            raise GalleryDlRuntimeError("gallery-dl 尚未安装。请先在工具管理中显式安装 gallery-dl。")
        root = Path(root).resolve()
        if not root.is_dir() or root.is_symlink():
            raise GalleryDlRuntimeError("Managed gallery-dl 目录不可用。")

        ensure_gallery_dl_runtime_dependencies()
        root_text = str(root)
        _clear_gallery_dl_modules()
        sys.path.insert(0, root_text)
        importlib.invalidate_caches()
        try:
            package = importlib.import_module("gallery_dl")
            package_file = Path(str(getattr(package, "__file__", "") or "")).resolve()
            if root not in package_file.parents:
                raise GalleryDlRuntimeError("gallery-dl 未从 Galaxy 托管目录加载。")
            config = importlib.import_module("gallery_dl.config")
            job = importlib.import_module("gallery_dl.job")
            exception = importlib.import_module("gallery_dl.exception")
            yield config, job, exception
        finally:
            try:
                config_module = sys.modules.get("gallery_dl.config")
                clear = getattr(config_module, "clear", None)
                if callable(clear):
                    clear()
            except Exception:
                pass
            _clear_gallery_dl_modules()
            try:
                sys.path.remove(root_text)
            except ValueError:
                pass
            importlib.invalidate_caches()


def run_gallery_dl_runtime_self_test() -> None:
    assert gallery_dl_runtime_busy() is False
    with GALLERY_DL_RUNTIME_LOCK:
        # RLock is intentionally re-entrant for manager/executor composition.
        assert gallery_dl_runtime_busy() is False
