from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / "docs" / "managed-gallery-dl.md").read_text(encoding="utf-8")
assert "pypi.org/pypi/gallery-dl/json" in text
assert "SHA-256" in text
assert "optional managed tool" in text
