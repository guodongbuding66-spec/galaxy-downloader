from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_workspace import transcript_path
from prompt_library import get_prompt
from runtime_storage import state_dir as runtime_state_dir

DATABASE_FILENAME = "ai-history.sqlite3"
SCHEMA_VERSION = 1
MAX_HISTORY_RESULTS = 200
MAX_RESULT_CHARS = 1_000_000
MAX_ERROR_CHARS = 1_400
MAX_TRANSCRIPT_BYTES = 16 * 1024 * 1024
MAX_RAW_PROMPT_CHARS = 24_000
MAX_MODEL_CHARS = 160

SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"
_HISTORY_STATES = frozenset({SUCCEEDED, FAILED, CANCELLED})
_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
_TASK_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_SYMBOLIC_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_HASH_RE = re.compile(r"^[a-f0-9]{64}$")
_SECRET_DETAIL_RE = re.compile(
    r"(?i)(authorization|api[-_ ]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"
)


class AiHistoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class AiRunBinding:
    media_id: str
    transcript_hash: str
    prompt_id: str
    prompt_hash: str

    def public_payload(self) -> dict[str, str | None]:
        return {
            "mediaId": self.media_id or None,
            "transcriptHash": self.transcript_hash or None,
            "promptId": self.prompt_id or None,
            "promptHash": self.prompt_hash or None,
        }


def _db_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / DATABASE_FILENAME


