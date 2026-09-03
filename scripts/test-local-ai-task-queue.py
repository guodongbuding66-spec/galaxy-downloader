from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from ai_task_queue import run_ai_task_queue_self_test  # noqa: E402


if __name__ == "__main__":
    run_ai_task_queue_self_test()
    print("AI task queue self-test passed")
