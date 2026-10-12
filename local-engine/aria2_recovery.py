from __future__ import annotations

"""Restart-safe persistence for Galaxy aria2/Torrent sessions.

aria2 records share the existing ``state/resume-jobs.json`` file used by the
media downloader. The extension is deliberately additive: legacy records still
use the original ResumeStateStore validation and serialization paths, while
provider="aria2" records carry only the fields needed to restore an interrupted
session. Full Magnet/Torrent sources never leave the local state file.
"""

import os
import threading
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from aria2_source_policy import Aria2Source, Aria2SourceError, require_torrent_source
from aria2_transfer import (
    Aria2TransferError,
    Aria2TransferOptions,
    Aria2TransferSession,
    Aria2TransferSnapshot,
    normalize_aria2_gid,
)
from pause_resume_policy import ResumeStateStore, _bounded_progress, _bounded_text, _utc_now
from transfer_preferences import normalize_aria2_connections

_PROVIDER = "aria2"
_ACTIVE_STATES = frozenset({"queued", "running", "retrying", "pausing", "cancelling"})
_CONTEXT_LOCK = threading.RLock()
_STORE_PATCHED = False


@dataclass
class _RecoveryContext:
    engine_module: Any
    store: ResumeStateStore
    executable_resolver: Callable[[Any], Path | None]


_CONTEXTS: dict[int, _RecoveryContext] = {}
_SESSIONS: dict[str, "RecoverableAria2TransferSession"] = {}
_SESSION_CONTEXT: dict[str, int] = {}


def _clean_resume_id(value: object) -> str:
    """Keep persisted IDs compatible with Bridge v5's alphanumeric boundary."""
    job_id = _bounded_text(value, 96)
    return job_id if job_id and job_id.isalnum() else ""


def _new_resume_id() -> str:
    return f"aria2resume{uuid.uuid4().hex}"


def _new_aria2_gid() -> str:
    """Return a non-zero 64-bit aria2 GID encoded as exactly 16 hex chars."""
    while True:
        gid = uuid.uuid4().hex[:16].lower()
        if gid != "0000000000000000":
            return gid


def _clean_aria2_gid(value: object) -> str:
    try:
        return normalize_aria2_gid(value)
    except Aria2TransferError:
        return ""


def _validated_recovery_source(engine_module, classified: Aria2Source) -> Aria2Source | None:
    """Re-apply Galaxy's public URL/SSRF boundary before restoring remote torrents."""
    if classified.kind != "torrent_url":
        return classified
    validator = getattr(engine_module, "_validated_source_url", None)
    if not callable(validator):
        return None
    try:
        normalized = str(validator(classified.source))
        validated = require_torrent_source(normalized)
    except Exception:  # noqa: BLE001 - persisted input must fail closed
        return None
    return validated if validated.kind == "torrent_url" else None


def _source_host(source: str, source_kind: str) -> str:
    if source_kind != "torrent_url":
        return ""
    try:
        return (urlsplit(source).hostname or "").lower()[:160]
    except ValueError:
        return ""


def _source_label(source: str, source_kind: str) -> str:
    if source_kind == "magnet":
        return "Magnet 下载"
    if source_kind == "torrent_url":
        try:
            name = Path(urlsplit(source).path).name.strip()
        except ValueError:
            name = ""
        return name[:180] or "Torrent 下载"
    name = Path(source).name.strip()
    return name[:180] or "Torrent 下载"


