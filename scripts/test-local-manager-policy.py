from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from job_history import run_history_self_test  # noqa: E402
from queue_controls import run_queue_controls_self_test  # noqa: E402
from workspace_policy import run_workspace_self_test  # noqa: E402


def main() -> int:
    run_workspace_self_test()
    run_history_self_test()
    run_queue_controls_self_test()
    print("Local Engine manager policy tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
