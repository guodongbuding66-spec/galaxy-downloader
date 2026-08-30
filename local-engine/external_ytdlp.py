from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

PROGRESS_PREFIX = "__GALAXY_PROGRESS__"
FILE_PREFIX = "__GALAXY_FILE__"
UPDATE_STAMP = ".yt-dlp-nightly-check"
DEFAULT_UPDATE_INTERVAL = 12 * 60 * 60
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class ExternalYtDlpError(RuntimeError):
    pass


def external_ytdlp_path(app_dir: Path) -> Path | None:
    candidates = [
        app_dir / "yt-dlp.exe",
        app_dir / "bin" / "yt-dlp.exe",
        app_dir / "yt-dlp",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def managed_plugin_dirs(executable: Path) -> list[Path]:
    """Return only Galaxy-managed yt-dlp plugin packages.

    The external yt-dlp process is intentionally launched with
    ``--no-plugin-dirs`` and then these directories are added explicitly. This
    prevents an unrelated plugin from a user's global yt-dlp configuration from
    silently changing Galaxy download behavior.
    """
    try:
        root = executable.resolve().parent / "plugins"
    except OSError:
        root = executable.parent / "plugins"
    if not root.is_dir():
        return []

    output: list[Path] = []
    try:
        children = sorted(root.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return []
    for child in children:
        if child.is_dir() and (child / "yt_dlp_plugins").is_dir():
            output.append(child)
    return output


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _clean_line(value: str) -> str:
    return ANSI_RE.sub("", value).strip()


def external_version(executable: Path) -> str | None:
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=_creation_flags(),
            check=False,
        )
    except Exception:
        return None
    value = _clean_line(result.stdout or result.stderr)
    return value.splitlines()[0].strip() if value else None


def update_external_ytdlp_if_due(
    executable: Path,
    app_dir: Path,
    *,
    interval_seconds: int = DEFAULT_UPDATE_INTERVAL,
) -> tuple[bool, str | None]:
    """Update official yt-dlp binary to nightly at most once per interval.

    Returns `(attempted, version)`. Update failures are intentionally non-fatal;
    the existing verified binary remains available as the primary runner and the
    embedded Python yt-dlp remains a second fallback.
    """
    stamp = app_dir / UPDATE_STAMP
    now = time.time()
    try:
        if stamp.exists() and now - stamp.stat().st_mtime < interval_seconds:
            return False, external_version(executable)
    except OSError:
        pass

    try:
        result = subprocess.run(
            [str(executable), "--update-to", "nightly"],
            capture_output=True,
            text=True,
            timeout=90,
            creationflags=_creation_flags(),
            check=False,
        )
        # Record the check even when GitHub is temporarily unavailable. This
        # prevents every download click from repeatedly retrying the network.
        stamp.touch(exist_ok=True)
        if result.returncode != 0:
            return True, external_version(executable)
        return True, external_version(executable)
    except Exception:
        try:
            stamp.touch(exist_ok=True)
        except OSError:
            pass
        return True, external_version(executable)


def _reader_thread(stream, output: queue.Queue[str | None]) -> None:
    try:
        for raw in iter(stream.readline, ""):
            output.put(raw)
    finally:
        output.put(None)


def _parse_percent(value: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)", value)
    if not match:
        return 0.0
    return max(0.0, min(100.0, float(match.group(1))))


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def build_external_command(
    executable: Path,
    source_url: str,
    *,
    format_selector: str,
    output_template: str,
    ffmpeg_location: Path | None,
    browser: str,
    playlist: bool,
    include_subtitle: bool,
    subtitle_language: str | None,
    include_cover: bool,
) -> list[str]:
    command = [str(executable), "--no-plugin-dirs"]
    for plugin_dir in managed_plugin_dirs(executable):
        command.extend(["--plugin-dirs", str(plugin_dir)])

    command.extend([
        "--newline",
        "--no-colors",
        "--continue",
        "--retries", "10",
        "--fragment-retries", "10",
        "--extractor-retries", "5",
        "--concurrent-fragments", "4",
        "--merge-output-format", "mp4",
        "--windows-filenames",
        "--embed-metadata",
        "--embed-chapters",
        "--progress-template",
        f"download:{PROGRESS_PREFIX}%(progress._percent_str)s\t%(progress._speed_str)s\t%(progress._eta_str)s\t%(progress._downloaded_bytes_str)s\t%(progress._total_bytes_str)s",
        "--print",
        f"after_move:{FILE_PREFIX}%(filepath)s",
        "-f", format_selector,
        "-o", output_template,
    ])

    command.append("--yes-playlist" if playlist else "--no-playlist")

    if ffmpeg_location:
        command.extend(["--ffmpeg-location", str(ffmpeg_location)])

    if browser and browser != "none":
        command.extend(["--cookies-from-browser", browser])

    if include_subtitle:
        langs = subtitle_language or "zh-Hans,zh-Hant,zh,en,ja,es,ru"
        command.extend([
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", langs,
            "--sub-format", "srt/best",
            "--convert-subs", "srt",
            "--embed-subs",
        ])

    if include_cover:
        command.extend(["--write-thumbnail", "--embed-thumbnail"])

    command.extend(["--", source_url])
    return command


def download_with_external_ytdlp(
    executable: Path,
    source_url: str,
    *,
    format_selector: str,
    output_template: str,
    ffmpeg_location: Path | None,
    browser: str,
    playlist: bool,
    include_subtitle: bool,
    subtitle_language: str | None,
    include_cover: bool,
    cancelled: Callable[[], bool],
    on_progress: Callable[[float, str, str, str, str], None],
    on_status: Callable[[str], None],
) -> Path | None:
    command = build_external_command(
        executable,
        source_url,
        format_selector=format_selector,
        output_template=output_template,
        ffmpeg_location=ffmpeg_location,
        browser=browser,
        playlist=playlist,
        include_subtitle=include_subtitle,
        subtitle_language=subtitle_language,
        include_cover=include_cover,
    )

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_creation_flags(),
    )
    assert process.stdout is not None

    lines: queue.Queue[str | None] = queue.Queue()
    reader = threading.Thread(target=_reader_thread, args=(process.stdout, lines), daemon=True)
    reader.start()

    final_path: Path | None = None
    recent_errors: list[str] = []
    reader_finished = False

    while process.poll() is None or not reader_finished:
        if cancelled():
            _terminate_process(process)
            raise ExternalYtDlpError("Cancelled by user")

        try:
            raw = lines.get(timeout=0.15)
        except queue.Empty:
            continue

        if raw is None:
            reader_finished = True
            continue

        line = _clean_line(raw)
        if not line:
            continue

        if line.startswith(PROGRESS_PREFIX):
            payload = line[len(PROGRESS_PREFIX):]
            fields = payload.split("\t")
            fields += ["—"] * (5 - len(fields))
            on_progress(_parse_percent(fields[0]), fields[1], fields[2], fields[3], fields[4])
            continue

        if line.startswith(FILE_PREFIX):
            value = line[len(FILE_PREFIX):].strip()
            if value:
                final_path = Path(value)
            continue

        if "ERROR:" in line.upper() or "WARNING:" in line.upper():
            recent_errors.append(line)
            recent_errors = recent_errors[-8:]
        if line.startswith("["):
            on_status(line)

    return_code = process.wait()
    if return_code != 0:
        detail = "\n".join(recent_errors[-4:]) or f"yt-dlp exited with code {return_code}"
        raise ExternalYtDlpError(detail)

    return final_path
