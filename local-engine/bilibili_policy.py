from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

DANMAKU_LANGUAGE = "danmaku"
DANMAKU_TIMEOUT_SECONDS = 60
COLLECTION_MODES = {"single", "all", "selected"}


class BilibiliDanmakuError(RuntimeError):
    pass


def is_bilibili_url(value: object) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return (
        hostname == "bilibili.com"
        or hostname.endswith(".bilibili.com")
        or hostname == "b23.tv"
        or hostname.endswith(".b23.tv")
    )


def _normalized_collection_mode(collection_mode: str | None, playlist: bool) -> str:
    value = str(collection_mode or "").strip().lower()
    if value in COLLECTION_MODES:
        return value
    return "all" if playlist else "single"


def _selected_item_spec(selected_items: tuple[int, ...] | list[int] | None) -> str | None:
    values: list[int] = []
    for raw in selected_items or ():
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in values:
            values.append(value)
    return ",".join(str(value) for value in values) or None


def _creation_flags() -> int:
    if subprocess.mswindows:  # type: ignore[attr-defined]
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def build_danmaku_command(
    executable: Path,
    source_url: str,
    *,
    output_template: str,
    playlist: bool,
    collection_mode: str | None = None,
    selected_items: tuple[int, ...] | list[int] | None = None,
    browser: str = "none",
) -> list[str]:
    """Build a deterministic yt-dlp pass that writes only Bilibili danmaku XML."""
    if not is_bilibili_url(source_url):
        raise BilibiliDanmakuError("danmaku sidecars are only supported for Bilibili URLs")

    command = [
        str(executable),
        "--ignore-config",
        "--newline",
        "--no-colors",
        "--skip-download",
        "--write-subs",
        "--no-write-auto-subs",
        "--sub-langs",
        DANMAKU_LANGUAGE,
        "--sub-format",
        "xml",
        "--no-embed-subs",
        "--no-write-thumbnail",
        "--no-write-info-json",
        "--no-write-comments",
        "--no-write-playlist-metafiles",
        "-o",
        output_template,
    ]

    mode = _normalized_collection_mode(collection_mode, playlist)
    selected_spec = _selected_item_spec(selected_items)
    if mode == "all":
        command.append("--yes-playlist")
    elif mode == "selected" and selected_spec:
        command.extend(["--yes-playlist", "--playlist-items", selected_spec])
    else:
        command.extend(["--no-playlist", "--playlist-items", "1"])

    if browser and browser != "none":
        command.extend(["--cookies-from-browser", browser])

    command.extend(["--", source_url])
    return command


def _terminate(process: subprocess.Popen[str]) -> None:
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


def _run_once(
    command: list[str],
    *,
    cancelled: Callable[[], bool],
) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creation_flags(),
    )
    started = time.monotonic()
    output = ""
    while True:
        if cancelled():
            _terminate(process)
            raise BilibiliDanmakuError("Cancelled by user")
        try:
            output, _ = process.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if time.monotonic() - started >= DANMAKU_TIMEOUT_SECONDS:
                _terminate(process)
                raise BilibiliDanmakuError("Bilibili danmaku sidecar timed out")

    if process.returncode != 0:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        detail = "\n".join(lines[-5:]) or f"yt-dlp exited with code {process.returncode}"
        raise BilibiliDanmakuError(detail)


def download_danmaku_sidecar(
    executable: Path,
    source_url: str,
    *,
    output_template: str,
    browser: str,
    playlist: bool,
    collection_mode: str | None,
    selected_items: tuple[int, ...] | list[int] | None,
    cancelled: Callable[[], bool],
    on_status: Callable[[str], None],
) -> None:
    """Save Bilibili's native XML danmaku without touching normal subtitle flags.

    The public path is attempted first to avoid locked Chromium cookie databases.
    If it fails and the user selected a browser, a single cookie-backed retry is
    attempted. A sidecar error is reported to the caller but never deletes or
    rewrites an already completed media file.
    """
    on_status("[Galaxy] 正在保存 Bilibili 弹幕 XML…")
    public_command = build_danmaku_command(
        executable,
        source_url,
        output_template=output_template,
        playlist=playlist,
        collection_mode=collection_mode,
        selected_items=selected_items,
        browser="none",
    )
    try:
        _run_once(public_command, cancelled=cancelled)
    except BilibiliDanmakuError as public_error:
        if cancelled() or not browser or browser == "none":
            raise
        on_status("[Galaxy] 公开弹幕读取失败，正在尝试浏览器登录会话…")
        cookie_command = build_danmaku_command(
            executable,
            source_url,
            output_template=output_template,
            playlist=playlist,
            collection_mode=collection_mode,
            selected_items=selected_items,
            browser=browser,
        )
        try:
            _run_once(cookie_command, cancelled=cancelled)
        except BilibiliDanmakuError as cookie_error:
            raise BilibiliDanmakuError(str(cookie_error) or str(public_error)) from cookie_error
    on_status("[Galaxy] Bilibili 弹幕 XML 已保存。")


def run_bilibili_policy_self_test() -> None:
    assert is_bilibili_url("https://www.bilibili.com/video/BV1demo")
    assert is_bilibili_url("https://m.bilibili.com/video/BV1demo")
    assert is_bilibili_url("https://b23.tv/demo")
    assert not is_bilibili_url("https://bilibili.com.evil.example/video/BV1demo")
    assert not is_bilibili_url("file:///bilibili.com/video/BV1demo")

    command = build_danmaku_command(
        Path("yt-dlp"),
        "https://www.bilibili.com/video/BV1demo",
        output_template="%(title)s [%(id)s].%(ext)s",
        playlist=False,
    )
    assert "--skip-download" in command
    assert command[command.index("--sub-langs") + 1] == DANMAKU_LANGUAGE
    assert command[command.index("--sub-format") + 1] == "xml"
    assert "--convert-subs" not in command
    assert "--embed-subs" not in command
    assert command[-2:] == ["--", "https://www.bilibili.com/video/BV1demo"]
