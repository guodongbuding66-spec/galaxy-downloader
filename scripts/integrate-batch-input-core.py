from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, got {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


entrypoint = ROOT / "local-engine" / "entrypoint.py"
replace_once(
    entrypoint,
    'from bridge_submission_policy import StructuredLocalBridge\n',
    'from batch_input import run_batch_input_self_test\nfrom bridge_submission_policy import StructuredLocalBridge\n',
)
replace_once(
    entrypoint,
    '    run_job_scheduler_self_test()\n',
    '    run_batch_input_self_test()\n    run_job_scheduler_self_test()\n',
)

policy_test = ROOT / "scripts" / "test-local-engine-policy.py"
replace_once(
    policy_test,
    '''bridge = load_module(
    "galaxy_bridge_test",
    ROOT / "local-engine" / "bridge.py",
)


class ExternalDownloadPolicyTests(unittest.TestCase):
''',
    '''bridge = load_module(
    "galaxy_bridge_test",
    ROOT / "local-engine" / "bridge.py",
)
batch_input = load_module(
    "galaxy_batch_input_test",
    ROOT / "local-engine" / "batch_input.py",
)


class BatchInputCorePolicyTests(unittest.TestCase):
    def test_batch_input_core_contract(self):
        batch_input.run_batch_input_self_test()


class ExternalDownloadPolicyTests(unittest.TestCase):
''',
)

print("batch input core integration applied")
