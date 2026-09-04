from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from course_workspace import (
    MAX_COURSES,
    MAX_ITEMS_PER_COURSE,
    MAX_NOTES_PER_ITEM,
    MAX_PROGRESS_SECONDS,
    CourseWorkspaceError,
    add_media_to_course,
    add_timestamp_note,
    create_course,
    delete_course,
    delete_note,
    list_course_items,
    list_courses,
    list_notes,
    rename_course,
    update_course_progress,
)
from media_library import list_media_items, sync_media_library
from platform_paths import resolve_platform_paths
from spaced_repetition import (
    SpacedRepetitionError,
    create_flashcard,
    delete_flashcard,
    get_flashcard,
    list_flashcards,
    review_flashcard,
    update_flashcard,
)

_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_MAX_FLASHCARDS_PER_RESPONSE = 2_000


class HeadlessLearningApiError(RuntimeError):
    status = 400
    code = "LEARNING_INVALID_REQUEST"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class HeadlessLearningNotFoundError(HeadlessLearningApiError):
    status = 404
    code = "LEARNING_NOT_FOUND"


class HeadlessLearningConflictError(HeadlessLearningApiError):
    status = 409
    code = "LEARNING_CONFLICT"


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def _clean_id(value: object, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(clean):
        raise HeadlessLearningApiError(f"invalid {label} id", code=f"LEARNING_INVALID_{label.upper()}_ID")
    return clean


def _safe_directory(value: Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    if raw.exists() and raw.is_symlink():
        raise HeadlessLearningApiError(f"{label} cannot be a symbolic link")
    resolved = raw.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _finite_seconds(value: object, *, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise HeadlessLearningApiError(f"{label} must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0 or parsed > MAX_PROGRESS_SECONDS:
        raise HeadlessLearningApiError(f"{label} must be between 0 and {MAX_PROGRESS_SECONDS}")
    return round(parsed, 3)


def _optional_bool(value: object, *, label: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise HeadlessLearningApiError(f"{label} must be a boolean")


def _translate_core_error(exc: Exception) -> HeadlessLearningApiError:
    detail = str(exc).strip()
    not_found = {
        "课程不存在": ("course not found", "LEARNING_COURSE_NOT_FOUND"),
        "课程条目不存在": ("course item not found", "LEARNING_ITEM_NOT_FOUND"),
        "Flashcard 不存在": ("flashcard not found", "LEARNING_FLASHCARD_NOT_FOUND"),
        "关联课程不存在": ("course not found", "LEARNING_COURSE_NOT_FOUND"),
        "媒体不存在或已离开 Galaxy 下载目录": ("media item not found", "LEARNING_MEDIA_NOT_FOUND"),
        "媒体文件不可用": ("media item not found", "LEARNING_MEDIA_NOT_FOUND"),
    }
    if detail in not_found:
        message, code = not_found[detail]
        return HeadlessLearningNotFoundError(message, code=code)
    if "数量超过安全上限" in detail:
        return HeadlessLearningConflictError("learning resource limit reached", code="LEARNING_LIMIT_REACHED")
    return HeadlessLearningApiError(detail or "learning operation failed")


@dataclass(frozen=True)
class HeadlessLearningContext:
    program_path: Path
    data_path: Path
    state_path: Path
    downloads_path: Path

    def app_dir(self) -> Path:
        return self.program_path

    def data_dir(self) -> Path:
        self.data_path.mkdir(parents=True, exist_ok=True)
        return self.data_path

    def state_dir(self) -> Path:
        self.state_path.mkdir(parents=True, exist_ok=True)
        return self.state_path

    def default_download_dir(self) -> Path:
        self.downloads_path.mkdir(parents=True, exist_ok=True)
        return self.downloads_path


def build_headless_learning_context(
    download_root: Path,
    *,
    program_dir: Path | None = None,
    data_dir: Path | None = None,
    state_dir: Path | None = None,
) -> HeadlessLearningContext:
    program = Path(program_dir or Path(__file__).resolve().parent).expanduser().resolve(strict=False)
    paths = resolve_platform_paths(program_dir=program)
    data = _safe_directory(Path(data_dir or paths.data_dir), label="learning data directory")
    state = _safe_directory(Path(state_dir or paths.state_dir), label="learning state directory")
    downloads = _safe_directory(Path(download_root), label="learning download root")
    return HeadlessLearningContext(program, data, state, downloads)


class HeadlessLearningApi:
    def __init__(
        self,
        download_root: Path,
        *,
        context: HeadlessLearningContext | None = None,
        program_dir: Path | None = None,
        data_dir: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.context = context or build_headless_learning_context(
            download_root,
            program_dir=program_dir,
            data_dir=data_dir,
            state_dir=state_dir,
        )

    def _course(self, course_id: object) -> dict[str, Any]:
        clean = _clean_id(course_id, "course")
        try:
            rows = list_courses(self.context, limit=MAX_COURSES)
        except CourseWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        for row in rows:
            if str(row.get("id") or "") == clean:
                return dict(row)
        raise HeadlessLearningNotFoundError("course not found", code="LEARNING_COURSE_NOT_FOUND")

    def courses(self, *, limit: object = 100) -> dict[str, Any]:
        safe_limit = _bounded_int(limit, 100, 1, 500)
        try:
            rows = list_courses(self.context, limit=safe_limit)
        except CourseWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"courses": rows, "limit": safe_limit}

    def course_detail(self, course_id: object, *, item_limit: object = 500) -> dict[str, Any]:
        course = self._course(course_id)
        safe_limit = _bounded_int(item_limit, 500, 1, MAX_ITEMS_PER_COURSE)
        try:
            items = list_course_items(self.context, course["id"], limit=safe_limit)
        except CourseWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"course": course, "items": items, "itemLimit": safe_limit}

    def create_course(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            course = create_course(
                self.context,
                payload.get("name"),
                payload.get("sourceUrl", ""),
                provider=payload.get("provider", "generic"),
            )
        except CourseWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"course": course}

    def update_course(self, course_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        clean = _clean_id(course_id, "course")
        if "name" not in payload:
            raise HeadlessLearningApiError("course name is required", code="LEARNING_COURSE_NAME_REQUIRED")
        try:
            rename_course(self.context, clean, payload.get("name"))
        except CourseWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"course": self._course(clean)}

    def remove_course(self, course_id: object) -> dict[str, Any]:
        clean = _clean_id(course_id, "course")
        try:
            deleted = delete_course(self.context, clean)
        except CourseWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        if not deleted:
            raise HeadlessLearningNotFoundError("course not found", code="LEARNING_COURSE_NOT_FOUND")
        return {"courseId": clean, "deleted": True}

    def items(self, course_id: object, *, limit: object = 500) -> dict[str, Any]:
        course = self._course(course_id)
        safe_limit = _bounded_int(limit, 500, 1, MAX_ITEMS_PER_COURSE)
        try:
            rows = list_course_items(self.context, course["id"], limit=safe_limit)
        except CourseWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"courseId": course["id"], "items": rows, "limit": safe_limit}

    def add_item(self, course_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        course = self._course(course_id)
        media_id = _clean_id(payload.get("mediaId"), "media")
        try:
            item_id = add_media_to_course(self.context, course["id"], media_id)
            rows = list_course_items(self.context, course["id"], limit=MAX_ITEMS_PER_COURSE)
        except CourseWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        item = next((row for row in rows if row.get("id") == item_id), None)
        if item is None:
            raise HeadlessLearningNotFoundError("course item not found", code="LEARNING_ITEM_NOT_FOUND")
        return {"courseId": course["id"], "item": item}

    def set_progress(self, item_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        clean = _clean_id(item_id, "item")
        if "progressSeconds" not in payload:
            raise HeadlessLearningApiError("progressSeconds is required", code="LEARNING_PROGRESS_REQUIRED")
        progress = _finite_seconds(payload.get("progressSeconds"), label="progressSeconds")
        completed = _optional_bool(payload.get("completed"), label="completed")
        try:
            update_course_progress(self.context, clean, progress, completed=completed)
        except CourseWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"itemId": clean, "progressSeconds": progress, "completed": completed}

    def notes(self, item_id: object, *, limit: object = 1000) -> dict[str, Any]:
        clean = _clean_id(item_id, "item")
        safe_limit = _bounded_int(limit, 1000, 1, MAX_NOTES_PER_ITEM)
        try:
            rows = list_notes(self.context, clean, limit=safe_limit)
        except CourseWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"itemId": clean, "notes": rows, "limit": safe_limit}

    def create_note(self, item_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        clean = _clean_id(item_id, "item")
        timestamp = _finite_seconds(payload.get("timestampSeconds", 0), label="timestampSeconds")
        try:
            note = add_timestamp_note(self.context, clean, timestamp, payload.get("body"))
        except CourseWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"itemId": clean, "note": note}

    def remove_note(self, note_id: object) -> dict[str, Any]:
        clean = _clean_id(note_id, "note")
        try:
            deleted = delete_note(self.context, clean)
        except CourseWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        if not deleted:
            raise HeadlessLearningNotFoundError("note not found", code="LEARNING_NOTE_NOT_FOUND")
        return {"noteId": clean, "deleted": True}

    def flashcards(
        self,
        *,
        course_id: object = "",
        due_only: object = False,
        limit: object = 500,
    ) -> dict[str, Any]:
        clean_course = str(course_id or "").strip().lower()
        if clean_course:
            clean_course = _clean_id(clean_course, "course")
            self._course(clean_course)
        if not isinstance(due_only, bool):
            raise HeadlessLearningApiError("dueOnly must be a boolean")
        safe_limit = _bounded_int(limit, 500, 1, _MAX_FLASHCARDS_PER_RESPONSE)
        try:
            rows = list_flashcards(
                self.context,
                course_id=clean_course,
                due_only=due_only,
                limit=safe_limit,
            )
        except SpacedRepetitionError as exc:
            raise _translate_core_error(exc) from exc
        return {"flashcards": rows, "courseId": clean_course, "dueOnly": due_only, "limit": safe_limit}

    def flashcard_detail(self, card_id: object) -> dict[str, Any]:
        clean = _clean_id(card_id, "flashcard")
        try:
            card = get_flashcard(self.context, clean)
        except SpacedRepetitionError as exc:
            raise _translate_core_error(exc) from exc
        return {"flashcard": card}

    def create_flashcard(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            card = create_flashcard(
                self.context,
                payload.get("front"),
                payload.get("back"),
                course_id=payload.get("courseId", ""),
                tags=payload.get("tags"),
            )
        except SpacedRepetitionError as exc:
            raise _translate_core_error(exc) from exc
        return {"flashcard": card}

    def update_flashcard(self, card_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        clean = _clean_id(card_id, "flashcard")
        if not any(key in payload for key in ("front", "back", "tags")):
            raise HeadlessLearningApiError("flashcard update payload is empty")
        try:
            card = update_flashcard(
                self.context,
                clean,
                front=payload.get("front") if "front" in payload else None,
                back=payload.get("back") if "back" in payload else None,
                tags=payload.get("tags") if "tags" in payload else None,
            )
        except SpacedRepetitionError as exc:
            raise _translate_core_error(exc) from exc
        return {"flashcard": card}

    def review_flashcard(self, card_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        clean = _clean_id(card_id, "flashcard")
        try:
            card = review_flashcard(self.context, clean, payload.get("rating"))
        except SpacedRepetitionError as exc:
            raise _translate_core_error(exc) from exc
        return {"flashcard": card}

    def remove_flashcard(self, card_id: object) -> dict[str, Any]:
        clean = _clean_id(card_id, "flashcard")
        try:
            deleted = delete_flashcard(self.context, clean)
        except SpacedRepetitionError as exc:
            raise _translate_core_error(exc) from exc
        if not deleted:
            raise HeadlessLearningNotFoundError("flashcard not found", code="LEARNING_FLASHCARD_NOT_FOUND")
        return {"flashcardId": clean, "deleted": True}


def run_headless_learning_api_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        program = root / "program"
        data = root / "data"
        state = root / "state"
        downloads = root / "downloads"
        for target in (program, data, state, downloads):
            target.mkdir()

        media = downloads / "Lesson 01.mp4"
        media.write_bytes(b"lesson")
        context = HeadlessLearningContext(program, data, state, downloads)
        history = [
            {
                "state": "completed",
                "filePath": str(media),
                "fileName": media.name,
                "label": "Lesson 01",
                "durationSeconds": 120,
                "sourceUrl": "https://example.com/lesson-01",
                "finishedAt": "2026-09-04T00:00:00Z",
            }
        ]
        assert sync_media_library(context, history) == 1
        media_id = list_media_items(context, limit=1)[0]["id"]
        api = HeadlessLearningApi(downloads, context=context)

        created = api.create_course({"name": "Galaxy Course", "provider": "generic"})["course"]
        course_id = created["id"]
        assert api.courses(limit=10)["courses"][0]["id"] == course_id
        assert api.update_course(course_id, {"name": "Galaxy Course Updated"})["course"]["name"].endswith("Updated")

        item = api.add_item(course_id, {"mediaId": media_id})["item"]
        assert item["title"] == "Lesson 01" and "filePath" not in item
        progress = api.set_progress(item["id"], {"progressSeconds": 32.5, "completed": False})
        assert progress["progressSeconds"] == 32.5

        note = api.create_note(item["id"], {"timestampSeconds": 30, "body": "Remember this"})["note"]
        assert api.notes(item["id"])["notes"][0]["id"] == note["id"]

        card = api.create_flashcard({"courseId": course_id, "front": "Q", "back": "A", "tags": ["demo"]})["flashcard"]
        assert api.flashcards(course_id=course_id)["flashcards"][0]["id"] == card["id"]
        reviewed = api.review_flashcard(card["id"], {"rating": "good"})["flashcard"]
        assert reviewed["repetitions"] == 1
        assert api.update_flashcard(card["id"], {"front": "Updated Q"})["flashcard"]["front"] == "Updated Q"

        assert api.remove_note(note["id"])["deleted"] is True
        assert api.remove_flashcard(card["id"])["deleted"] is True
        assert api.remove_course(course_id)["deleted"] is True

        try:
            api.set_progress(item["id"], {"progressSeconds": float("nan")})
        except HeadlessLearningApiError:
            pass
        else:
            raise AssertionError("non-finite learning progress was accepted")
