from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-engine"))

import media_policy  # noqa: E402


assert media_policy._parse_time("01:20") == 80
assert media_policy._parse_time("1:02:03") == 3723
assert media_policy._parse_time("bad") is None
assert media_policy._validated_languages("zh-Hans,en,en,../bad") == ("zh-Hans", "en")
assert media_policy._validated_sponsor_categories("sponsor,selfpromo,unknown") == ("sponsor", "selfpromo")

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    executable = root / "yt-dlp.exe"
    executable.write_bytes(b"")
    (root / "aria2c.exe").write_bytes(b"")
    job = SimpleNamespace(
        segment_start=80.0,
        segment_end=225.0,
        split_chapters=True,
        include_subtitle=True,
        subtitle_mode="manual",
        subtitle_languages=("zh-Hans", "en"),
        audio_languages=("zh", "en"),
        sponsorblock_categories=("sponsor", "selfpromo"),
        use_aria2c=True,
    )
    command = [
        str(executable),
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "zh,en",
        "--",
        "https://example.com/video",
    ]
    result = media_policy._apply_external_command(job, command, executable)
    assert "--download-sections" in result
    assert "*01:20-03:45" in result
    assert "--split-chapters" in result
    assert "--write-subs" in result
    assert "--write-auto-subs" not in result
    assert result[result.index("--sub-langs") + 1] == "zh-Hans,en"
    assert "--audio-multistreams" in result
    assert "--sponsorblock-remove" in result
    assert result[result.index("--sponsorblock-remove") + 1] == "sponsor,selfpromo"
    assert "--downloader" in result
    assert Path(result[result.index("--downloader") + 1]).name.lower() == "aria2c.exe"
    assert result[-2:] == ["--", "https://example.com/video"]

print("local media policy tests OK")
