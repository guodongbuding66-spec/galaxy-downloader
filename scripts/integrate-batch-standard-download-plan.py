from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/components/downloader/BatchWorkbench.tsx"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "import {\n  createDefaultLocalEngineAdvancedOptions,\n  resolveLocalEngineAdvancedJobOptions,\n} from '@/lib/local-engine'\n",
        "import { createDefaultLocalEngineAdvancedOptions } from '@/lib/local-engine'\nimport {\n  buildLocalEngineBatchOptions,\n  createDefaultLocalEngineBatchPlanOptions,\n} from '@/lib/local-engine-batch-options'\n",
        "batch plan imports",
    )

    text = replace_once(
        text,
        "import { LocalEngineAdvancedControls } from './LocalEngineAdvancedControls'\nimport { BatchWorkbenchResultPanel } from './BatchWorkbenchResultPanel'",
        "import { BatchDownloadPlanControls } from './BatchDownloadPlanControls'\nimport { LocalEngineAdvancedControls } from './LocalEngineAdvancedControls'\nimport { BatchWorkbenchResultPanel } from './BatchWorkbenchResultPanel'",
        "batch plan component import",
    )

    text = replace_once(
        text,
        "  const [submissionResult, setSubmissionResult] = useState<LocalEngineBatchSubmissionResult | null>(null)\n  const [advancedOptions, setAdvancedOptions] = useState(() => createDefaultLocalEngineAdvancedOptions())",
        "  const [submissionResult, setSubmissionResult] = useState<LocalEngineBatchSubmissionResult | null>(null)\n  const [planOptions, setPlanOptions] = useState(() => createDefaultLocalEngineBatchPlanOptions())\n  const [advancedOptions, setAdvancedOptions] = useState(() => createDefaultLocalEngineAdvancedOptions())",
        "batch plan state",
    )

    text = replace_once(
        text,
        "        options: resolveLocalEngineAdvancedJobOptions(\n          advancedOptions,\n          Boolean(bridge?.aria2Ready),\n        ),",
        "        options: buildLocalEngineBatchOptions(\n          planOptions,\n          advancedOptions,\n          Boolean(bridge?.aria2Ready),\n        ),",
        "batch plan submission",
    )

    marker = """        <LocalEngineAdvancedControls
          value={advancedOptions}
          aria2Ready={Boolean(bridge?.aria2Ready)}
          disabled={submitting}
          onChange={(next) => {
            setAdvancedOptions(next)
            setSubmissionResult(null)
            setSubmissionError('')
          }}
        />
"""
    plan = """        <BatchDownloadPlanControls
          value={planOptions}
          disabled={submitting}
          onChange={(next) => {
            setPlanOptions(next)
            setSubmissionResult(null)
            setSubmissionError('')
          }}
        />

"""
    text = replace_once(text, marker, plan + marker, "batch plan controls mount")

    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
