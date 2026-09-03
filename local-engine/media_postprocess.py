from __future__ import annotations

import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ffmpeg_manager import bundled_ffmpeg_directory, existing_managed_ffmpeg
from media_library import resolve_media_item_path

CONTAINERS = {"original", "mp4", "mkv", "webm"}
TEMPLATE_TOKEN_RE = re.compile(r"\{(title|channel|artist|album|upload_date|playlist|playlist_index|id|ext)\}")
INVALID_FILENAME_RE = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")


class MediaPostprocessError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaPostprocessResult:
    path: Path
    operation: str


def _ffmpeg(engine_module) -> Path:
    directory = existing_managed_ffmpeg(engine_module) or bundled_ffmpeg_directory(engine_module)
    if directory is None:
        raise MediaPostprocessError("FFmpeg 不可用")
    executable = Path(directory) / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not executable.is_file():
        raise MediaPostprocessError("FFmpeg 不可用")
    return executable


def _safe_metadata(value: object, limit: int = 1000) -> str:
    return str(value or "").replace("\x00", " ").strip()[:limit]


def render_filename_template(template: object, metadata: Mapping[str, object], *, extension: str) -> str:
    raw = str(template or "{title}.{ext}").strip()[:500] or "{title}.{ext}"
    ext = extension.lower().lstrip(".")[:12]

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "ext":
            return ext
        value = " ".join(str(metadata.get(key) or "").split()).strip()
        return value[:180]

    rendered = TEMPLATE_TOKEN_RE.sub(replace, raw)
    rendered = re.sub(r"\{[^{}]{1,40}\}", "", rendered)
    rendered = INVALID_FILENAME_RE.sub("_", rendered).strip(" .")
    rendered = re.sub(r"\s+", " ", rendered)[:220]
    if not Path(rendered).suffix and ext:
        rendered += f".{ext}"
    return rendered or f"media.{ext or 'bin'}"


def _destination(engine_module, category: str, filename: str) -> Path:
    root = Path(engine_module.default_download_dir()).resolve(strict=False) / "processed" / category
    root.mkdir(parents=True, exist_ok=True)
    target = root / Path(filename).name
    if not target.exists():
        return target
    return root / f"{target.stem}-{uuid.uuid4().hex[:8]}{target.suffix}"


def _run(command: list[str], *, timeout_seconds: int = 7200) -> None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(30, min(int(timeout_seconds), 14_400)),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaPostprocessError("FFmpeg 处理超时") from exc
    except OSError as exc:
        raise MediaPostprocessError(str(exc)) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise MediaPostprocessError(detail[-2000:] or f"FFmpeg exited with {completed.returncode}")


def remux_media(
    engine_module,
    media_id: object,
    *,
    container: str,
    metadata: Mapping[str, object] | None = None,
    filename_template: object = "{title}.{ext}",
) -> MediaPostprocessResult:
    selected = str(container or "original").strip().lower()
    if selected not in CONTAINERS:
        raise MediaPostprocessError("输出容器无效")
    source = resolve_media_item_path(engine_module, media_id)
    if source is None:
        raise MediaPostprocessError("媒体文件不可用")
    if selected == "original":
        return MediaPostprocessResult(source, "original")
    values = dict(metadata or {})
    values.setdefault("title", source.stem)
    values.setdefault("id", str(media_id or ""))
    filename = render_filename_template(filename_template, values, extension=selected)
    destination = _destination(engine_module, "remux", filename)
    command = [str(_ffmpeg(engine_module)), "-nostdin", "-y", "-i", str(source), "-map", "0", "-c", "copy"]
    for key in ("title", "artist", "album", "date", "comment"):
        if key in values and _safe_metadata(values[key]):
            command.extend(["-metadata", f"{key}={_safe_metadata(values[key])}"])
    command.append(str(destination))
    _run(command)
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise MediaPostprocessError("FFmpeg 未生成输出文件")
    return MediaPostprocessResult(destination, "remux")


def _safe_subtitle(engine_module, value: object) -> Path:
    try:
        path = Path(str(value or "")).expanduser().resolve(strict=True)
        data_accessor = getattr(engine_module, "data_dir", None)
        data_root = Path(data_accessor()).resolve(strict=False) if callable(data_accessor) else Path(engine_module.app_dir()).resolve(strict=False)
        downloads = Path(engine_module.default_download_dir()).resolve(strict=False)
        if not any(_inside(path, root) for root in (data_root, downloads)):
            raise MediaPostprocessError("字幕必须位于 Galaxy 管理目录")
    except (OSError, RuntimeError, ValueError) as exc:
        raise MediaPostprocessError("字幕文件无效") from exc
    if path.suffix.lower() not in {".srt", ".ass", ".ssa", ".vtt"} or path.is_symlink():
        raise MediaPostprocessError("字幕格式无效")
    return path


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def embed_subtitle(engine_module, media_id: object, subtitle_file: object, *, container: str = "mkv") -> MediaPostprocessResult:
    selected = str(container or "mkv").lower()
    if selected not in {"mkv", "mp4"}:
        raise MediaPostprocessError("软字幕仅支持 MKV/MP4 输出")
    source = resolve_media_item_path(engine_module, media_id)
    if source is None:
        raise MediaPostprocessError("媒体文件不可用")
    subtitle = _safe_subtitle(engine_module, subtitle_file)
    destination = _destination(engine_module, "subtitles", f"{source.stem}-subtitled.{selected}")
    subtitle_codec = "mov_text" if selected == "mp4" else "srt"
    _run([
        str(_ffmpeg(engine_module)), "-nostdin", "-y", "-i", str(source), "-i", str(subtitle),
        "-map", "0", "-map", "1:0", "-c", "copy", "-c:s", subtitle_codec,
        "-metadata:s:s:0", "language=und", str(destination),
    ])
    return MediaPostprocessResult(destination, "embed-subtitle")


def _filter_path(path: Path) -> str:
    # FFmpeg filtergraph escaping is separate from shell escaping. The command
    # is passed as argv (never through a shell), and these escapes protect the
    # subtitles filter's own colon/backslash/quote grammar.
    value = str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("[", "\\[").replace("]", "\\]")
    return value


def burn_subtitle(engine_module, media_id: object, subtitle_file: object) -> MediaPostprocessResult:
    source = resolve_media_item_path(engine_module, media_id)
    if source is None:
        raise MediaPostprocessError("媒体文件不可用")
    subtitle = _safe_subtitle(engine_module, subtitle_file)
    destination = _destination(engine_module, "subtitles", f"{source.stem}-burned.mp4")
    _run([
        str(_ffmpeg(engine_module)), "-nostdin", "-y", "-i", str(source),
        "-vf", f"subtitles='{_filter_path(subtitle)}'", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(destination),
    ])
    return MediaPostprocessResult(destination, "burn-subtitle")


def run_media_postprocess_self_test() -> None:
    rendered = render_filename_template("{channel}/{upload_date} - {title}.{ext}", {"channel": "Demo", "upload_date": "20260903", "title": "A:B"}, extension="mkv")
    assert "/" not in rendered and "\\" not in rendered
    assert rendered.endswith(".mkv")
    assert render_filename_template("{title}.{ext}", {"title": "demo"}, extension="mp4") == "demo.mp4"
