from __future__ import annotations

import re
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from gallery_dl_runtime import GalleryDlRuntimeError, managed_gallery_dl_modules
from local_task_provider import (
    LocalTaskActionResult,
    LocalTaskSnapshot,
    install_local_task_provider_bridge,
    register_local_task_provider,
)
from url_policy import validated_public_http_url

MAX_GALLERY_DL_FILES = 500
MAX_GALLERY_DL_TASKS = 200
_SAFE_NAME_RE = re.compile(r"[^\w .()+\[\]-]+", re.UNICODE)


class GalleryDlExecutorError(RuntimeError):
    pass


@dataclass(frozen=True)
class GalleryDlRunResult:
    status_code: int
    processed: int
    downloaded: int
    cancelled: bool = False
    limit_reached: bool = False


ProgressCallback = Callable[[str, int, int], None]
Runner = Callable[[str, Path, int, threading.Event, ProgressCallback], GalleryDlRunResult]


@dataclass
class _GalleryTask:
    task_id: str
    source_url: str
    output_root: Path
    max_files: int
    state: str = "queued"
    attempt: int = 1
    processed: int = 0
    downloaded: int = 0
    current_file: str = ""
    detail: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)


def _display_name(kwdict: object) -> str:
    if not isinstance(kwdict, dict):
        return "媒体文件"
    name = str(kwdict.get("filename") or kwdict.get("title") or kwdict.get("id") or "媒体文件")
    extension = str(kwdict.get("extension") or "").strip(". ")
    name = name.replace("\\", "_").replace("/", "_").replace("\x00", "")
    name = _SAFE_NAME_RE.sub("_", name).strip(" ._") or "媒体文件"
    if extension and not name.lower().endswith(f".{extension.lower()}"):
        name = f"{name}.{_SAFE_NAME_RE.sub('', extension)[:16]}"
    return name[:180]


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        resolved_root = root.resolve()
        resolved = candidate.resolve()
    except OSError:
        return False
    return resolved == resolved_root or resolved_root in resolved.parents


def _safe_output_root(root: Path) -> Path:
    target = Path(root)
    try:
        if target.exists() and target.is_symlink():
            raise GalleryDlExecutorError("gallery-dl 输出根目录不能是符号链接。")
        target.mkdir(parents=True, exist_ok=True)
        resolved = target.resolve()
    except OSError as exc:
        raise GalleryDlExecutorError("无法创建 gallery-dl 输出目录。") from exc
    if not resolved.is_dir() or resolved.is_symlink():
        raise GalleryDlExecutorError("gallery-dl 输出根目录不可用。")
    return resolved


def _task_directory(root: Path, task_id: str, attempt: int) -> Path:
    gallery_root = _safe_output_root(root) / "gallery-dl"
    if gallery_root.exists() and gallery_root.is_symlink():
        raise GalleryDlExecutorError("gallery-dl 托管输出目录不能是符号链接。")
    gallery_root.mkdir(parents=True, exist_ok=True)
    gallery_root = gallery_root.resolve()
    target = gallery_root / f"{task_id}-a{attempt}"
    if target.exists() and target.is_symlink():
        raise GalleryDlExecutorError("gallery-dl 任务目录不能是符号链接。")
    target.mkdir(parents=False, exist_ok=True)
    resolved = target.resolve()
    if gallery_root not in resolved.parents:
        raise GalleryDlExecutorError("gallery-dl 任务目录越过了输出边界。")
    return resolved


class _RunController:
    def __init__(
        self,
        root: Path,
        max_files: int,
        cancel_event: threading.Event,
        progress: ProgressCallback,
        stop_exception,
    ) -> None:
        self.root = root.resolve()
        self.max_files = max_files
        self.cancel_event = cancel_event
        self.progress = progress
        self.stop_exception = stop_exception
        self.processed = 0
        self.downloaded = 0
        self.cancelled = False
        self.limit_reached = False

    def _stop(self, *, cancelled: bool = False, limit: bool = False) -> None:
        self.cancelled = self.cancelled or cancelled
        self.limit_reached = self.limit_reached or limit
        raise self.stop_exception()

    def before_resource(self, kwdict: object) -> None:
        if self.cancel_event.is_set():
            self._stop(cancelled=True)
        if self.processed >= self.max_files:
            self._stop(limit=True)
        self.processed += 1
        self.progress(_display_name(kwdict), self.processed, self.downloaded)

    def validate_path(self, value: object) -> None:
        if not value:
            return
        try:
            candidate = Path(str(value))
        except (TypeError, ValueError) as exc:
            raise GalleryDlExecutorError("gallery-dl 生成了无效输出路径。") from exc
        if not _is_within(self.root, candidate):
            raise GalleryDlExecutorError("gallery-dl 生成的路径越过了任务输出边界。")

    def after_resource(self, pathfmt: object) -> None:
        path_value = getattr(pathfmt, "path", "") if pathfmt is not None else ""
        if path_value:
            self.validate_path(path_value)
            try:
                if Path(str(path_value)).is_file():
                    self.downloaded += 1
            except OSError:
                pass
        self.progress("", self.processed, self.downloaded)
        if self.cancel_event.is_set():
            self._stop(cancelled=True)
        if self.processed >= self.max_files:
            self._stop(limit=True)


