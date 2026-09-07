from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from gallery_dl_manager import gallery_dl_version  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        package = root / "gallery_dl"
        package.mkdir()
        (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
        (package / "__main__.py").write_text("def main():\n    return 0\n", encoding="utf-8")
        dist = root / "gallery_dl-1.32.11.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: gallery-dl\nVersion: 1.32.11\n\n",
            encoding="utf-8",
        )
        assert gallery_dl_version(root) == "1.32.11"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
