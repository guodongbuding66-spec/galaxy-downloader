from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = ROOT / "local-engine" / "VERSION"
NOTES_PATH = ROOT / "local-engine" / "RELEASE_NOTES.md"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
SECTION_RE = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s*$", re.MULTILINE)


def main() -> None:
    version = VERSION_PATH.read_text(encoding="utf-8").strip()
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(f"invalid Local Engine VERSION: {version!r}")

    notes = NOTES_PATH.read_text(encoding="utf-8")
    expected_title = f"# Galaxy Local Engine {version}"
    first_nonempty = next((line.strip() for line in notes.splitlines() if line.strip()), "")
    if first_nonempty != expected_title:
        raise SystemExit(
            f"release notes title must match VERSION; expected {expected_title!r}, got {first_nonempty!r}"
        )

    sections = SECTION_RE.findall(notes)
    if not sections:
        raise SystemExit("release notes contain no semantic-version release section")
    if sections[0] != version:
        raise SystemExit(
            f"first release section must be current VERSION {version}; got {sections[0]}"
        )
    if sections.count(version) != 1:
        raise SystemExit(f"release notes must contain exactly one ## {version} section")

    required_install_tokens = (
        "GalaxyLocalEngine-Windows.zip",
        "SHA256SUMS.txt",
        "install.cmd",
    )
    for token in required_install_tokens:
        if token not in notes:
            raise SystemExit(f"release notes are missing required install token: {token}")

    current_section_start = notes.index(f"## {version}")
    next_section = SECTION_RE.search(notes, current_section_start + len(f"## {version}"))
    current_section = notes[current_section_start: next_section.start() if next_section else len(notes)]
    if len(current_section.splitlines()) < 4:
        raise SystemExit(f"release notes section for {version} is unexpectedly empty")

    print(f"Local Engine release notes match VERSION {version}")


if __name__ == "__main__":
    main()
