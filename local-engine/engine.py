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
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadCancelled, DownloadError

from bridge import LocalBridge, bridge_is_running, post_job_to_running_engine
from external_ytdlp import (
    ExternalYtDlpError,
    build_external_command,
    download_with_external_ytdlp,
    external_ytdlp_path,
)

APP_NAME = "Galaxy Local Engine"
PROTOCOL = "galaxy-downloader"
SUPPORTED_BROWSERS = {"none", "edge", "chrome", "firefox", "brave", "chromium", "opera", "vivaldi"}


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def read_version() -> str:
    path = resource_path("VERSION")
    try:
        version = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Missing bundled VERSION file: {path}") from exc
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError(f"Invalid VERSION value: {version!r}")
    return version


VERSION = read_version()


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


def _validated_source_url(value: str) -> str:
    source_url = value.strip()
    source = urlparse(source_url)
    if source.scheme not in {"http", "https"} or not source.netloc:
        raise ValueError("A valid http(s) media URL is required")
    return source_url


def _validated_browser(value: str | None) -> str:
    browser = (value or "none").lower().strip()
    return browser if browser in SUPPORTED_BROWSERS else "none"


def parse_job(raw: str) -> Job:
    parsed = urlparse(raw)
    if parsed.scheme.lower() != PROTOCOL:
        raise ValueError("Unsupported protocol")
    action = (parsed.netloc or parsed.path.lstrip("/")).lower()
    if action != "download":
        raise ValueError("Unsupported action")

    query = parse_qs(parsed.query)
    source_url = _validated_source_url(unquote(query.get("url", [""])[0]))
    subtitle_lang = query.get("subtitle_lang", [""])[0].strip() or None
    return Job(
        source_url=source_url,
        video_quality=query.get("video", ["best"])[0].strip() or "best",
        audio_quality=query.get("audio", ["best"])[0].strip() or "best",
        include_audio=_bool(query.get("include_audio", ["1"])[0], True),
        include_subtitle=_bool(query.get("subtitle", ["0"])[0]),
        subtitle_lang=subtitle_lang,
        include_cover=_bool(query.get("cover", ["0"])[0]),
        browser=_validated_browser(query.get("browser", ["none"])[0]),
        playlist=_bool(query.get("playlist", ["0"])[0]),
    )


def job_from_payload(payload: dict[str, Any]) -> Job:
    source_url = _validated_source_url(str(payload.get("sourceUrl") or ""))
    subtitle_value = payload.get("subtitleLanguage")
    subtitle_lang = str(subtitle_value).strip() if subtitle_value else None
    return Job(
        source_url=source_url,
        video_quality=str(payload.get("videoQuality") or "best").strip() or "best",
        audio_quality=str(payload.get("audioQuality") or "best").strip() or "best",
        include_audio=bool(payload.get("includeAudio", True)),
        include_subtitle=bool(payload.get("includeSubtitle", False)),
        subtitle_lang=subtitle_lang,
        include_cover=bool(payload.get("includeCover", False)),
        browser=_validated_browser(str(payload.get("browser") or "none")),
        playlist=bool(payload.get("playlist", False)),
    )


def job_to_payload(job: Job) -> dict[str, Any]:
    return {
        "sourceUrl": job.source_url,
        "videoQuality": job.video_quality,
        "audioQuality": job.audio_quality,
        "includeAudio": job.include_audio,
        "includeSubtitle": job.include_subtitle,
        "subtitleLanguage": job.subtitle_lang,
        "includeCover": job.include_cover,
        "browser": job.browser,
        "playlist": job.playlist,
    }


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
        return f"bv*[height<={height}]+{audio}/b[height<={height}]/b"
    return f"bv*+{audio}/b"


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
    target = app_dir() / "downloads"
    target.mkdir(parents=True, exist_ok=True)
    return target


