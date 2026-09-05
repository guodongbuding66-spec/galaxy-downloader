from __future__ import annotations

from typing import Any

from course_structure import CourseStructureError, enrich_course_items, list_course_sections
from headless_learning_api import HeadlessLearningApi, HeadlessLearningApiError


def _structured_payload(api: HeadlessLearningApi, result: dict[str, Any], course_id: object) -> dict[str, Any]:
    try:
        values = dict(result)
        values["items"] = enrich_course_items(api.context, values.get("items") or [])
        values["sections"] = list_course_sections(api.context, course_id)
        return values
    except CourseStructureError as exc:
        raise HeadlessLearningApiError(
            str(exc).strip() or "course structure lookup failed",
            code="LEARNING_COURSE_STRUCTURE_ERROR",
        ) from exc


def install_headless_learning_structure() -> None:
    """Add Section/Lecture metadata to existing Learning read responses."""

    current_course_detail = HeadlessLearningApi.course_detail
    if getattr(current_course_detail, "_galaxy_structured_learning", False):
        return
    original_course_detail = current_course_detail
    original_items = HeadlessLearningApi.items

    def structured_course_detail(self, course_id: object, *, item_limit: object = 500) -> dict[str, Any]:
        result = original_course_detail(self, course_id, item_limit=item_limit)
        return _structured_payload(self, result, result["course"]["id"])

    def structured_items(self, course_id: object, *, limit: object = 500) -> dict[str, Any]:
        result = original_items(self, course_id, limit=limit)
        return _structured_payload(self, result, result["courseId"])

    structured_course_detail._galaxy_structured_learning = True  # type: ignore[attr-defined]
    structured_items._galaxy_structured_learning = True  # type: ignore[attr-defined]
    HeadlessLearningApi.course_detail = structured_course_detail
    HeadlessLearningApi.items = structured_items
