from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from failure_policy import run_failure_policy_self_test  # noqa: E402
from recovery_policy import run_recovery_self_test  # noqa: E402
from task_center import run_task_center_self_test  # noqa: E402


def main() -> int:
    run_failure_policy_self_test()
    run_recovery_self_test()
    run_task_center_self_test()
    print("Local Engine smart recovery/task center policy tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