def run_self_test() -> int:
    sample = (
        "galaxy-downloader://download?"
        "url=https%3A%2F%2Fexample.com%2Fwatch%3Fv%3Dabc123%26list%3Ddemo"
        "&video=1080p&audio=192&include_audio=1&subtitle=1&subtitle_lang=zh-Hans"
        "&cover=1&browser=edge&playlist=0"
    )
    job = parse_job(sample)
    assert job.source_url == "https://example.com/watch?v=abc123&list=demo"
    assert job.video_quality == "1080p"
    assert job.audio_quality == "192"
    assert job.include_audio is True
    assert job.include_subtitle is True
    assert job.subtitle_lang == "zh-Hans"
    assert job.include_cover is True
    assert job.browser == "edge"
    assert job.playlist is False
    selector = format_selector(job)
    assert "height<=1080" in selector
    assert "abr<=192" in selector

    payload_job = job_from_payload(job_to_payload(job))
    assert payload_job == job

    external_command = build_external_command(
        Path("yt-dlp.exe"),
        job.source_url,
        format_selector=selector,
        output_template="%(title)s.%(ext)s",
        ffmpeg_location=Path("ffmpeg"),
        browser=job.browser,
        playlist=job.playlist,
        include_subtitle=job.include_subtitle,
        subtitle_language=job.subtitle_lang,
        include_cover=job.include_cover,
    )
    assert "--cookies-from-browser" in external_command
    assert "edge" in external_command
    assert "--embed-subs" in external_command
    assert "--embed-thumbnail" in external_command
    assert external_command[-1] == job.source_url

    try:
        parse_job("galaxy-downloader://download?url=file%3A%2F%2FC%3A%2Fsecret.txt")
    except ValueError:
        pass
    else:
        raise AssertionError("non-http source was accepted")

    print(f"{APP_NAME} {VERSION} self-test OK")
    return 0