def _run_managed_gallery_dl(
    engine_module,
    source_url: str,
    task_dir: Path,
    max_files: int,
    cancel_event: threading.Event,
    progress: ProgressCallback,
) -> GalleryDlRunResult:
    with managed_gallery_dl_modules(engine_module) as (config, job_module, exception):
        # Do not load gallery-dl's user/system configuration. Galaxy owns the
        # full execution policy for this task, including output and cache state.
        config.clear()
        config.set((), "base-directory", str(task_dir))
        config.set((), "actions", ())
        config.set((), "postprocessors", ())
        config.set(("output",), "mode", "null")
        config.set(("cache",), "file", ":memory:")

        controller = _RunController(task_dir, max_files, cancel_event, progress, exception.StopExtraction)

        class GalaxyDownloadJob(job_module.DownloadJob):
            def __init__(self, url, parent=None):
                super().__init__(url, parent)
                self._galaxy_controller = (
                    getattr(parent, "_galaxy_controller", controller) if parent is not None else controller
                )

            def handle_directory(self, kwdict):
                super().handle_directory(kwdict)
                pathfmt = getattr(self, "pathfmt", None)
                directory = getattr(pathfmt, "directory", "") if pathfmt is not None else ""
                if directory:
                    self._galaxy_controller.validate_path(directory)

            def handle_url(self, url, kwdict):
                current = self._galaxy_controller
                current.before_resource(kwdict)
                pathfmt = getattr(self, "pathfmt", None)
                if pathfmt is not None:
                    try:
                        pathfmt.set_filename(kwdict)
                        if getattr(pathfmt, "extension", None) and not getattr(self, "metadata_http", None):
                            pathfmt.build_path()
                            current.validate_path(getattr(pathfmt, "path", ""))
                    except GalleryDlExecutorError:
                        raise
                    except Exception:
                        # Let gallery-dl's own handler produce its normal bounded
                        # status for ordinary filename-format errors.
                        pass
                super().handle_url(url, kwdict)
                current.after_resource(getattr(self, "pathfmt", None))

        try:
            status = int(GalaxyDownloadJob(source_url).run() or 0)
        except GalleryDlExecutorError:
            raise
        return GalleryDlRunResult(
            status_code=status,
            processed=controller.processed,
            downloaded=controller.downloaded,
            cancelled=controller.cancelled,
            limit_reached=controller.limit_reached,
        )


