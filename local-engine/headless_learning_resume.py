from __future__ import annotations

from typing import Any

from course_resume import resolve_course_resume
from course_workspace import CourseWorkspaceError
from headless_learning_api import HeadlessLearningApi, _clean_id, _translate_core_error

_SAFE_ITEM_FIELDS = (
    "id",
    "mediaId",
    "position",
    "title",
    "mediaType",
    "durationSeconds",
    "available",
)


def _safe_item(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) for key in _SAFE_ITEM_FIELDS}


def resolve_headless_course_resume(learning_api: HeadlessLearningApi, course_id: object) -> dict[str, Any]:
    """Return the stable course-resume contract without local filesystem details."""

    clean = _clean_id(course_id, "course")
    try:
        resolved = resolve_course_resume(learning_api.context, clean)
    except CourseWorkspaceError as exc:
        raise _translate_core_error(exc) from exc

    return {
        "resume": {
            "courseId": clean,
            "state": str(resolved.get("state") or "empty"),
            "item": _safe_item(resolved.get("item")),
            "progressSeconds": max(0.0, float(resolved.get("progressSeconds") or 0)),
            "completed": bool(resolved.get("completed")),
            "reason": str(resolved.get("reason") or ""),
        }
    }
