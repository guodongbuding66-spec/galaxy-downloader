from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from dynamic_document import _render_html  # noqa: E402


def main() -> int:
    html, final_url, browser = _render_html("https://example.com/", "none")
    normalized = html.lower()
    if "example domain" not in normalized:
        raise RuntimeError("CDP renderer did not return the expected Example Domain document")
    if not final_url.startswith("https://example.com"):
        raise RuntimeError(f"Unexpected CDP final URL: {final_url}")
    if browser not in {"edge", "chrome"}:
        raise RuntimeError(f"Unexpected CDP browser: {browser}")
    print(f"CDP dynamic document smoke passed with {browser}: {final_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
