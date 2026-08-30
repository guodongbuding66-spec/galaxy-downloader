from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import parse_qs, unquote, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadCancelled, DownloadError

APP_NAME = "Galaxy Local Engine"
PROTOCOL = "galaxy-downloader"
VERSION = "0.1.0"
SUPPORTED_BROWSERS = {"none", "edge", "chrome", "firefox", "brave", "chromium", "opera", "vivaldi"}


@dataclass(frozen=True)
class Job:
    source_url: str
    video_quality: str = "best"
    audio_quality: str = "best"
    include_audio: bool = True
    include_subtitle: bool = False
    subtitle_lang: str | None = None
    include_cover: bool = False
    browser: str = "none"
    playlist: bool = False


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def parse_job(raw: str) -> Job:
    parsed = urlparse(raw)
    if parsed.scheme.lower() != PROTOCOL:
        raise ValueError("Unsupported protocol")
    action = (parsed.netloc or parsed.path.lstrip("/")).lower()
    if action != "download":
        raise ValueError("Unsupported action")

    query = parse_qs(parsed.query)
    source_url = unquote(query.get("url", [""])[0]).strip()
    source = urlparse(source_url)
    if source.scheme not in {"http", "https"} or not source.netloc:
        raise ValueError("A valid http(s) media URL is required")

    browser = query.get("browser", ["none"])[0].lower().strip()
    if browser not in SUPPORTED_BROWSERS:
        browser = "none"

    subtitle_lang = query.get("subtitle_lang", [""])[0].strip() or None
    return Job(
        source_url=source_url,
        video_quality=query.get("video", ["best"])[0].strip() or "best",
        audio_quality=query.get("audio", ["best"])[0].strip() or "best",
        include_audio=_bool(query.get("include_audio", ["1"])[0], True),
        include_subtitle=_bool(query.get("subtitle", ["0"])[0]),
        subtitle_lang=subtitle_lang,
        include_cover=_bool(query.get("cover", ["0"])[0]),
        browser=browser,
        playlist=_bool(query.get("playlist", ["0"])[0]),
    )


def human_bytes(value: float | int | None) -> str:
    if not value:
        return "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return "—"


def human_speed(value: float | int | None) -> str:
    return "—" if not value else f"{human_bytes(value)}/s"


def format_selector(job: Job) -> str:
    raw_height = re.search(r"(\d{3,4})", job.video_quality)
    height = int(raw_height.group(1)) if raw_height else None
    abr_match = re.search(r"(\d{2,3})", job.audio_quality)
    abr = int(abr_match.group(1)) if abr_match else None

    if not job.include_audio:
        return f"bv*[height<={height}]/bv*" if height else "bv*/b"

    audio = f"ba[abr<={abr}]/ba" if abr else "ba"
    if height:
        return f"bv*[height<={height}]+({audio})/b[height<={height}]/b"
    return f"bv*+({audio})/b"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def ffmpeg_dir() -> Path | None:
    candidates = [
        app_dir() / "ffmpeg" / "bin",
        app_dir() / "bin",
        app_dir(),
    ]
    for candidate in candidates:
        if (candidate / "ffmpeg.exe").exists() or (candidate / "ffmpeg").exists():
            return candidate
    return None


def default_download_dir() -> Path:
    target = Path.home() / "Downloads" / "Galaxy Downloader"
    target.mkdir(parents=True, exist_ok=True)
    return target


