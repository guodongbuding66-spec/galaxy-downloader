from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/app/[locale]/unified-downloader.tsx"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "import { LocalEngineSetupHint } from '@/components/downloader/LocalEngineSetupHint';\n",
        "import { LocalEngineSetupHint } from '@/components/downloader/LocalEngineSetupHint';\n"
        "import { BatchWorkbench } from '@/components/downloader/BatchWorkbench';\n",
        "BatchWorkbench import",
    )

    text = replace_once(
        text,
        "                        </form>\n                    </section>\n\n                    <UnifiedDownloaderLowerSections",
        "                        </form>\n\n"
        "                        <BatchWorkbench />\n"
        "                    </section>\n\n"
        "                    <UnifiedDownloaderLowerSections",
        "BatchWorkbench render",
    )

    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
