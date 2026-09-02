from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    local_engine = ROOT / "src/lib/local-engine.ts"
    replace_once(
        local_engine,
        "  | 'music_offtopic'\n  | 'filler'\n\nexport interface LocalDesktopVideoSelection {",
        "  | 'music_offtopic'\n  | 'filler'\n\nexport interface LocalEngineAdvancedOptions {\n  segmentStart: string\n  segmentEnd: string\n  splitChapters: boolean\n  subtitleMode: LocalEngineSubtitleMode\n  subtitleLanguages: string[]\n  audioLanguages: string[]\n  sponsorBlockCategories: SponsorBlockCategory[]\n  useAria2c: boolean\n}\n\nexport function createDefaultLocalEngineAdvancedOptions(): LocalEngineAdvancedOptions {\n  return {\n    segmentStart: '',\n    segmentEnd: '',\n    splitChapters: false,\n    subtitleMode: 'both',\n    subtitleLanguages: [],\n    audioLanguages: [],\n    sponsorBlockCategories: [],\n    useAria2c: false,\n  }\n}\n\nexport function resolveLocalEngineAdvancedJobOptions(\n  value: LocalEngineAdvancedOptions,\n  aria2Ready: boolean,\n): LocalEngineAdvancedOptions {\n  return {\n    ...value,\n    subtitleLanguages: [...value.subtitleLanguages],\n    audioLanguages: [...value.audioLanguages],\n    sponsorBlockCategories: [...value.sponsorBlockCategories],\n    useAria2c: Boolean(aria2Ready && value.useAria2c),\n  }\n}\n\nexport interface LocalDesktopVideoSelection {",
        "shared advanced options model",
    )

    controls = ROOT / "src/components/downloader/LocalEngineAdvancedControls.tsx"
    replace_once(
        controls,
        "import type {\n  LocalEngineSubtitleMode,\n  SponsorBlockCategory,\n} from '@/lib/local-engine';",
        "import {\n  createDefaultLocalEngineAdvancedOptions,\n  type LocalEngineAdvancedOptions,\n  type LocalEngineSubtitleMode,\n  type SponsorBlockCategory,\n} from '@/lib/local-engine';\n\nexport type { LocalEngineAdvancedOptions } from '@/lib/local-engine';",
        "advanced controls shared import",
    )
    replace_once(
        controls,
        "export type LocalEngineAdvancedOptions = {\n  segmentStart: string;\n  segmentEnd: string;\n  splitChapters: boolean;\n  subtitleMode: LocalEngineSubtitleMode;\n  subtitleLanguages: string[];\n  audioLanguages: string[];\n  sponsorBlockCategories: SponsorBlockCategory[];\n  useAria2c: boolean;\n};\n\n",
        "",
        "remove component-owned advanced type",
    )
    replace_once(
        controls,
        "function defaultOptions(): LocalEngineAdvancedOptions {\n  return {\n    segmentStart: '',\n    segmentEnd: '',\n    splitChapters: false,\n    subtitleMode: 'both',\n    subtitleLanguages: [],\n    audioLanguages: [],\n    sponsorBlockCategories: [],\n    useAria2c: false,\n  };\n}\n\n",
        "",
        "remove component-owned defaults",
    )
    text = controls.read_text(encoding="utf-8")
    count = text.count("defaultOptions()")
    if count != 5:
        raise SystemExit(f"advanced default callsites: expected 5, found {count}")
    controls.write_text(text.replace("defaultOptions()", "createDefaultLocalEngineAdvancedOptions()"), encoding="utf-8")

    bridge = ROOT / "src/lib/local-engine-bridge.ts"
    replace_once(
        bridge,
        "  type LocalEngineBrowser,\n  type LocalEngineCollectionMode,\n} from '@/lib/local-engine'",
        "  type LocalEngineAdvancedOptions,\n  type LocalEngineBrowser,\n  type LocalEngineCollectionMode,\n} from '@/lib/local-engine'",
        "bridge advanced type import",
    )
    replace_once(
        bridge,
        "  ffmpegReady: boolean\n  ytDlpReady: boolean\n  queueLength: number",
        "  ffmpegReady: boolean\n  ytDlpReady: boolean\n  advancedMedia?: boolean\n  aria2Ready?: boolean\n  queueLength: number",
        "bridge advanced capabilities",
    )
    replace_once(
        bridge,
        "export interface LocalEngineBridgeJob {",
        "export interface LocalEngineBridgeJob extends Partial<LocalEngineAdvancedOptions> {",
        "bridge job advanced inheritance",
    )
    replace_once(
        bridge,
        "    ffmpegReady: Boolean(payload.ffmpegReady),\n    ytDlpReady: Boolean(payload.ytDlpReady),\n    queueLength,",
        "    ffmpegReady: Boolean(payload.ffmpegReady),\n    ytDlpReady: Boolean(payload.ytDlpReady),\n    advancedMedia: Boolean(payload.advancedMedia),\n    aria2Ready: Boolean(payload.aria2Ready),\n    queueLength,",
        "bridge advanced capability normalization",
    )

    batch = ROOT / "src/components/downloader/BatchWorkbench.tsx"
    replace_once(
        batch,
        "import { toast } from '@/lib/deferred-toast'\nimport {",
        "import { toast } from '@/lib/deferred-toast'\nimport {\n  createDefaultLocalEngineAdvancedOptions,\n  resolveLocalEngineAdvancedJobOptions,\n} from '@/lib/local-engine'\nimport {",
        "batch shared option imports",
    )
    replace_once(
        batch,
        "import { BatchWorkbenchResultPanel } from './BatchWorkbenchResultPanel'\n\nimport {",
        "import { LocalEngineAdvancedControls } from './LocalEngineAdvancedControls'\nimport { BatchWorkbenchResultPanel } from './BatchWorkbenchResultPanel'\n\nimport {",
        "batch advanced controls import",
    )
    replace_once(
        batch,
        "  const [submissionError, setSubmissionError] = useState('')\n  const [submissionResult, setSubmissionResult] = useState<LocalEngineBatchSubmissionResult | null>(null)\n\n  const preview",
        "  const [submissionError, setSubmissionError] = useState('')\n  const [submissionResult, setSubmissionResult] = useState<LocalEngineBatchSubmissionResult | null>(null)\n  const [advancedOptions, setAdvancedOptions] = useState(() => createDefaultLocalEngineAdvancedOptions())\n\n  const preview",
        "batch advanced state",
    )
    replace_once(
        batch,
        "      const result = await submitLocalEngineBatchInput({ input, format })",
        "      const result = await submitLocalEngineBatchInput({\n        input,\n        format,\n        options: resolveLocalEngineAdvancedJobOptions(\n          advancedOptions,\n          Boolean(bridge?.aria2Ready),\n        ),\n      })",
        "batch advanced submission",
    )
    replace_once(
        batch,
        "        <div className=\"mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between\">",
        "        <LocalEngineAdvancedControls\n          value={advancedOptions}\n          aria2Ready={Boolean(bridge?.aria2Ready)}\n          disabled={submitting}\n          onChange={(next) => {\n            setAdvancedOptions(next)\n            setSubmissionResult(null)\n            setSubmissionError('')\n          }}\n        />\n\n        <div className=\"mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between\">",
        "batch advanced controls mount",
    )


if __name__ == "__main__":
    main()
