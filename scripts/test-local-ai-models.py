from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from ai_models import run_ai_models_self_test  # noqa: E402
from runtime_storage import run_runtime_storage_self_test  # noqa: E402


if __name__ == "__main__":
    run_ai_models_self_test()
    run_runtime_storage_self_test()
    print("AI model settings and runtime migration self-tests passed")