class EngineWindow(tk.Tk):
    def __init__(self, job: Job | None):
        super().__init__()
        self.job = job
        self.cancel_event = threading.Event()
        self.last_path: Path | None = None
        self.running = False
        self._state_lock = threading.Lock()
        self._bridge_snapshot: dict[str, Any] = {
            "version": VERSION,
            "state": "ready",
            "status": "Ready",
            "detail": "Waiting for a download job",
            "busy": False,
            "progress": 0.0,
            "speed": "—",
            "eta": "—",
            "downloaded": "—",
        }

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
        self.protocol("WM_DELETE_WINDOW", self.close_app)

        self.bridge = LocalBridge(
            status_provider=self.bridge_status,
            submit_job=self.submit_bridge_job,
            cancel_job=self.cancel_from_bridge,
            open_folder=self.open_folder_from_bridge,
        )
        try:
            self.bridge.start()
        except OSError as exc:
            messagebox.showerror(
                APP_NAME,
                f"Could not start the local website bridge on 127.0.0.1.\n\n{exc}",
            )
            self.after(50, self.destroy)
            return

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

        tk.Label(
            wrapper,
            text=APP_NAME,
            font=("Segoe UI Variable Display", 20, "bold"),
            bg="#f6f8fc",
            fg="#14213d",
        ).pack(anchor="w")
        tk.Label(
            wrapper,
            text=f"Local yt-dlp + FFmpeg · v{VERSION}",
            font=("Segoe UI", 9),
            bg="#f6f8fc",
            fg="#667085",
        ).pack(anchor="w", pady=(2, 20))

        card = tk.Frame(
            wrapper,
            bg="#ffffff",
            highlightthickness=1,
            highlightbackground="#dfe5f0",
            padx=20,
            pady=18,
        )
        card.pack(fill="both", expand=True)

        tk.Label(
            card,
            textvariable=self.status_var,
            font=("Segoe UI", 12, "bold"),
            bg="#ffffff",
            fg="#172b4d",
        ).pack(anchor="w")
        tk.Label(
            card,
            textvariable=self.detail_var,
            font=("Segoe UI", 9),
            bg="#ffffff",
            fg="#667085",
            wraplength=540,
            justify="left",
        ).pack(anchor="w", pady=(5, 14))
        ttk.Progressbar(
            card,
            variable=self.percent_var,
            maximum=100,
            style="Galaxy.Horizontal.TProgressbar",
        ).pack(fill="x")

        stats = tk.Frame(card, bg="#ffffff")
        stats.pack(fill="x", pady=(16, 0))
        for index, (title, var) in enumerate(
            (("Speed", self.speed_var), ("ETA", self.eta_var), ("Downloaded", self.size_var))
        ):
            cell = tk.Frame(stats, bg="#ffffff")
            cell.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 8, 0))
            stats.grid_columnconfigure(index, weight=1)
            tk.Label(
                cell,
                text=title,
                font=("Segoe UI", 8),
                bg="#ffffff",
                fg="#98a2b3",
            ).pack(anchor="w")
            tk.Label(
                cell,
                textvariable=var,
                font=("Segoe UI", 10, "bold"),
                bg="#ffffff",
                fg="#344054",
            ).pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(wrapper, bg="#f6f8fc")
        actions.pack(fill="x", pady=(16, 0))
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.cancel)
        self.cancel_button.pack(side="left")
        self.cancel_button.state(["disabled"])
        self.folder_button = ttk.Button(actions, text="Open download folder", command=self.open_folder)
        self.folder_button.pack(side="right")

    def ui(self, fn, *args) -> None:
        self.after(0, fn, *args)

    def _update_bridge(self, **changes: Any) -> None:
        with self._state_lock:
            self._bridge_snapshot.update(changes)

    def bridge_status(self) -> dict[str, Any]:
        with self._state_lock:
            snapshot = dict(self._bridge_snapshot)
        snapshot.update(
            {
                "version": VERSION,
                "ffmpegReady": ffmpeg_dir() is not None,
                "ytDlpReady": external_ytdlp_path(app_dir()) is not None,
            }
        )
        return snapshot

    def set_status(self, title: str, detail: str | None = None) -> None:
        state_by_title = {
            "Ready": "ready",
            "Starting": "starting",
            "Extractor ready": "starting",
            "Preparing media": "starting",
            "Retrying with embedded extractor": "starting",
            "Downloading": "downloading",
            "Download finished": "processing",
            "Processing": "processing",
            "Finalizing": "processing",
            "Completed": "completed",
            "Cancelling": "cancelling",
            "Cancelled": "cancelled",
            "Download failed": "failed",
        }
        changes: dict[str, Any] = {
            "status": title,
            "state": state_by_title.get(title, "working" if self.running else "ready"),
            "busy": self.running,
        }
        if detail is not None:
            changes["detail"] = detail
        self._update_bridge(**changes)
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
            speed = human_speed(data.get("speed"))
            eta = data.get("eta")
            eta_text = "—" if eta is None else f"{int(eta)} s"
            size_text = human_bytes(downloaded)
            self._update_bridge(
                progress=max(0, min(100, percent)),
                speed=speed,
                eta=eta_text,
                downloaded=size_text,
                busy=True,
            )
            self.ui(self.percent_var.set, max(0, min(100, percent)))
            self.ui(self.speed_var.set, speed)
            self.ui(self.eta_var.set, eta_text)
            self.ui(self.size_var.set, size_text)
            filename = data.get("filename") or "Downloading media"
            self.set_status("Downloading", Path(filename).name)
        elif status == "finished":
            filename = data.get("filename")
            if filename:
                self.last_path = Path(filename)
            self._update_bridge(progress=100.0, busy=True)
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

    def external_progress_hook(
        self,
        percent: float,
        speed: str,
        eta: str,
        downloaded: str,
        total: str,
    ) -> None:
        size = downloaded or "—"
        if total and total != "—":
            size = f"{size} / {total}"
        self._update_bridge(
            progress=max(0, min(100, percent)),
            speed=speed or "—",
            eta=eta or "—",
            downloaded=size,
            busy=True,
        )
        self.ui(self.percent_var.set, percent)
        self.ui(self.speed_var.set, speed or "—")
        self.ui(self.eta_var.set, eta or "—")
        self.ui(self.size_var.set, size)
        self.set_status("Downloading", "Using the bundled yt-dlp extractor on this computer")

    def external_status_hook(self, line: str) -> None:
        if not line:
            return
        self.set_status("Preparing media", line[:220])

    def build_options(self) -> dict:
        assert self.job is not None
        output_dir = default_download_dir()
        postprocessors = [
            {
                "key": "FFmpegMetadata",
                "add_metadata": True,
                "add_chapters": True,
                "add_infojson": False,
            }
        ]
        if self.job.include_subtitle:
            postprocessors.extend(
                [
                    {"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"},
                    {"key": "FFmpegEmbedSubtitle"},
                ]
            )
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
            "subtitleslangs": (
                [self.job.subtitle_lang]
                if self.job.subtitle_lang
                else ["zh-Hans", "zh-Hant", "zh", "en", "ja", "es", "ru"]
            ),
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

    def _reset_job_ui(self) -> None:
        self.percent_var.set(0)
        self.speed_var.set("—")
        self.eta_var.set("—")
        self.size_var.set("—")
        self._update_bridge(progress=0.0, speed="—", eta="—", downloaded="—")

    def start_job(self) -> None:
        if not self.job or self.running:
            return
        self.running = True
        self.cancel_event.clear()
        self._reset_job_ui()
        self.cancel_button.state(["!disabled"])
        self._update_bridge(busy=True, state="starting")
        self.set_status("Starting", self.job.source_url)
        threading.Thread(target=self._run_job, daemon=True).start()

    def submit_bridge_job(self, payload: dict[str, Any]) -> tuple[bool, str]:
        try:
            job = job_from_payload(payload)
        except ValueError as exc:
            return False, str(exc)

        completed = threading.Event()
        result: dict[str, Any] = {"accepted": False, "message": "Local engine did not accept the job"}

        def accept() -> None:
            if self.running:
                result.update(
                    accepted=False,
                    message="Galaxy Local Engine is already processing another job",
                )
            else:
                self.job = job
                self.deiconify()
                self.lift()
                try:
                    self.focus_force()
                except tk.TclError:
                    pass
                self.start_job()
                result.update(accepted=True, message="Download job accepted")
            completed.set()

        self.after(0, accept)
        if not completed.wait(timeout=2.0):
            return False, "Timed out while handing the job to the desktop window"
        return bool(result["accepted"]), str(result["message"])

    def cancel_from_bridge(self) -> None:
        self.after(0, self.cancel)

    def open_folder_from_bridge(self) -> None:
        self.after(0, self.open_folder)

    def _run_external_job(self, executable: Path) -> bool:
        assert self.job is not None
        self.set_status("Extractor ready", "Using the verified yt-dlp bundled with Galaxy Local Engine")

        output_dir = default_download_dir()
        try:
            final_path = download_with_external_ytdlp(
                executable,
                self.job.source_url,
                format_selector=format_selector(self.job),
                output_template=str(output_dir / "%(title).180B [%(id)s].%(ext)s"),
                ffmpeg_location=ffmpeg_dir(),
                browser=self.job.browser,
                playlist=self.job.playlist,
                include_subtitle=self.job.include_subtitle,
                subtitle_language=self.job.subtitle_lang,
                include_cover=self.job.include_cover,
                cancelled=self.cancel_event.is_set,
                on_progress=self.external_progress_hook,
                on_status=self.external_status_hook,
            )
        except ExternalYtDlpError as exc:
            if self.cancel_event.is_set():
                raise DownloadCancelled("Cancelled by user") from exc
            self.set_status("Retrying with embedded extractor", str(exc)[:220])
            return False

        if final_path:
            self.last_path = final_path
        self.ui(self.percent_var.set, 100)
        self._update_bridge(progress=100.0)
        return True

    def _run_job(self) -> None:
        assert self.job is not None
        try:
            external = external_ytdlp_path(app_dir())
            if external and self._run_external_job(external):
                self.set_status("Completed", "The finished media file is saved in the portable downloads folder")
                return

            with YoutubeDL(self.build_options()) as ydl:
                result = ydl.extract_info(self.job.source_url, download=True)
                path = ydl.prepare_filename(result)
                if path:
                    self.last_path = Path(path)
            self.ui(self.percent_var.set, 100)
            self._update_bridge(progress=100.0)
            self.set_status("Completed", "The finished media file is saved in the portable downloads folder")
        except DownloadCancelled:
            self.set_status("Cancelled", "The local download was cancelled")
        except DownloadError as exc:
            self.set_status("Download failed", str(exc))
        except Exception as exc:  # noqa: BLE001
            self.set_status("Download failed", str(exc))
        finally:
            self.running = False
            self._update_bridge(busy=False)
            self.ui(self.cancel_button.state, ["disabled"])

    def cancel(self) -> None:
        if not self.running:
            return
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

    def close_app(self) -> None:
        if self.running:
            self.cancel_event.set()
        try:
            self.bridge.stop()
        finally:
            self.destroy()


def main() -> int:
    if "--self-test" in sys.argv:
        return run_self_test()
    if "--version" in sys.argv:
        print(VERSION)
        return 0

    raw = next((arg for arg in sys.argv[1:] if not arg.startswith("--")), None)
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

        # If the desktop app is already open, hand the protocol job to that
        # instance instead of showing a second window.
        if post_job_to_running_engine(job_to_payload(job)):
            return 0
    elif bridge_is_running():
        # Installer/start-menu launches should keep a single resident window.
        return 0

    app = EngineWindow(job)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
