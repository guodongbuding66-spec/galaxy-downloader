from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_ai_api import run_headless_ai_api_self_test  # noqa: E402


def run() -> None:
    run_headless_ai_api_self_test()


if __name__ == "__main__":
    run()
    print("Headless AI API adapter self-test passed")
