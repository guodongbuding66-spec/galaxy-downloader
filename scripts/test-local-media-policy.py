from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-engine"))

import bilibili_policy  # noqa: E402
import external_ytdlp  # noqa: E402
import media_policy  # noqa: E402
from bilibili_danmaku_convert import BilibiliDanmakuConversionError  # noqa: E402


SAMPLE_DANMAKU_XML = (
    '<i><d p="1.25,1,25,16711680,1700000000,0,user,row">Hello &amp; world</d>'
    '<d p="2.5,5,30,255">Top</d></i>'
)

assert media_policy._parse_time("01:20") == 80
assert media_policy._parse_time("1:02:03") == 3723
assert media_policy._parse_time("bad") is None
assert media_policy._validated_languages("zh-Hans,en,en,../bad") == ("zh-Hans", "en")
assert media_policy._validated_sponsor_categories("sponsor,selfpromo,unknown") == ("sponsor", "selfpromo")
assert media_policy._validated_danmaku_formats("xml,ass,json,ass,srt") == ("xml", "ass", "json")
assert media_policy._validated_danmaku_formats("srt,unknown") == ("xml",)
assert media_policy._clean_preferences({})["includeDanmaku"] is False
assert media_policy._clean_preferences({})["danmakuFormats"] == ["xml"]
assert media_policy._clean_preferences({})["keepCoverSidecar"] is False
assert media_policy._clean_preferences({"includeDanmaku": True})["includeDanmaku"] is True
assert media_policy._clean_preferences({"danmakuFormats": ["ass", "json"]})["danmakuFormats"] == ["ass", "json"]
assert media_policy._clean_preferences({"keepCoverSidecar": True})["keepCoverSidecar"] is True

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
    preexisting = root / "existing.danmaku.xml"
    preexisting.write_text(SAMPLE_DANMAKU_XML, encoding="utf-8")
    produced = root / "fresh.danmaku.xml"
    original_run_once = bilibili_policy._run_once

    def fake_run_once(command, *, cancelled, timeout_seconds):
        assert not cancelled()
        assert timeout_seconds > 0
        produced.write_text(SAMPLE_DANMAKU_XML, encoding="utf-8")

    bilibili_policy._run_once = fake_run_once
    try:
        changed = bilibili_policy.download_danmaku_sidecar(
            root / "yt-dlp",
            "https://www.bilibili.com/video/BV1demo",
            output_template=str(root / "%(title)s [%(id)s].%(ext)s"),
            browser="none",
            playlist=False,
            collection_mode="single",
            selected_items=None,
            cancelled=lambda: False,
            on_status=lambda _message: None,
        )
    finally:
        bilibili_policy._run_once = original_run_once
    assert changed == (produced.resolve(),)
    assert preexisting.resolve() not in changed

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    xml = root / "video.danmaku.xml"
    xml.write_text(SAMPLE_DANMAKU_XML, encoding="utf-8")
    saved = media_policy._convert_danmaku_sidecars((xml,), ("xml", "ass", "json"))
    assert saved == ("xml", "ass", "json")
    assert xml.exists()
    assert (root / "video.danmaku.ass").exists()
    assert (root / "video.danmaku.json").exists()

    ass_only_xml = root / "ass-only.danmaku.xml"
    ass_only_xml.write_text(SAMPLE_DANMAKU_XML, encoding="utf-8")
    saved = media_policy._convert_danmaku_sidecars((ass_only_xml,), ("ass",))
    assert saved == ("ass",)
    assert not ass_only_xml.exists()
    assert (root / "ass-only.danmaku.ass").exists()
    assert not (root / "ass-only.danmaku.json").exists()

    failed_xml = root / "failed.danmaku.xml"
    failed_xml.write_text(SAMPLE_DANMAKU_XML, encoding="utf-8")
    original_convert = media_policy.convert_danmaku_file

    def fail_convert(*_args, **_kwargs):
        raise BilibiliDanmakuConversionError("synthetic conversion failure")

    media_policy.convert_danmaku_file = fail_convert
    try:
        try:
            media_policy._convert_danmaku_sidecars((failed_xml,), ("ass", "json"))
        except BilibiliDanmakuConversionError:
            pass
        else:
            raise AssertionError("synthetic danmaku conversion failure was swallowed")
    finally:
        media_policy.convert_danmaku_file = original_convert
    assert failed_xml.exists()

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
        keep_cover_sidecar=False,
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
    assert "--write-thumbnail" not in result
    assert result[-2:] == ["--", "https://example.com/video"]

    common_external = dict(
        executable=executable,
        source_url="https://example.com/video",
        format_selector="best",
        output_template=str(root / "%(title)s.%(ext)s"),
        ffmpeg_location=None,
        browser="none",
        playlist=False,
        subtitle_language=None,
    )

    no_cover = external_ytdlp.build_external_command(
        **common_external,
        include_subtitle=False,
        include_cover=False,
    )
    assert "--no-write-thumbnail" in no_cover
    assert "--no-embed-thumbnail" in no_cover
    unchanged = media_policy._apply_cover_sidecar_command(
        SimpleNamespace(keep_cover_sidecar=False),
        list(no_cover),
    )
    assert unchanged == no_cover

    sidecar_only = media_policy._apply_cover_sidecar_command(
        SimpleNamespace(keep_cover_sidecar=True),
        list(no_cover),
    )
    assert "--write-thumbnail" in sidecar_only
    assert "--no-write-thumbnail" not in sidecar_only
    assert "--no-embed-thumbnail" in sidecar_only
    assert sidecar_only.index("--write-thumbnail") < sidecar_only.index("--")

    embed_only = external_ytdlp.build_external_command(
        **common_external,
        include_subtitle=False,
        include_cover=True,
    )
    assert "--embed-thumbnail" in embed_only
    assert "--write-thumbnail" not in embed_only
    assert "--no-write-thumbnail" not in embed_only

    embed_and_sidecar = media_policy._apply_cover_sidecar_command(
        SimpleNamespace(keep_cover_sidecar=True),
        list(embed_only),
    )
    assert "--embed-thumbnail" in embed_and_sidecar
    assert "--write-thumbnail" in embed_and_sidecar
    assert "--no-write-thumbnail" not in embed_and_sidecar

    embedded_sidecar_only = media_policy._apply_embedded_cover_sidecar(
        SimpleNamespace(keep_cover_sidecar=True),
        {"writethumbnail": False, "postprocessors": []},
    )
    assert embedded_sidecar_only["writethumbnail"] is True
    assert embedded_sidecar_only["postprocessors"] == []

    embedded_embed_and_sidecar = media_policy._apply_embedded_cover_sidecar(
        SimpleNamespace(keep_cover_sidecar=True),
        {
            "writethumbnail": True,
            "postprocessors": [
                {"key": "FFmpegMetadata"},
                {"key": "EmbedThumbnail", "already_have_thumbnail": False},
            ],
        },
    )
    assert embedded_embed_and_sidecar["writethumbnail"] is True
    embed_pp = next(
        item
        for item in embedded_embed_and_sidecar["postprocessors"]
        if item.get("key") == "EmbedThumbnail"
    )
    assert embed_pp["already_have_thumbnail"] is True

print("local media policy tests OK")