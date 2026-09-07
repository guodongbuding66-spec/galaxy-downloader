from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from gallery_dl_source import resolve_gallery_dl_source  # noqa: E402


def main() -> int:
    resolved = resolve_gallery_dl_source(timeout=20.0)
    artifact = resolved.artifact
    assert artifact.tool == "gallery-dl"
    assert artifact.archive == "zip"
    assert resolved.asset_name == f"gallery_dl-{artifact.version}-py3-none-any.whl"
    assert artifact.url.startswith("https://files.pythonhosted.org/")
    assert len(artifact.sha256) == 64
    assert resolved.release_tag == artifact.version
    print(f"trusted gallery-dl provider resolved {artifact.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
