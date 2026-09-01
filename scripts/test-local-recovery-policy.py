from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from failure_policy import run_failure_policy_self_test  # noqa: E402
from recovery_policy import run_recovery_self_test  # noqa: E402


def main() -> int:
    # Ubuntu CI intentionally does not import task_center.py because the runner's
    # minimal Python image has no Tkinter. The Windows source/executable self-test
    # imports the real desktop stack and runs run_task_center_self_test there.
    run_failure_policy_self_test()
    run_recovery_self_test()
    print("Local Engine smart recovery policy tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
