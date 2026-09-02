from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/test-local-pause-resume.py"


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    old = 'ROOT = Path(__file__).resolve().parents[1]\n\n\ndef load_module'
    new = (
        'ROOT = Path(__file__).resolve().parents[1]\n'
        'LOCAL_ENGINE = ROOT / "local-engine"\n'
        'sys.path.insert(0, str(LOCAL_ENGINE))\n\n\n'
        'def load_module'
    )
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"pause resume loader anchor: expected 1 match, found {count}")
    TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
