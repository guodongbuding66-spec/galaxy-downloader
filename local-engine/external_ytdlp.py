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
COOKIE_ACCESS_PATTERNS = (
    "could not copy chrome cookie database",
    "could not copy edge cookie database",
    "could not copy firefox cookie database",
    "cookie database is locked",
    "database is locked",
    "failed to decrypt with dpapi",
    "failed to decrypt cookie",
)


class ExternalYtDlpError(RuntimeError):
    pass


class BrowserCookieAccessError(RuntimeError):
    """Raised when a user-selected browser session cannot be read safely."""


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
    """Optionally update yt-dlp without making normal downloads depend on GitHub.

    Galaxy release ZIPs already contain a verified yt-dlp.exe. Automatic online
    updates are disabled by default so users who cannot reach GitHub do not wait
    for a network timeout before downloading media.

    Advanced users can opt in by setting GALAXY_YTDLP_AUTO_UPDATE=1.
    """
    enabled = os.environ.get("GALAXY_YTDLP_AUTO_UPDATE", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False, external_version(executable)

    stamp = app_dir / UPDATE_STAMP
    now = time.time()
    try:
        if stamp.exists() and now - stamp.stat().st_mtime < interval_seconds:
            return False, external_version(executable)
    except OSError:
        pass

    try:
        subprocess.run(
            [str(executable), "--update-to", "nightly"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_creation_flags(),
            check=False,
        )
        stamp.touch(exist_ok=True)
        return True, external_version(executable)
    except Exception:
        try:
            stamp.touch(exist_ok=True)
        except OSError:
            pass
        return True, external_version(executable)


def is_cookie_access_error(detail: str) -> bool:
    lowered = detail.lower()
    return any(pattern in lowered for pattern in COOKIE_ACCESS_PATTERNS)


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
    command = [
        str(executable),
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
    ]

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


def _run_external_once(
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
            recent_errors = recent_errors[-10:]
        if line.startswith("["):
            on_status(line)

    return_code = process.wait()
    if return_code != 0:
        detail = "\n".join(recent_errors[-5:]) or f"yt-dlp exited with code {return_code}"
        raise ExternalYtDlpError(detail)

    return final_path


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
    # A selected browser session is a fallback, not the first step. Most public
    # videos do not require cookies at all, and Chromium browsers commonly keep
    # their cookie SQLite database locked while the browser is open. Trying the
    # public path first avoids that entire failure mode for ordinary downloads.
    if browser and browser != "none":
        on_status("[Galaxy] 正在先尝试无需浏览器 Cookie 的公开下载。")
        try:
            return _run_external_once(
                executable,
                source_url,
                format_selector=format_selector,
                output_template=output_template,
                ffmpeg_location=ffmpeg_location,
                browser="none",
                playlist=playlist,
                include_subtitle=include_subtitle,
                subtitle_language=subtitle_language,
                include_cover=include_cover,
                cancelled=cancelled,
                on_progress=on_progress,
                on_status=on_status,
            )
        except ExternalYtDlpError as public_error:
            if cancelled():
                raise

            on_status(
                f"[Galaxy] 公开下载未成功，正在尝试读取 {browser} 登录状态。"
            )
            try:
                return _run_external_once(
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
                    cancelled=cancelled,
                    on_progress=on_progress,
                    on_status=on_status,
                )
            except ExternalYtDlpError as browser_error:
                if is_cookie_access_error(str(browser_error)):
                    raise BrowserCookieAccessError(
                        f"无法读取 {browser} 的浏览器 Cookie。通常是浏览器正在占用 Cookie 数据库。"
                        f"请先完全关闭 {browser} 后重试；如果是公开视频，也可以在网站登录状态中选择“不读取浏览器 Cookie”。\n"
                        f"原始错误：{browser_error}"
                    ) from browser_error

                raise ExternalYtDlpError(
                    "无需 Cookie 与浏览器登录状态两种方式都未成功。\n"
                    f"公开下载错误：{public_error}\n"
                    f"浏览器登录状态错误：{browser_error}"
                ) from browser_error

    return _run_external_once(
        executable,
        source_url,
        format_selector=format_selector,
        output_template=output_template,
        ffmpeg_location=ffmpeg_location,
        browser="none",
        playlist=playlist,
        include_subtitle=include_subtitle,
        subtitle_language=subtitle_language,
        include_cover=include_cover,
        cancelled=cancelled,
        on_progress=on_progress,
        on_status=on_status,
    )
