from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from asr_provider_router import run_asr_provider_router_self_test  # noqa: E402


if __name__ == "__main__":
    run_asr_provider_router_self_test()
    print("ASR provider router self-test passed")
