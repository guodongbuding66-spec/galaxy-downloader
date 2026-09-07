from __future__ import annotations


def ensure_gallery_dl_runtime_dependencies() -> tuple[str, str]:
    """Load gallery-dl HTTP dependencies only when the managed tool is used.

    Keeping these imports inside the function preserves zero-dependency policy
    tests that import tool_manager without installing Local Engine requirements,
    while PyInstaller still sees and bundles the imports statically.
    """
    import requests
    import urllib3

    return str(requests.__version__), str(urllib3.__version__)


def run_gallery_dl_runtime_dependencies_self_test() -> None:
    requests_version, urllib3_version = ensure_gallery_dl_runtime_dependencies()
    assert requests_version
    assert urllib3_version
