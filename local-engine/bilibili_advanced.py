from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

from media_format_catalog import build_media_format_catalog, public_media_format_catalog
from url_policy import validated_public_http_url

BVID_RE = re.compile(r"\b(BV[0-9A-Za-z]{10})\b", re.I)
MAX_API_BYTES = 8 * 1024 * 1024
MAX_DANMAKU_BYTES = 64 * 1024 * 1024
MAX_DANMAKU_ITEMS = 100_000


class BilibiliAdvancedError(RuntimeError):
    pass


@dataclass(frozen=True)
class BilibiliSidecarResult:
    root: Path
    xml: Path | None
    json: Path | None
    ass: Path | None
    nfo: Path | None


def _read_limited(response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        block = response.read(min(64 * 1024, limit - total + 1))
        if not block:
            break
        total += len(block)
        if total > limit:
            raise BilibiliAdvancedError("Bilibili 响应超过安全上限")
        chunks.append(block)
    return b"".join(chunks)


def _get_json(url: str) -> dict[str, Any]:
    validated = validated_public_http_url(url)
    request = urllib.request.Request(
        validated,
        headers={"User-Agent": "Mozilla/5.0 GalaxyLocalEngine/1.0", "Referer": "https://www.bilibili.com/"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed Bilibili public API URL is validated
            final = validated_public_http_url(response.geturl())
            if "bilibili.com" not in (urlparse(final).hostname or ""):
                raise BilibiliAdvancedError("Bilibili API 重定向到非预期主机")
            body = _read_limited(response, MAX_API_BYTES)
    except (OSError, urllib.error.URLError) as exc:
        raise BilibiliAdvancedError(str(exc)) from exc
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BilibiliAdvancedError("Bilibili API 返回无效 JSON") from exc
    if not isinstance(value, dict):
        raise BilibiliAdvancedError("Bilibili API 响应格式无效")
    return value


def _extract_bvid(source_url: object) -> str:
    url = validated_public_http_url(str(source_url or ""))
    match = BVID_RE.search(url)
    if not match:
        raise BilibiliAdvancedError("当前链接没有可解析的 BV 号；番剧/课程仍可使用 Galaxy 通用 Bilibili 下载")
    return match.group(1)


def bilibili_view_metadata(source_url: object) -> dict[str, Any]:
    bvid = _extract_bvid(source_url)
    payload = _get_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not data:
        raise BilibiliAdvancedError(str(payload.get("message") or "Bilibili 视频元数据不可用"))
    pages = data.get("pages") if isinstance(data.get("pages"), list) else []
    return {
        "bvid": bvid,
        "aid": int(data.get("aid") or 0),
        "title": str(data.get("title") or "")[:500],
        "description": str(data.get("desc") or "")[:10_000],
        "owner": str((data.get("owner") or {}).get("name") or "")[:200]
        if isinstance(data.get("owner"), dict)
        else "",
        "pic": str(data.get("pic") or "")[:1000],
        "pubdate": int(data.get("pubdate") or 0),
        "pages": [
            {
                "page": int(item.get("page") or index + 1),
                "cid": int(item.get("cid") or 0),
                "part": str(item.get("part") or "")[:300],
            }
            for index, item in enumerate(pages[:500])
            if isinstance(item, dict)
        ],
    }


def inspect_bilibili_formats(engine_module, source_url: object, *, browser: str = "none") -> dict[str, Any]:
    url = validated_public_http_url(str(source_url or ""))
    executable = engine_module.external_ytdlp_path(engine_module.app_dir())
    if executable is None:
        raise BilibiliAdvancedError("yt-dlp 不可用")
    command = [
        str(executable),
        "--ignore-config",
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
    ]
    selected_browser = str(browser or "none").strip().lower()
    if selected_browser != "none":
        command.extend(["--cookies-from-browser", selected_browser])
    command.extend(["--", url])
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BilibiliAdvancedError(str(exc)) from exc
    if completed.returncode != 0:
        raise BilibiliAdvancedError((completed.stderr or completed.stdout or "yt-dlp failed")[-1600:])
    try:
        metadata = json.loads(completed.stdout)
    except ValueError as exc:
        raise BilibiliAdvancedError("yt-dlp 返回无效元数据") from exc
    if not isinstance(metadata, dict):
        raise BilibiliAdvancedError("yt-dlp 返回无效元数据")
    raw_formats = metadata.get("formats") if isinstance(metadata.get("formats"), list) else []
    catalog = public_media_format_catalog(build_media_format_catalog(raw_formats))
    videos = catalog["videoOptions"] if isinstance(catalog.get("videoOptions"), list) else []
    audios = catalog["audioOptions"] if isinstance(catalog.get("audioOptions"), list) else []
    capabilities = {
        "4k": any(int(item.get("height") or 0) >= 2160 for item in videos if isinstance(item, dict)),
        "hdr": any(
            "hdr" in str(item.get("dynamicRange") or "").lower()
            or "dolby" in str(item.get("dynamicRange") or "").lower()
            for item in videos
            if isinstance(item, dict)
        ),
        "dolbyVision": any(
            "dolby" in str(item.get("dynamicRange") or "").lower()
            for item in videos
            if isinstance(item, dict)
        ),
        "hiResAudio": any(
            float(item.get("audioBitrate") or 0) >= 500
            for item in audios
            if isinstance(item, dict)
        ),
    }
    return {"catalog": catalog, "capabilities": capabilities, "browser": selected_browser}


def _danmaku_xml(cid: int) -> bytes:
    if cid <= 0:
        raise BilibiliAdvancedError("CID 无效")
    url = validated_public_http_url(f"https://comment.bilibili.com/{cid}.xml")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 GalaxyLocalEngine/1.0", "Referer": "https://www.bilibili.com/"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed validated Bilibili host
            final = validated_public_http_url(response.geturl())
            if not (urlparse(final).hostname or "").endswith("bilibili.com"):
                raise BilibiliAdvancedError("弹幕接口重定向到非预期主机")
            return _read_limited(response, MAX_DANMAKU_BYTES)
    except (OSError, urllib.error.URLError) as exc:
        raise BilibiliAdvancedError(str(exc)) from exc


def parse_danmaku_xml(data: bytes) -> list[dict[str, Any]]:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise BilibiliAdvancedError("弹幕 XML 无效") from exc
    result: list[dict[str, Any]] = []
    for node in root.findall("d"):
        parts = str(node.attrib.get("p") or "").split(",")
        if len(parts) < 4:
            continue
        try:
            start = max(0.0, float(parts[0]))
            mode = int(parts[1])
            size = max(12, min(int(parts[2]), 72))
            color = max(0, min(int(parts[3]), 0xFFFFFF))
        except (TypeError, ValueError):
            continue
        text = str(node.text or "").replace("\r", " ").replace("\n", " ").strip()[:500]
        if text:
            result.append(
                {"time": round(start, 3), "mode": mode, "size": size, "color": color, "text": text}
            )
        if len(result) >= MAX_DANMAKU_ITEMS:
            break
    return result


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100)))
    h, rem = divmod(centiseconds, 360_000)
    m, rem = divmod(rem, 6_000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def danmaku_to_ass(rows: list[dict[str, Any]], *, width: int = 1920, height: int = 1080) -> str:
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        "Style: Danmaku,Arial,36,&H00FFFFFF,&H00FFFFFF,&H80000000,&H40000000,0,0,0,0,100,100,0,0,1,2,0,7,20,20,20,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    ) % (width, height)
    events: list[str] = []
    lane = 0
    for item in rows[:MAX_DANMAKU_ITEMS]:
        start = float(item["time"])
        end = start + 8.0
        text = str(item["text"]).replace("{", "(").replace("}", ")").replace(",", "，")
        y = 30 + (lane % 18) * 55
        lane += 1
        if int(item.get("mode") or 1) in {4, 5}:
            effect = f"{{\\an8\\pos({width // 2},{y})}}"
        else:
            effect = f"{{\\move({width + 40},{y},-800,{y})}}"
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Danmaku,,0,0,0,,{effect}{text}"
        )
    return header + "\n".join(events) + "\n"


