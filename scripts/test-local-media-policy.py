from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-engine"))

import bilibili_policy  # noqa: E402
import media_policy  # noqa: E402


assert media_policy._parse_time("01:20") == 80
assert media_policy._parse_time("1:02:03") == 3723
assert media_policy._parse_time("bad") is None
assert media_policy._validated_languages("zh-Hans,en,en,../bad") == ("zh-Hans", "en")
assert media_policy._validated_sponsor_categories("sponsor,selfpromo,unknown") == ("sponsor", "selfpromo")
assert media_policy._clean_preferences({})["includeDanmaku"] is False
assert media_policy._clean_preferences({"includeDanmaku": True})["includeDanmaku"] is True

bilibili_policy.run_bilibili_policy_self_test()
assert bilibili_policy.is_bilibili_url("https://www.bilibili.com/video/BV1demo")
assert bilibili_policy.is_bilibili_url("https://m.bilibili.com/video/BV1demo")
assert bilibili_policy.is_bilibili_url("https://b23.tv/demo")
assert not bilibili_policy.is_bilibili_url("https://bilibili.com.evil.example/video/BV1demo")

bili_job = SimpleNamespace(
    source_url="https://www.bilibili.com/video/BV1demo",
    include_danmaku=True,
    include_subtitle=False,
)
assert media_policy._bilibili_danmaku_requested(bili_job)
assert media_policy._embedded_danmaku_only(bili_job)
assert not media_policy._bilibili_danmaku_requested(
    SimpleNamespace(source_url="https://example.com/video", include_danmaku=True)
)
assert not media_policy._embedded_danmaku_only(
    SimpleNamespace(
        source_url="https://www.bilibili.com/video/BV1demo",
        include_danmaku=True,
        include_subtitle=True,
    )
)

single_command = bilibili_policy.build_danmaku_command(
    Path("yt-dlp"),
    "https://www.bilibili.com/video/BV1demo",
    output_template="%(title)s [%(id)s].%(ext)s",
    playlist=False,
)
assert "--skip-download" in single_command
assert single_command[single_command.index("--sub-langs") + 1] == "danmaku"
assert single_command[single_command.index("--sub-format") + 1] == "xml"
assert "--convert-subs" not in single_command
assert "--embed-subs" not in single_command
assert "--no-write-comments" in single_command
assert single_command[-2:] == ["--", "https://www.bilibili.com/video/BV1demo"]

selected_command = bilibili_policy.build_danmaku_command(
    Path("yt-dlp"),
    "https://www.bilibili.com/video/BV1demo",
    output_template="%(title)s [%(id)s].%(ext)s",
    playlist=True,
    collection_mode="selected",
    selected_items=(3, 1, 3, 0, -2),
    browser="edge",
)
assert "--yes-playlist" in selected_command
assert selected_command[selected_command.index("--playlist-items") + 1] == "3,1"
assert selected_command[selected_command.index("--cookies-from-browser") + 1] == "edge"

try:
    bilibili_policy.build_danmaku_command(
        Path("yt-dlp"),
        "https://bilibili.com.evil.example/video/BV1demo",
        output_template="%(title)s.%(ext)s",
        playlist=False,
    )
except bilibili_policy.BilibiliDanmakuError:
    pass
else:
    raise AssertionError("spoofed Bilibili host was accepted for danmaku sidecar")

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    executable = root / "yt-dlp.exe"
    executable.write_bytes(b"")
    (root / "aria2c.exe").write_bytes(b"")
    job = SimpleNamespace(
        source_url="https://example.com/video",
        segment_start=80.0,
        segment_end=225.0,
        split_chapters=True,
        include_subtitle=True,
        include_danmaku=False,
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
