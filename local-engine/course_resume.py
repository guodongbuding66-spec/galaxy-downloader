from __future__ import annotations

from contextlib import closing
from typing import Any

from course_workspace import (
    MAX_ITEMS_PER_COURSE,
    CourseWorkspaceError,
    _clean_id,
    _connect,
    list_course_items,
)

PLAYABLE_MEDIA_TYPES = frozenset({"video", "audio"})


def _safe_resume_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "mediaId": str(item.get("mediaId") or ""),
        "position": int(item.get("position") or 0),
        "title": str(item.get("title") or ""),
        "mediaType": str(item.get("mediaType") or ""),
        "durationSeconds": float(item.get("durationSeconds") or 0),
        "available": bool(item.get("available")),
    }


def _result(
    course_id: str,
    state: str,
    *,
    item: dict[str, Any] | None = None,
    reason: str,
) -> dict[str, Any]:
    progress = float(item.get("progressSeconds") or 0) if item is not None else 0.0
    return {
        "courseId": course_id,
        "state": state,
        "item": _safe_resume_item(item) if item is not None else None,
        "progressSeconds": max(0.0, progress),
        "completed": state == "completed",
        "reason": reason,
    }


def resolve_course_resume(engine_module, course_id: object) -> dict[str, Any]:
    """Resolve one deterministic local-media target for continuing a course.

    Resolution order is intentionally stable:
    1. Most recently updated unfinished playable item with saved progress.
    2. First unfinished playable item in course position order.
    3. Completed when every currently playable item is complete.
    4. Empty when the course has no currently playable local video/audio.
    """

    course = _clean_id(course_id, "课程 ID")
    with closing(_connect(engine_module)) as connection:
        if connection.execute("SELECT 1 FROM courses WHERE id=?", (course,)).fetchone() is None:
            raise CourseWorkspaceError("课程不存在")
        started_rows = connection.execute(
            """
            SELECT id
            FROM course_items
            WHERE course_id=? AND completed=0 AND progress_seconds>0
            ORDER BY updated_at DESC, position ASC, id ASC
            """,
            (course,),
        ).fetchall()

    items = list_course_items(engine_module, course, limit=MAX_ITEMS_PER_COURSE)
    playable = [
        item
        for item in items
        if bool(item.get("available"))
        and str(item.get("mediaType") or "").strip().lower() in PLAYABLE_MEDIA_TYPES
    ]
    if not playable:
        return _result(course, "empty", reason="no playable local video or audio")

    playable_by_id = {str(item.get("id") or ""): item for item in playable}
    for row in started_rows:
        item = playable_by_id.get(str(row["id"]))
        if item is not None and not bool(item.get("completed")):
            return _result(
                course,
                "resume",
                item=item,
                reason="most recently updated unfinished media with saved progress",
            )

    for item in playable:
        if not bool(item.get("completed")):
            return _result(
                course,
                "start",
                item=item,
                reason="first unfinished playable media in course order",
            )

    return _result(course, "completed", reason="all playable local media completed")