def _connect(engine_module) -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    # Keep history in one durable file so the runtime-state migration ledger
    # never needs to reason about a detached WAL file.
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    _ensure_schema(connection)
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version not in {0, SCHEMA_VERSION}:
        raise AiHistoryError(f"不支持的 AI History 数据库版本：{version}")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS ai_runs (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL DEFAULT '',
            media_id TEXT NOT NULL DEFAULT '',
            provider_id TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            prompt_id TEXT NOT NULL DEFAULT '',
            prompt_hash TEXT NOT NULL DEFAULT '',
            transcript_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            error_code TEXT NOT NULL DEFAULT '',
            error_detail TEXT NOT NULL DEFAULT '',
            result_text TEXT NOT NULL DEFAULT '',
            input_chars INTEGER NOT NULL DEFAULT 0,
            output_chars INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            finished_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ai_runs_created
          ON ai_runs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ai_runs_media_created
          ON ai_runs(media_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ai_runs_provider_created
          ON ai_runs(provider_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ai_runs_status_created
          ON ai_runs(status, created_at DESC);
        """
    )
    if version == 0:
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    connection.commit()


def _clean_media_id(value: object, *, allow_empty: bool = False) -> str:
    clean = str(value or "").strip().lower()
    if not clean and allow_empty:
        return ""
    if not _MEDIA_ID_RE.fullmatch(clean):
        raise AiHistoryError("媒体条目 ID 无效")
    return clean


def _clean_task_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if clean and not _TASK_ID_RE.fullmatch(clean):
        raise AiHistoryError("AI Task ID 无效")
    return clean


def _clean_symbolic_id(value: object, *, field_name: str, allow_empty: bool = False) -> str:
    clean = str(value or "").strip().lower()
    if not clean and allow_empty:
        return ""
    if not _SYMBOLIC_ID_RE.fullmatch(clean):
        raise AiHistoryError(f"{field_name} 无效")
    return clean


def _clean_hash(value: object, *, field_name: str, allow_empty: bool = True) -> str:
    clean = str(value or "").strip().lower()
    if not clean and allow_empty:
        return ""
    if not _HASH_RE.fullmatch(clean):
        raise AiHistoryError(f"{field_name} 无效")
    return clean


def _clean_status(value: object) -> str:
    clean = str(value or "").strip().lower()
    if clean not in _HISTORY_STATES:
        raise AiHistoryError("AI History 状态无效")
    return clean


def _clean_model(value: object) -> str:
    model = " ".join(str(value or "").split()).strip()
    if len(model) > MAX_MODEL_CHARS:
        raise AiHistoryError("模型名称超过长度限制")
    return model


def _clean_error_code(value: object) -> str:
    code = str(value or "").strip().upper()
    if not code:
        return ""
    clean = re.sub(r"[^A-Z0-9_-]", "_", code)[:64]
    return clean or "AI_ERROR"


def _clean_error_detail(value: object) -> str:
    detail = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    detail = _SECRET_DETAIL_RE.sub(lambda match: match.group(1) + ": [REDACTED]", detail)
    return detail[-MAX_ERROR_CHARS:]


def _clean_nonnegative_int(value: object, *, maximum: int = 2_000_000_000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    return max(0, min(parsed, maximum))


def _safe_limit(value: object, *, default: int = 50) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, MAX_HISTORY_RESULTS))


def _safe_time(value: object, *, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(0.0, parsed)


def fingerprint_text(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def transcript_fingerprint(engine_module, media_id: object) -> str:
    clean_id = _clean_media_id(media_id)
    source = transcript_path(engine_module, clean_id)
    if not source.is_file() or source.is_symlink():
        raise AiHistoryError("字幕文件不存在或不是受支持的普通文件")
    try:
        size = source.stat().st_size
        if size <= 0:
            raise AiHistoryError("字幕文件为空")
        if size > MAX_TRANSCRIPT_BYTES:
            raise AiHistoryError("字幕文件超过 16 MB 上限")
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            while True:
                block = handle.read(64 * 1024)
                if not block:
                    break
                digest.update(block)
        return digest.hexdigest()
    except AiHistoryError:
        raise
    except OSError as exc:
        raise AiHistoryError(str(exc)) from exc


def prompt_fingerprint(engine_module, prompt_id: object) -> str:
    clean_id = _clean_symbolic_id(prompt_id, field_name="Prompt ID")
    prompt = get_prompt(engine_module, clean_id)
    if prompt is None:
        raise AiHistoryError("Prompt 不存在")
    canonical = json.dumps(
        {
            "id": prompt.id,
            "title": prompt.title,
            "instructions": prompt.instructions,
            "icon": prompt.icon,
            "builtin": bool(prompt.builtin),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return fingerprint_text(canonical)


def raw_prompt_fingerprint(instructions: object, *, extra_instruction: object = "") -> str:
    system = str(instructions or "").strip()
    extra = str(extra_instruction or "").strip()
    if not system:
        raise AiHistoryError("Raw Prompt instructions 不能为空")
    if len(system) + len(extra) > MAX_RAW_PROMPT_CHARS:
        raise AiHistoryError("Raw Prompt 超过安全长度限制")
    canonical = json.dumps(
        {"instructions": system, "extraInstruction": extra},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return fingerprint_text(canonical)


def build_ai_run_binding(
    engine_module,
    *,
    media_id: object = "",
    prompt_id: object = "",
    instructions: object = "",
    extra_instruction: object = "",
) -> AiRunBinding:
    clean_media = _clean_media_id(media_id, allow_empty=True)
    clean_prompt = _clean_symbolic_id(
        prompt_id,
        field_name="Prompt ID",
        allow_empty=True,
    )
    transcript_hash = transcript_fingerprint(engine_module, clean_media) if clean_media else ""
    if clean_prompt:
        prompt_hash = prompt_fingerprint(engine_module, clean_prompt)
    elif str(instructions or "").strip():
        prompt_hash = raw_prompt_fingerprint(
            instructions,
            extra_instruction=extra_instruction,
        )
    else:
        prompt_hash = ""
    return AiRunBinding(clean_media, transcript_hash, clean_prompt, prompt_hash)


def record_ai_run(
    engine_module,
    *,
    provider_id: object,
    model: object,
    status: object,
    binding: AiRunBinding | None = None,
    task_id: object = "",
    result_text: object = "",
    error_code: object = "",
    error_detail: object = "",
    input_chars: object = 0,
    duration_ms: object = 0,
    created_at: object = None,
    finished_at: object = None,
) -> str:
    provider = _clean_symbolic_id(provider_id, field_name="Provider ID")
    clean_status = _clean_status(status)
    clean_task = _clean_task_id(task_id)
    clean_model = _clean_model(model)
    attached = binding or AiRunBinding("", "", "", "")
    media_id = _clean_media_id(attached.media_id, allow_empty=True)
    prompt_id = _clean_symbolic_id(attached.prompt_id, field_name="Prompt ID", allow_empty=True)
    prompt_hash = _clean_hash(attached.prompt_hash, field_name="Prompt Hash")
    transcript_hash = _clean_hash(attached.transcript_hash, field_name="Transcript Hash")
    output = str(result_text or "")
    if len(output) > MAX_RESULT_CHARS:
        output = output[:MAX_RESULT_CHARS]
    if clean_status != SUCCEEDED:
        output = ""
    clean_error_code = _clean_error_code(error_code) if clean_status == FAILED else ""
    clean_error_detail = _clean_error_detail(error_detail) if clean_status == FAILED else ""
    now = time.time()
    created = _safe_time(created_at, fallback=now) if created_at is not None else now
    finished = _safe_time(finished_at, fallback=max(now, created)) if finished_at is not None else max(now, created)
    if finished < created:
        finished = created
    run_id = uuid.uuid4().hex
    with closing(_connect(engine_module)) as connection:
        connection.execute(
            """
            INSERT INTO ai_runs(
                id, task_id, media_id, provider_id, model, prompt_id,
                prompt_hash, transcript_hash, status, error_code, error_detail,
                result_text, input_chars, output_chars, duration_ms, created_at,
                finished_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                clean_task,
                media_id,
                provider,
                clean_model,
                prompt_id,
                prompt_hash,
                transcript_hash,
                clean_status,
                clean_error_code,
                clean_error_detail,
                output,
                _clean_nonnegative_int(input_chars),
                len(output),
                _clean_nonnegative_int(duration_ms),
                created,
                finished,
            ),
        )
        connection.commit()
    return run_id


def _summary_payload(row: sqlite3.Row) -> dict[str, Any]:
    result_text = str(row["result_text"])
    preview = " ".join(result_text.split())[:240]
    return {
        "id": str(row["id"]),
        "taskId": str(row["task_id"]) or None,
        "mediaId": str(row["media_id"]) or None,
        "providerId": str(row["provider_id"]),
        "model": str(row["model"]),
        "promptId": str(row["prompt_id"]) or None,
        "promptHash": str(row["prompt_hash"]) or None,
        "transcriptHash": str(row["transcript_hash"]) or None,
        "status": str(row["status"]),
        "errorCode": str(row["error_code"]) or None,
        "errorDetail": str(row["error_detail"]) or None,
        "resultPreview": preview or None,
        "inputChars": int(row["input_chars"]),
        "outputChars": int(row["output_chars"]),
        "durationMs": int(row["duration_ms"]),
        "createdAt": float(row["created_at"]),
        "finishedAt": float(row["finished_at"]),
    }


def get_ai_run(engine_module, run_id: object) -> dict[str, Any] | None:
    clean = str(run_id or "").strip().lower()
    if not _TASK_ID_RE.fullmatch(clean):
        return None
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT * FROM ai_runs WHERE id=?", (clean,)).fetchone()
    if row is None:
        return None
    payload = _summary_payload(row)
    payload["resultText"] = str(row["result_text"]) or None
    return payload


def list_ai_runs(
    engine_module,
    *,
    media_id: object = "",
    provider_id: object = "",
    status: object = "",
    limit: object = 50,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[object] = []
    if str(media_id or "").strip():
        try:
            clean_media = _clean_media_id(media_id)
        except AiHistoryError:
            return []
        clauses.append("media_id=?")
        params.append(clean_media)
    if str(provider_id or "").strip():
        try:
            provider = _clean_symbolic_id(provider_id, field_name="Provider ID")
        except AiHistoryError:
            return []
        clauses.append("provider_id=?")
        params.append(provider)
    if str(status or "").strip():
        try:
            clean_status = _clean_status(status)
        except AiHistoryError:
            return []
        clauses.append("status=?")
        params.append(clean_status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(_safe_limit(limit))
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            f"SELECT * FROM ai_runs{where} ORDER BY created_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
    return [_summary_payload(row) for row in rows]


def delete_ai_run(engine_module, run_id: object) -> bool:
    clean = str(run_id or "").strip().lower()
    if not _TASK_ID_RE.fullmatch(clean):
        return False
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute("DELETE FROM ai_runs WHERE id=?", (clean,))
        connection.commit()
        return int(cursor.rowcount) > 0


def clear_ai_history(engine_module) -> int:
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM ai_runs").fetchone()
        count = int(row["count"]) if row is not None else 0
        connection.execute("DELETE FROM ai_runs")
        connection.commit()
        return count


def run_ai_history_self_test() -> None:
    import tempfile

    from prompt_library import save_prompt

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        data = root / "data"
        state.mkdir()
        data.mkdir()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return state

            @staticmethod
            def data_dir() -> Path:
                return data

        media_id = "a" * 32
        transcript = transcript_path(Engine, media_id)
        transcript.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
            encoding="utf-8",
        )
        save_prompt(
            Engine,
            prompt_id="history-test",
            title="History Test",
            instructions="Summarize exactly.",
        )
        first_binding = build_ai_run_binding(
            Engine,
            media_id=media_id,
            prompt_id="history-test",
        )
        assert len(first_binding.transcript_hash) == 64
        assert len(first_binding.prompt_hash) == 64

        transcript.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nhello changed\n",
            encoding="utf-8",
        )
        second_binding = build_ai_run_binding(
            Engine,
            media_id=media_id,
            prompt_id="history-test",
        )
        assert first_binding.transcript_hash != second_binding.transcript_hash

        save_prompt(
            Engine,
            prompt_id="history-test",
            title="History Test",
            instructions="Summarize with a new instruction.",
        )
        third_binding = build_ai_run_binding(
            Engine,
            media_id=media_id,
            prompt_id="history-test",
        )
        assert second_binding.prompt_hash != third_binding.prompt_hash

        success_id = record_ai_run(
            Engine,
            provider_id="openai",
            model="test-model",
            status=SUCCEEDED,
            binding=third_binding,
            task_id="b" * 32,
            result_text="full result text",
            input_chars=123,
            duration_ms=456,
            created_at=10,
            finished_at=11,
        )
        listed = list_ai_runs(Engine)
        assert len(listed) == 1
        assert "resultText" not in listed[0]
        assert listed[0]["resultPreview"] == "full result text"
        assert listed[0]["transcriptHash"] == third_binding.transcript_hash
        full = get_ai_run(Engine, success_id)
        assert full is not None and full["resultText"] == "full result text"
        assert full["outputChars"] == len("full result text")

        failure_id = record_ai_run(
            Engine,
            provider_id="openai",
            model="test-model",
            status=FAILED,
            binding=third_binding,
            error_code="RATE_LIMIT",
            error_detail="Authorization=super-secret rate limited",
            created_at=12,
            finished_at=13,
        )
        failure = get_ai_run(Engine, failure_id)
        assert failure is not None
        assert failure["resultText"] is None
        assert failure["errorCode"] == "RATE_LIMIT"
        assert "super-secret" not in str(failure["errorDetail"])
        assert len(list_ai_runs(Engine, media_id=media_id)) == 2
        assert len(list_ai_runs(Engine, provider_id="openai", status=FAILED)) == 1

        raw = build_ai_run_binding(
            Engine,
            instructions="Do one thing",
            extra_instruction="Keep it short",
        )
        assert raw.media_id == "" and raw.prompt_id == "" and len(raw.prompt_hash) == 64

        assert delete_ai_run(Engine, failure_id)
        assert get_ai_run(Engine, failure_id) is None
        assert clear_ai_history(Engine) == 1
        assert list_ai_runs(Engine) == []
        assert _db_path(Engine).is_file()