def _safe_destination(engine_module, value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    raw = Path(text).expanduser()
    if raw.exists() and raw.is_symlink():
        return None
    try:
        destination = raw.resolve(strict=False)
        root = Path(engine_module.default_download_dir()).resolve(strict=False)
        destination.relative_to(root)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return destination


def _clean_aria2_record(store: ResumeStateStore, value: dict[str, Any]) -> dict[str, Any] | None:
    job_id = _clean_resume_id(value.get("id"))
    state = str(value.get("state") or "").strip().lower()
    if not job_id or state not in {"running", "pausing", "paused", "interrupted"}:
        return None
    try:
        classified = require_torrent_source(value.get("source"))
    except Aria2SourceError:
        return None
    declared_kind = str(value.get("sourceKind") or value.get("source_kind") or "").strip().lower()
    if declared_kind and declared_kind != classified.kind:
        return None
    destination = _safe_destination(store.engine_module, value.get("destination"))
    if destination is None:
        return None
    raw_gid = _bounded_text(value.get("aria2Gid"), 128)
    aria2_gid = _clean_aria2_gid(raw_gid)
    if raw_gid and not aria2_gid:
        return None
    created_at = _bounded_text(value.get("createdAt"), 40) or _utc_now()
    updated_at = _bounded_text(value.get("updatedAt"), 40) or created_at
    return {
        "id": job_id,
        "state": state,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "provider": _PROVIDER,
        "source": classified.source,
        "sourceKind": classified.kind,
        "sourceHost": _source_host(classified.source, classified.kind),
        "destination": str(destination),
        "lifecycle": _bounded_text(value.get("lifecycle"), 32) or state,
        "aria2Gid": aria2_gid,
        "connections": normalize_aria2_connections(value.get("connections")),
        "label": _bounded_text(value.get("label"), 180) or _source_label(classified.source, classified.kind),
        "videoQuality": "",
        "batchId": None,
        "batchIndex": 0,
        "batchSize": 0,
        "progress": _bounded_progress(value.get("progress")),
        "downloaded": _bounded_text(value.get("downloaded"), 80),
        "resumeMode": "continue",
        "queueWasPaused": False,
    }


def _install_resume_store_extension() -> None:
    global _STORE_PATCHED
    with _CONTEXT_LOCK:
        if _STORE_PATCHED:
            return
        original_clean = ResumeStateStore._clean_record
        original_public = ResumeStateStore.public_records

        def clean_record(store: ResumeStateStore, value: object):
            if isinstance(value, dict) and str(value.get("provider") or "").strip().lower() == _PROVIDER:
                return _clean_aria2_record(store, value)
            return original_clean(store, value)

        def public_records(store: ResumeStateStore) -> list[dict[str, Any]]:
            public = original_public(store)
            full = {record["id"]: record for record in store.records()}
            for item in public:
                record = full.get(str(item.get("id") or ""))
                if record and record.get("provider") == _PROVIDER:
                    item["provider"] = _PROVIDER
                    item["sourceKind"] = str(record.get("sourceKind") or "")
            return public

        ResumeStateStore._clean_record = clean_record
        ResumeStateStore.public_records = public_records
        _STORE_PATCHED = True


class RecoverableAria2TransferSession(Aria2TransferSession):
    """Aria2 session with a persistence observer independent of the UI listener."""

    def __init__(
        self,
        *args,
        executable_resolver: Callable[[], Path | None] | None = None,
        **kwargs,
    ) -> None:
        self._recovery_observers: list[Callable[[Aria2TransferSnapshot], None]] = []
        self._executable_resolver = executable_resolver
        super().__init__(*args, **kwargs)

    def add_recovery_observer(
        self,
        observer: Callable[[Aria2TransferSnapshot], None],
        *,
        emit: bool = True,
    ) -> None:
        if observer not in self._recovery_observers:
            self._recovery_observers.append(observer)
        if emit:
            try:
                observer(self.snapshot())
            except Exception:
                pass

    def _emit(self) -> None:
        super()._emit()
        snapshot = self.snapshot()
        for observer in tuple(self._recovery_observers):
            try:
                observer(snapshot)
            except Exception:
                pass

    def restore_interrupted(self) -> None:
        with self._lock:
            self._pause_event.clear()
            self._stop_event.clear()
            self._terminal_event.clear()
            self._state = "paused"
            self._error = ""
            self._returncode = None

    def _refresh_executable(self) -> bool:
        resolver = self._executable_resolver
        if resolver is None:
            return True
        try:
            executable = resolver()
        except Exception:
            executable = None
        if executable is not None:
            self.executable = Path(executable)
            return True
        with self._lock:
            self._error = "未检测到 aria2c；请先在 Galaxy 工具目录安装/配置 aria2c，然后重试此任务。"
            self._state = "failed"
            self._returncode = 127
            self._terminal_event.set()
        self._emit()
        return False

    def start(self):
        if not self._refresh_executable():
            return self
        return super().start()

    def resume(self) -> bool:
        if self.state != "paused":
            return False
        if not self._refresh_executable():
            return False
        return super().resume()

    def retry(self) -> bool:
        if self.state != "failed":
            return False
        if not self._refresh_executable():
            return False
        return super().retry()

    def pause(self) -> bool:
        with self._lock:
            if self._state == "queued":
                self._pause_event.set()
                self._state = "pausing"
                queued = True
            else:
                queued = False
        if queued:
            self._emit()
            self._terminate_process()
            return True
        return super().pause()


def _record_state(snapshot: Aria2TransferSnapshot) -> str | None:
    if snapshot.state in {"completed", "cancelled"}:
        return None
    if snapshot.state == "paused":
        return "paused"
    if snapshot.state == "pausing":
        return "pausing"
    if snapshot.state == "failed":
        if snapshot.returncode == 127:
            return "interrupted"
        return None
    if snapshot.state in {"queued", "running", "retrying", "cancelling"}:
        return "running"
    return "interrupted"


def _attach_session(
    context: _RecoveryContext,
    session: RecoverableAria2TransferSession,
    source_kind: str,
    *,
    resume_id: str | None = None,
    emit: bool = True,
) -> str:
    record_id = _clean_resume_id(resume_id) if resume_id is not None else _new_resume_id()
    if not record_id:
        raise Aria2SourceError("aria2 恢复任务 ID 无效")
    source = str(session.options.source)
    destination = str(session.options.destination)
    created_at = _utc_now()

    def persist(snapshot: Aria2TransferSnapshot) -> None:
        state = _record_state(snapshot)
        if state is None:
            context.store.remove(record_id)
            with _CONTEXT_LOCK:
                _SESSIONS.pop(record_id, None)
                _SESSION_CONTEXT.pop(record_id, None)
            return
        previous = context.store.get(record_id) or {}
        record = {
            "id": record_id,
            "state": state,
            "createdAt": previous.get("createdAt") or created_at,
            "updatedAt": _utc_now(),
            "provider": _PROVIDER,
            "source": source,
            "sourceKind": source_kind,
            "destination": destination,
            "lifecycle": snapshot.state,
            "aria2Gid": session.options.aria2_gid,
            "connections": int(session.options.connections),
            "label": previous.get("label") or _source_label(source, source_kind),
            "progress": float(snapshot.progress.percent),
            "downloaded": previous.get("downloaded") or "",
            "resumeMode": "continue",
            "queueWasPaused": False,
        }
        context.store.upsert(record)

    session.add_recovery_observer(persist, emit=emit)
    with _CONTEXT_LOCK:
        _SESSIONS[record_id] = session
        _SESSION_CONTEXT[record_id] = id(context.engine_module)
    return record_id


def create_recoverable_aria2_session(
    engine_module,
    executable: Path,
    options: Aria2TransferOptions,
    *,
    source_kind: str,
    on_update: Callable[[Aria2TransferSnapshot], None] | None = None,
    max_retry_delay_seconds: float = 1.0,
) -> RecoverableAria2TransferSession:
    with _CONTEXT_LOCK:
        context = _CONTEXTS.get(id(engine_module))
    resolver = None
    if context is not None:
        resolver = lambda: context.executable_resolver(engine_module)
    if not options.aria2_gid:
        options = replace(options, aria2_gid=_new_aria2_gid())
    session = RecoverableAria2TransferSession(
        Path(executable),
        options,
        on_update=on_update,
        retry_base_seconds=max_retry_delay_seconds,
        executable_resolver=resolver,
    )
    if context is not None:
        classified = require_torrent_source(options.source)
        if classified.kind != source_kind:
            raise Aria2SourceError("Torrent 来源类型与已验证分类不一致")
        _attach_session(context, session, source_kind)
    return session


def _restore_record(context: _RecoveryContext, record: dict[str, Any]) -> RecoverableAria2TransferSession | None:
    try:
        classified = require_torrent_source(record.get("source"))
    except Aria2SourceError:
        context.store.remove(str(record.get("id") or ""))
        return None
    classified = _validated_recovery_source(context.engine_module, classified)
    if classified is None:
        context.store.remove(str(record.get("id") or ""))
        return None
    if classified.kind != str(record.get("sourceKind") or ""):
        context.store.remove(str(record.get("id") or ""))
        return None
    destination = _safe_destination(context.engine_module, record.get("destination"))
    if destination is None:
        context.store.remove(str(record.get("id") or ""))
        return None
    executable = context.executable_resolver(context.engine_module)
    if executable is None:
        executable = Path("aria2c.exe" if os.name == "nt" else "aria2c")
    persisted_gid = _clean_aria2_gid(record.get("aria2Gid"))
    aria2_gid = persisted_gid or _new_aria2_gid()
    session = RecoverableAria2TransferSession(
        Path(executable),
        Aria2TransferOptions(
            source=classified.source,
            destination=destination,
            connections=normalize_aria2_connections(record.get("connections")),
            seed_time_minutes=0,
            max_attempts=3,
            aria2_gid=aria2_gid,
        ),
        executable_resolver=lambda: context.executable_resolver(context.engine_module),
    )
    session.restore_interrupted()
    _attach_session(
        context,
        session,
        classified.kind,
        resume_id=str(record["id"]),
        emit=False,
    )
    if not persisted_gid:
        migrated = dict(record)
        migrated["aria2Gid"] = aria2_gid
        context.store.upsert(migrated)
    return session


def _install_window_routes(context: _RecoveryContext) -> None:
    window_cls = context.engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_aria2_recovery_routes_installed", False):
        return
    original_resume = window_cls.resume_job
    original_discard = window_cls.discard_resume_job
    original_close = window_cls.close_app

    def resume_job(window, job_id: str | None = None) -> bool:
        records = window._resume_store.records()
        selected = None
        if job_id:
            selected = next((item for item in records if item["id"] == str(job_id)), None)
        elif records:
            selected = records[0]
        if not selected or selected.get("provider") != _PROVIDER:
            return original_resume(window, job_id)
        record_id = str(selected["id"])
        with _CONTEXT_LOCK:
            session = _SESSIONS.get(record_id)
        if session is None:
            session = _restore_record(context, selected)
            if session is None:
                return False
            try:
                from aria2_task_provider import register_aria2_session
                register_aria2_session(session, title=str(selected.get("label") or ""))
            except Exception:
                pass
        if session.state == "paused":
            return bool(session.resume())
        if session.state == "failed":
            return bool(session.retry())
        if session.state == "queued":
            session.start()
            return True
        return session.state in _ACTIVE_STATES

    def discard_resume_job(window, job_id: str) -> bool:
        wanted = str(job_id or "")
        record = window._resume_store.get(wanted)
        if not record or record.get("provider") != _PROVIDER:
            return original_discard(window, job_id)
        with _CONTEXT_LOCK:
            session = _SESSIONS.pop(wanted, None)
            _SESSION_CONTEXT.pop(wanted, None)
        if session is not None and session.state not in {"completed", "cancelled"}:
            try:
                session.cancel()
            except Exception:
                pass
        return window._resume_store.remove(wanted) or record is not None

    def close_app(window) -> None:
        with _CONTEXT_LOCK:
            sessions = [
                session
                for record_id, session in _SESSIONS.items()
                if _SESSION_CONTEXT.get(record_id) == id(context.engine_module)
            ]
        active = [session for session in sessions if session.state in _ACTIVE_STATES]
        if not active:
            original_close(window)
            return
        for session in active:
            try:
                session.pause()
            except Exception:
                pass
        setter = getattr(window, "set_status", None)
        if callable(setter):
            try:
                setter("Pausing", "正在保存 aria2/Torrent 断点并安全退出…")
            except Exception:
                pass

        def finish() -> None:
            if any(session.state in _ACTIVE_STATES for session in active):
                try:
                    window.after(100, finish)
                except Exception:
                    pass
                return
            original_close(window)

        try:
            window.after(100, finish)
        except Exception:
            original_close(window)

    window_cls.resume_job = resume_job
    window_cls.discard_resume_job = discard_resume_job
    window_cls.close_app = close_app
    window_cls._galaxy_aria2_recovery_routes_installed = True
    context.engine_module._galaxy_aria2_recovery_installed = True


def install_aria2_recovery(engine_module, executable_resolver: Callable[[Any], Path | None]):
    """Persist and restore aria2 sessions through the existing resume state file."""
    if getattr(engine_module, "_galaxy_aria2_recovery_installed", False):
        return engine_module.EngineWindow
    _install_resume_store_extension()
    context = _RecoveryContext(engine_module, ResumeStateStore(engine_module), executable_resolver)
    context.store.recover_after_restart()
    with _CONTEXT_LOCK:
        _CONTEXTS[id(engine_module)] = context
    _install_window_routes(context)

    for record in context.store.records():
        if record.get("provider") != _PROVIDER:
            continue
        session = _restore_record(context, record)
        if session is None:
            continue
        try:
            from aria2_task_provider import register_aria2_session
            register_aria2_session(session, title=str(record.get("label") or ""))
        except Exception:
            pass
    return engine_module.EngineWindow


def run_aria2_recovery_self_test() -> None:
    import json
    import tempfile
    from dataclasses import dataclass

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        downloads = root / "downloads"
        downloads.mkdir()

        @dataclass(frozen=True)
        class FakeJob:
            source_url: str

        class FakeWindow:
            def __init__(self, job=None) -> None:
                self.job = job
                self._resume_store = ResumeStateStore(FakeEngine)
            def resume_job(self, _job_id=None) -> bool: return False
            def discard_resume_job(self, _job_id: str) -> bool: return False
            def close_app(self) -> None: return None
            def after(self, _delay: int, callback) -> None: callback()
            def set_status(self, *_args) -> None: return None

        class FakeEngine:
            EngineWindow = FakeWindow
            @staticmethod
            def app_dir() -> Path: return root
            @staticmethod
            def default_download_dir() -> Path: return downloads
            @staticmethod
            def _validated_source_url(value: str) -> str:
                host = (urlsplit(value).hostname or "").lower()
                if host in {"localhost", "127.0.0.1", "169.254.169.254"} or host.startswith("10.") or host.startswith("192.168."):
                    raise ValueError("private URL rejected")
                return value
            @staticmethod
            def job_from_payload(payload: dict[str, Any]) -> FakeJob:
                source = str(payload.get("sourceUrl") or "")
                if not source.startswith("https://"):
                    raise ValueError("bad source")
                return FakeJob(source)

        _install_resume_store_extension()
        store = ResumeStateStore(FakeEngine)
        legacy = store.upsert({
            "id": "legacy",
            "state": "paused",
            "payload": {"sourceUrl": "https://example.com/video"},
            "progress": 12,
        })
        assert legacy is not None

        magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
        record_id = "aria2resumetest"
        stable_gid = "2089b05ecca3d829"
        assert record_id.isalnum()
        aria = store.upsert({
            "id": record_id,
            "state": "running",
            "provider": "aria2",
            "source": magnet,
            "sourceKind": "magnet",
            "destination": str(downloads / "torrents"),
            "lifecycle": "running",
            "aria2Gid": stable_gid.upper(),
            "connections": 7,
            "progress": 48,
        })
        assert aria is not None and aria["provider"] == "aria2"
        assert aria["connections"] == 7
        assert aria["aria2Gid"] == stable_gid

        assert store.upsert({
            "id": "aria2-bad-id",
            "state": "paused",
            "provider": "aria2",
            "source": magnet,
            "sourceKind": "magnet",
            "destination": str(downloads / "torrents"),
        }) is None
        assert store.upsert({
            "id": "aria2badstate",
            "state": "completed",
            "provider": "aria2",
            "source": magnet,
            "sourceKind": "magnet",
            "destination": str(downloads / "torrents"),
        }) is None
        assert store.upsert({
            "id": "aria2badkind",
            "state": "paused",
            "provider": "aria2",
            "source": magnet,
            "sourceKind": "torrent_url",
            "destination": str(downloads / "torrents"),
        }) is None
        assert store.upsert({
            "id": "aria2badgid",
            "state": "paused",
            "provider": "aria2",
            "source": magnet,
            "sourceKind": "magnet",
            "destination": str(downloads / "torrents"),
            "aria2Gid": "not-a-valid-gid",
        }) is None

        recovered = store.recover_after_restart()
        restored = next(item for item in recovered if item["id"] == record_id)
        assert restored["state"] == "interrupted"
        assert restored["sourceKind"] == "magnet"
        assert restored["connections"] == 7
        assert restored["aria2Gid"] == stable_gid
        assert any(item["id"] == "legacy" for item in recovered)
        public = next(item for item in store.public_records() if item["id"] == record_id)
        assert public["provider"] == "aria2" and public["sourceKind"] == "magnet"
        rendered = json.dumps(public)
        assert "urn:btih" not in rendered and "source" not in {key.lower() for key in public}

        generated = _new_resume_id()
        assert generated.isalnum() and len(generated) <= 96
        generated_gid = _new_aria2_gid()
        assert normalize_aria2_gid(generated_gid, allow_empty=False) == generated_gid

        context = _RecoveryContext(FakeEngine, store, lambda _engine: Path("aria2c"))
        session = _restore_record(context, restored)
        assert session is not None and session.state == "paused"
        assert session.options.connections == 7
        assert session.options.aria2_gid == stable_gid
        with _CONTEXT_LOCK:
            assert _SESSIONS.get(record_id) is session
        session.cancel()
        assert store.get(record_id) is None

        legacy_gid_id = "aria2legacygid"
        migrated = store.upsert({
            "id": legacy_gid_id,
            "state": "interrupted",
            "provider": "aria2",
            "source": magnet,
            "sourceKind": "magnet",
            "destination": str(downloads / "torrents"),
            "connections": 4,
        })
        assert migrated is not None and migrated["aria2Gid"] == ""
        migrated_session = _restore_record(context, migrated)
        assert migrated_session is not None
        assert normalize_aria2_gid(migrated_session.options.aria2_gid, allow_empty=False)
        migrated_record = store.get(legacy_gid_id)
        assert migrated_record is not None
        assert migrated_record["aria2Gid"] == migrated_session.options.aria2_gid
        migrated_session.cancel()

        unsafe_id = "aria2unsafeurl"
        unsafe = store.upsert({
            "id": unsafe_id,
            "state": "interrupted",
            "provider": "aria2",
            "source": "https://127.0.0.1/private.torrent",
            "sourceKind": "torrent_url",
            "destination": str(downloads / "torrents"),
            "aria2Gid": "0123456789abcdef",
        })
        assert unsafe is not None
        assert _restore_record(context, unsafe) is None
        assert store.get(unsafe_id) is None


if __name__ == "__main__":
    run_aria2_recovery_self_test()
    print("aria2_recovery self-test: OK")