def export_bilibili_sidecars(
    engine_module,
    source_url: object,
    *,
    page: int = 1,
    xml: bool = True,
    json_output: bool = True,
    ass: bool = True,
    nfo: bool = True,
) -> BilibiliSidecarResult:
    metadata = bilibili_view_metadata(source_url)
    pages = metadata["pages"]
    selected = next((item for item in pages if int(item["page"]) == int(page)), None)
    if selected is None:
        raise BilibiliAdvancedError("分 P 不存在")
    root = (
        Path(engine_module.default_download_dir())
        / "bilibili-sidecars"
        / metadata["bvid"]
        / f"P{int(page):03d}"
    )
    root.mkdir(parents=True, exist_ok=True)
    xml_path = json_path = ass_path = nfo_path = None
    data = _danmaku_xml(int(selected["cid"])) if (xml or json_output or ass) else b""
    rows = parse_danmaku_xml(data) if data else []
    if xml:
        xml_path = root / "danmaku.xml"
        xml_path.write_bytes(data)
    if json_output:
        json_path = root / "danmaku.json"
        json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if ass:
        ass_path = root / "danmaku.ass"
        ass_path.write_text(danmaku_to_ass(rows), encoding="utf-8")
    if nfo:
        nfo_path = root / "video.nfo"
        nfo_path.write_text(
            "<?xml version='1.0' encoding='UTF-8'?>\n<episodedetails>\n"
            f"<title>{_xml_escape(metadata['title'])}</title>\n"
            f"<showtitle>{_xml_escape(metadata['owner'])}</showtitle>\n"
            f"<plot>{_xml_escape(metadata['description'])}</plot>\n"
            f"<episode>{int(page)}</episode>\n"
            f"<uniqueid type='bilibili' default='true'>{_xml_escape(metadata['bvid'])}</uniqueid>\n"
            "</episodedetails>\n",
            encoding="utf-8",
        )
    return BilibiliSidecarResult(root, xml_path, json_path, ass_path, nfo_path)


def _xml_escape(value: object) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")[:20_000]
    )


def run_bilibili_advanced_self_test() -> None:
    sample = b'<?xml version="1.0"?><i><d p="1.5,1,25,16777215,0,0,0,0">Hello</d></i>'
    rows = parse_danmaku_xml(sample)
    assert rows[0]["time"] == 1.5 and rows[0]["text"] == "Hello"
    rendered = danmaku_to_ass(rows)
    assert "Dialogue:" in rendered and "Hello" in rendered
    assert _xml_escape("<a&b>") == "&lt;a&amp;b&gt;"