class EngineWindow(tk.Tk):
    def __init__(self, job: Job | None):
        super().__init__()
        self.job = job
        self.cancel_event = threading.Event()
        self.last_path: Path | None = None
        self.title(APP_NAME)
        self.geometry("620x420")
        self.minsize(520, 360)
        self.configure(bg="#f6f8fc")

        self.status_var = tk.StringVar(value="Ready")
        self.detail_var = tk.StringVar(value="Waiting for a download job")
        self.percent_var = tk.DoubleVar(value=0)
        self.speed_var = tk.StringVar(value="—")
        self.eta_var = tk.StringVar(value="—")
        self.size_var = tk.StringVar(value="—")

        self._build_ui()
        if self.job:
            self.after(120, self.start_job)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Galaxy.Horizontal.TProgressbar", thickness=12)

        wrapper = tk.Frame(self, bg="#f6f8fc", padx=26, pady=24)
        wrapper.pack(fill="both", expand=True)

        tk.Label(wrapper, text=APP_NAME, font=("Segoe UI Variable Display", 20, "bold"), bg="#f6f8fc", fg="#14213d").pack(anchor="w")
        tk.Label(wrapper, text=f"Local yt-dlp + FFmpeg · v{VERSION}", font=("Segoe UI", 9), bg="#f6f8fc", fg="#667085").pack(anchor="w", pady=(2, 20))

        card = tk.Frame(wrapper, bg="#ffffff", highlightthickness=1, highlightbackground="#dfe5f0", padx=20, pady=18)
        card.pack(fill="both", expand=True)

        tk.Label(card, textvariable=self.status_var, font=("Segoe UI", 12, "bold"), bg="#ffffff", fg="#172b4d").pack(anchor="w")
        tk.Label(card, textvariable=self.detail_var, font=("Segoe UI", 9), bg="#ffffff", fg="#667085", wraplength=540, justify="left").pack(anchor="w", pady=(5, 14))
        ttk.Progressbar(card, variable=self.percent_var, maximum=100, style="Galaxy.Horizontal.TProgressbar").pack(fill="x")

        stats = tk.Frame(card, bg="#ffffff")
        stats.pack(fill="x", pady=(16, 0))
        for index, (title, var) in enumerate((("Speed", self.speed_var), ("ETA", self.eta_var), ("Downloaded", self.size_var))):
            cell = tk.Frame(stats, bg="#ffffff")
            cell.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 8, 0))
            stats.grid_columnconfigure(index, weight=1)
            tk.Label(cell, text=title, font=("Segoe UI", 8), bg="#ffffff", fg="#98a2b3").pack(anchor="w")
            tk.Label(cell, textvariable=var, font=("Segoe UI", 10, "bold"), bg="#ffffff", fg="#344054").pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(wrapper, bg="#f6f8fc")
        actions.pack(fill="x", pady=(16, 0))
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.cancel)
        self.cancel_button.pack(side="left")
        self.cancel_button.state(["disabled"])
        self.folder_button = ttk.Button(actions, text="Open download folder", command=self.open_folder)
        self.folder_button.pack(side="right")

    def ui(self, fn, *args) -> None:
        self.after(0, fn, *args)

    def set_status(self, title: str, detail: str | None = None) -> None:
        self.ui(self.status_var.set, title)
        if detail is not None:
            self.ui(self.detail_var.set, detail)

    def progress_hook(self, data: dict) -> None:
        if self.cancel_event.is_set():
            raise DownloadCancelled("Cancelled by user")
        status = data.get("status")
        if status == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            percent = (downloaded / total * 100) if total else 0
            self.ui(self.percent_var.set, max(0, min(100, percent)))
            self.ui(self.speed_var.set, human_speed(data.get("speed")))
            eta = data.get("eta")
            self.ui(self.eta_var.set, "—" if eta is None else f"{int(eta)} s")
            self.ui(self.size_var.set, human_bytes(downloaded))
            filename = data.get("filename") or "Downloading media"
            self.set_status("Downloading", Path(filename).name)
        elif status == "finished":
            filename = data.get("filename")
            if filename:
                self.last_path = Path(filename)
            self.ui(self.percent_var.set, 100)
            self.set_status("Download finished", "Preparing final file with FFmpeg")

    def postprocessor_hook(self, data: dict) -> None:
        if self.cancel_event.is_set():
            raise DownloadCancelled("Cancelled by user")
        name = data.get("postprocessor") or "FFmpeg"
        status = data.get("status")
        if status == "started":
            self.set_status("Processing", f"{name} is building the final file")
        elif status == "finished":
            info = data.get("info_dict") or {}
            filepath = info.get("filepath") or info.get("_filename")
            if filepath:
                self.last_path = Path(filepath)
            self.set_status("Finalizing", f"{name} completed")

    def build_options(self) -> dict:
        assert self.job is not None
        output_dir = default_download_dir()
        postprocessors = [{"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True, "add_infojson": False}]
        if self.job.include_subtitle:
            postprocessors.extend([
                {"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"},
                {"key": "FFmpegEmbedSubtitle"},
            ])
        if self.job.include_cover:
            postprocessors.append({"key": "EmbedThumbnail"})

        options = {
            "format": format_selector(self.job),
            "outtmpl": str(output_dir / "%(title).180B [%(id)s].%(ext)s"),
            "windowsfilenames": True,
            "noplaylist": not self.job.playlist,
            "continuedl": True,
            "retries": 10,
            "fragment_retries": 10,
            "extractor_retries": 5,
            "file_access_retries": 5,
            "concurrent_fragment_downloads": 4,
            "merge_output_format": "mp4",
            "writethumbnail": self.job.include_cover,
            "writesubtitles": self.job.include_subtitle,
            "writeautomaticsub": self.job.include_subtitle,
            "subtitlesformat": "srt/best",
            "subtitleslangs": [self.job.subtitle_lang] if self.job.subtitle_lang else ["zh-Hans", "zh-Hant", "zh", "en", "ja", "es", "ru"],
            "postprocessors": postprocessors,
            "progress_hooks": [self.progress_hook],
            "postprocessor_hooks": [self.postprocessor_hook],
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "socket_timeout": 30,
        }
        ffmpeg = ffmpeg_dir()
        if ffmpeg:
            options["ffmpeg_location"] = str(ffmpeg)
        if self.job.browser != "none":
            options["cookiesfrombrowser"] = (self.job.browser, None, None, None)
        return options

    def start_job(self) -> None:
        if not self.job:
            return
        self.cancel_event.clear()
        self.cancel_button.state(["!disabled"])
        self.set_status("Starting", self.job.source_url)
        threading.Thread(target=self._run_job, daemon=True).start()

    def _run_job(self) -> None:
        assert self.job is not None
        try:
            with YoutubeDL(self.build_options()) as ydl:
                result = ydl.extract_info(self.job.source_url, download=True)
                path = ydl.prepare_filename(result)
                if path:
                    self.last_path = Path(path)
            self.ui(self.percent_var.set, 100)
            self.set_status("Completed", "The finished media file is saved on this computer")
        except DownloadCancelled:
            self.set_status("Cancelled", "The local download was cancelled")
        except DownloadError as exc:
            self.set_status("Download failed", str(exc))
        except Exception as exc:  # noqa: BLE001
            self.set_status("Download failed", str(exc))
        finally:
            self.ui(self.cancel_button.state, ["disabled"])

    def cancel(self) -> None:
        self.cancel_event.set()
        self.set_status("Cancelling", "Stopping at the next safe download checkpoint")

    def open_folder(self) -> None:
        target = self.last_path.parent if self.last_path and self.last_path.parent.exists() else default_download_dir()
        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Could not open the folder:\n{exc}")


def main() -> int:
    raw = sys.argv[1] if len(sys.argv) > 1 else None
    job = None
    if raw:
        try:
            job = parse_job(raw)
        except Exception as exc:  # noqa: BLE001
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(APP_NAME, f"Invalid Galaxy download request:\n{exc}")
            root.destroy()
            return 2
    app = EngineWindow(job)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
