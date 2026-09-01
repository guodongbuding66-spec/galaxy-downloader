from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-engine"))

from image_archive_policy import install_image_archive_policy  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    state = {"status": "Ready", "lastPath": None, "detail": ""}

    def set_state(**values):
        state.update(values)

    def image_job_status():
        return dict(state)

    def run_image_job(payload):
        archive_path = root / "demo.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("demo-1.jpg", b"one")
            archive.writestr("demo-2.png", b"two")
            archive.writestr("demo.md", b"# demo")
        set_state(status="Completed", lastPath=str(archive_path), detail="Saved")

    module = SimpleNamespace(
        _run_image_job=run_image_job,
        image_job_status=image_job_status,
        _set_state=set_state,
    )
    install_image_archive_policy(module)
    module._run_image_job(
        {
            "images": ["https://example.com/1.jpg", "https://example.com/2.png"],
            "title": "demo",
            "author": "Guo Dong",
            "publishedAt": "2026-09-01",
            "sourceUrl": "https://example.com/post",
            "platform": "example",
            "archiveFormat": "cbz",
        }
    )

    final_path = Path(state["lastPath"])
    assert final_path.suffix == ".cbz"
    assert final_path.exists()
    with zipfile.ZipFile(final_path, "r") as archive:
        metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
    assert metadata["author"] == "Guo Dong"
    assert metadata["sourceUrl"] == "https://example.com/post"
    assert metadata["platform"] == "example"
    assert metadata["archiveFormat"] == "cbz"
    assert metadata["images"] == [
        {"originalImageUrl": "https://example.com/1.jpg", "localFile": "demo-1.jpg"},
        {"originalImageUrl": "https://example.com/2.png", "localFile": "demo-2.png"},
    ]

print("local image archive policy tests OK")