class GalleryDlExecutor:
    def __init__(self, engine_module, *, runner: Runner | None = None, validator=validated_public_http_url) -> None:
        self.engine_module = engine_module
        self._validator = validator
        self._runner = runner or (
            lambda source_url, task_dir, max_files, cancel_event, progress: _run_managed_gallery_dl(
                engine_module, source_url, task_dir, max_files, cancel_event, progress
            )
        )
        self._lock = threading.RLock()
        self._tasks: dict[str, _GalleryTask] = {}
        self._queue: deque[str] = deque()
        self._worker: threading.Thread | None = None

    def _default_output_root(self) -> Path:
        getter = getattr(self.engine_module, "default_download_dir", None)
        if not callable(getter):
            raise GalleryDlExecutorError("本机下载目录不可用。")
        return Path(getter())

    def submit(self, source_url: str, *, output_root: Path | None = None, max_files: int = MAX_GALLERY_DL_FILES) -> str:
        source = self._validator(str(source_url or ""))
        try:
            limit = int(max_files)
        except (TypeError, ValueError) as exc:
            raise GalleryDlExecutorError("gallery-dl 文件数量上限无效。") from exc
        if limit < 1 or limit > MAX_GALLERY_DL_FILES:
            raise GalleryDlExecutorError(f"gallery-dl 单任务文件数量必须在 1 到 {MAX_GALLERY_DL_FILES} 之间。")
        root = _safe_output_root(Path(output_root) if output_root is not None else self._default_output_root())
        task_id = f"gdl-{uuid.uuid4().hex[:16]}"
        task = _GalleryTask(task_id, source, root, limit, detail="等待 gallery-dl 下载线程。")
        with self._lock:
            self._tasks[task_id] = task
            self._queue.append(task_id)
            self._trim_locked()
            self._ensure_worker_locked()
        return task_id

    def _ensure_worker_locked(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._worker_loop, name="GalaxyGalleryDl", daemon=True)
        self._worker.start()

    def _next_task_locked(self) -> _GalleryTask | None:
        while self._queue:
            task = self._tasks.get(self._queue.popleft())
            if task is not None and task.state == "queued":
                return task
        return None

    def _worker_loop(self) -> None:
        while True:
            with self._lock:
                task = self._next_task_locked()
                if task is None:
                    self._worker = None
                    return
                task.state = "active"
                task.current_file = ""
                task.processed = 0
                task.downloaded = 0
                task.detail = "正在初始化托管 gallery-dl…"
                attempt = task.attempt
            try:
                task_dir = _task_directory(task.output_root, task.task_id, attempt)

                def progress(current_file: str, processed: int, downloaded: int) -> None:
                    with self._lock:
                        current = self._tasks.get(task.task_id)
                        if current is None or current.attempt != attempt or current.state != "active":
                            return
                        current.processed = max(0, int(processed))
                        current.downloaded = max(0, int(downloaded))
                        if current_file:
                            current.current_file = current_file[:180]
                        if current.cancel_event.is_set():
                            current.detail = (
                                f"正在取消 · 已处理 {current.processed} 项 · 已保存 {current.downloaded} 项；"
                                "当前网络文件结束后停止。"
                            )
                        elif current.current_file:
                            current.detail = (
                                f"当前 {current.current_file} · 已处理 {current.processed} 项 · "
                                f"已保存 {current.downloaded} 项"
                            )
                        else:
                            current.detail = f"已处理 {current.processed} 项 · 已保存 {current.downloaded} 项"

                result = self._runner(task.source_url, task_dir, task.max_files, task.cancel_event, progress)
                if not isinstance(result, GalleryDlRunResult):
                    raise GalleryDlExecutorError("gallery-dl runner 返回了无效结果。")
                with self._lock:
                    current = self._tasks.get(task.task_id)
                    if current is None or current.attempt != attempt:
                        continue
                    current.processed = max(current.processed, int(result.processed))
                    current.downloaded = max(current.downloaded, int(result.downloaded))
                    current.current_file = ""
                    if result.cancelled or current.cancel_event.is_set():
                        current.state = "cancelled"
                        current.detail = f"已取消 · 已处理 {current.processed} 项 · 已保存 {current.downloaded} 项"
                    elif result.status_code:
                        current.state = "failed"
                        current.detail = f"gallery-dl 执行失败（状态 {int(result.status_code)}）。"
                    elif current.downloaded <= 0:
                        current.state = "failed"
                        current.detail = "gallery-dl 没有保存任何可下载文件。"
                    else:
                        current.state = "completed"
                        suffix = " · 已达到本任务数量上限" if result.limit_reached else ""
                        current.detail = f"已完成 · 保存 {current.downloaded} 项{suffix}"
                    self._trim_locked()
            except (GalleryDlExecutorError, GalleryDlRuntimeError):
                with self._lock:
                    current = self._tasks.get(task.task_id)
                    if current is not None and current.attempt == attempt:
                        if current.cancel_event.is_set():
                            current.state = "cancelled"
                            current.detail = f"已取消 · 已处理 {current.processed} 项 · 已保存 {current.downloaded} 项"
                        else:
                            current.state = "failed"
                            current.detail = "gallery-dl 本机执行失败。请检查工具状态或来源是否受支持。"
                        current.current_file = ""
                        self._trim_locked()
            except Exception:
                with self._lock:
                    current = self._tasks.get(task.task_id)
                    if current is not None and current.attempt == attempt:
                        current.state = "failed"
                        current.current_file = ""
                        current.detail = "gallery-dl 本机执行失败。"
                        self._trim_locked()

    def cancel(self, task_id: str) -> LocalTaskActionResult:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return LocalTaskActionResult(False, False, "gallery-dl 任务不存在。")
            if task.state == "queued":
                task.cancel_event.set()
                task.state = "cancelled"
                task.detail = "任务尚未开始，已从 gallery-dl 等待队列取消。"
                return LocalTaskActionResult(True, True, "gallery-dl 等待任务已取消。")
            if task.state == "active":
                if task.cancel_event.is_set():
                    return LocalTaskActionResult(True, False, "gallery-dl 已在等待安全取消点。")
                task.cancel_event.set()
                task.detail = (
                    f"正在取消 · 已处理 {task.processed} 项 · 已保存 {task.downloaded} 项；"
                    "当前网络文件结束后停止。"
                )
                return LocalTaskActionResult(True, True, "已请求取消；当前文件结束后停止。")
            return LocalTaskActionResult(False, False, "当前 gallery-dl 任务状态不能取消。")

    def retry(self, task_id: str) -> LocalTaskActionResult:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return LocalTaskActionResult(False, False, "gallery-dl 任务不存在。")
            if task.state not in {"failed", "cancelled"}:
                return LocalTaskActionResult(False, False, "只有失败或已取消的 gallery-dl 任务可以重试。")
            task.attempt += 1
            task.state = "queued"
            task.processed = 0
            task.downloaded = 0
            task.current_file = ""
            task.detail = f"等待重试 · 第 {task.attempt} 次尝试；之前已保存的文件保持不变。"
            task.cancel_event = threading.Event()
            self._queue.append(task.task_id)
            self._ensure_worker_locked()
            return LocalTaskActionResult(True, True, "gallery-dl 任务已按原参数重新排队。")

    def action(self, task_id: str, action: str) -> LocalTaskActionResult:
        if action == "cancel":
            return self.cancel(task_id)
        if action == "retry":
            return self.retry(task_id)
        return LocalTaskActionResult(False, False, "不支持这个 gallery-dl 任务操作。")

    def snapshots(self) -> tuple[LocalTaskSnapshot, ...]:
        with self._lock:
            tasks = tuple(self._tasks.values())
        rows: list[LocalTaskSnapshot] = []
        for task in tasks:
            host = (urlparse(task.source_url).hostname or "来源").lower()[:120]
            title = f"Gallery · {host}"
            actions: tuple[str, ...] = ()
            failure_label = ""
            advice = ""
            if task.state == "queued":
                actions = ("cancel",)
                advice = "等待同一 gallery-dl 执行器中的前序任务；不会读取系统或用户 gallery-dl 配置。"
            elif task.state == "active":
                if not task.cancel_event.is_set():
                    actions = ("cancel",)
                advice = (
                    "取消在文件边界生效；正在传输的当前文件不会被伪装成瞬时中止。"
                    if not task.cancel_event.is_set()
                    else "取消请求已记录；当前网络文件完成或失败后停止。"
                )
            elif task.state in {"failed", "cancelled"}:
                actions = ("retry",)
                failure_label = "gallery-dl 失败" if task.state == "failed" else "gallery-dl 已取消"
                advice = "可按原参数重试；新尝试使用新的任务子目录，不删除之前已经保存的文件。"
            elif task.state == "completed":
                advice = "文件已保存到 Galaxy 下载目录的 gallery-dl 任务子目录。"
            rows.append(
                LocalTaskSnapshot(
                    task_id=task.task_id,
                    state=task.state,
                    title=title,
                    provider_label="gallery-dl",
                    task_type="图片 / 图库",
                    when=f"{task.processed} 项" if task.processed else "",
                    detail=task.detail,
                    advice=advice,
                    failure_label=failure_label,
                    actions=actions,
                )
            )
        return tuple(rows)

    def _trim_locked(self) -> None:
        if len(self._tasks) <= MAX_GALLERY_DL_TASKS:
            return
        for task_id in tuple(self._tasks):
            if len(self._tasks) <= MAX_GALLERY_DL_TASKS:
                break
            task = self._tasks[task_id]
            if task.state in {"completed", "failed", "cancelled"}:
                self._tasks.pop(task_id, None)


def install_gallery_dl_executor(engine_module) -> GalleryDlExecutor:
    existing = getattr(engine_module, "_galaxy_gallery_dl_executor", None)
    if isinstance(existing, GalleryDlExecutor):
        return existing
    executor = GalleryDlExecutor(engine_module)
    register_local_task_provider(
        "gallery-dl",
        label="gallery-dl",
        snapshot=executor.snapshots,
        action=executor.action,
    )
    install_local_task_provider_bridge(engine_module)
    engine_module._galaxy_gallery_dl_executor = executor
    engine_module._galaxy_gallery_dl_executor_installed = True

    window_cls = getattr(engine_module, "EngineWindow", None)
    if window_cls is not None:
        def submit_gallery_dl_task(window, source_url: str, *, max_files: int = MAX_GALLERY_DL_FILES) -> str:
            return executor.submit(source_url, max_files=max_files)

        window_cls.submit_gallery_dl_task = submit_gallery_dl_task
        window_cls._galaxy_gallery_dl_executor_installed = True
    return executor


def run_gallery_dl_executor_self_test() -> None:
    assert _display_name({"filename": "a/b\\c", "extension": "jpg"}).endswith(".jpg")
    assert MAX_GALLERY_DL_FILES == 500
