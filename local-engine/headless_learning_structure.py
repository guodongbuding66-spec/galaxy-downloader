from __future__ import annotations

from typing import Any

from course_attachment_files import CourseAttachmentFileError, enrich_course_attachment_files
from course_attachments import CourseAttachmentError, enrich_course_item_attachments
from course_structure import CourseStructureError, enrich_course_items, list_course_sections
from course_subtitles import CourseSubtitleError, enrich_course_item_subtitles
from headless_learning_api import HeadlessLearningApi, HeadlessLearningApiError


def _positive_position(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _ordered_rows(rows: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        item
        for _index, item in sorted(
            rows,
            key=lambda pair: (
                0 if _positive_position(pair[1].get("providerPosition")) else 1,
                _positive_position(pair[1].get("providerPosition")) or pair[0],
                pair[0],
            ),
        )
    ]


def _with_navigation(
    items: list[dict[str, Any]],
    sections: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    values = [dict(item) for item in items]
    section_values = [dict(section) for section in sections]
    structured = bool(section_values) or any(
        str(item.get("sectionId") or "").strip()
        or _positive_position(item.get("providerPosition"))
        for item in values
    )
    if not structured:
        return values, section_values

    section_ids = [str(section.get("id") or "").strip() for section in section_values]
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {
        section_id: [] for section_id in section_ids if section_id
    }
    unsectioned: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(values):
        section_id = str(item.get("sectionId") or "").strip()
        if section_id and section_id in grouped:
            grouped[section_id].append((index, item))
        else:
            unsectioned.append((index, item))

    ordered_items: list[dict[str, Any]] = []
    for section_index, section in enumerate(section_values):
        section_id = str(section.get("id") or "").strip()
        rows = _ordered_rows(grouped.get(section_id, []))
        section["itemCount"] = len(rows)
        section["previousSectionId"] = (
            str(section_values[section_index - 1].get("id") or "") if section_index > 0 else ""
        )
        section["nextSectionId"] = (
            str(section_values[section_index + 1].get("id") or "")
            if section_index + 1 < len(section_values)
            else ""
        )
        for item_index, item in enumerate(rows):
            item["sectionItemIndex"] = item_index + 1
            item["sectionItemCount"] = len(rows)
            item["previousSectionItemId"] = (
                str(rows[item_index - 1].get("id") or "") if item_index > 0 else ""
            )
            item["nextSectionItemId"] = (
                str(rows[item_index + 1].get("id") or "") if item_index + 1 < len(rows) else ""
            )
        ordered_items.extend(rows)

    ordered_items.extend(_ordered_rows(unsectioned))
    ordered_ids = [str(item.get("id") or "").strip() for item in ordered_items]
    navigation: dict[str, tuple[str, str]] = {}
    for index, item_id in enumerate(ordered_ids):
        if not item_id:
            continue
        previous_item = ordered_ids[index - 1] if index > 0 else ""
        next_item = ordered_ids[index + 1] if index + 1 < len(ordered_ids) else ""
        navigation[item_id] = (previous_item, next_item)

    for item in values:
        item_id = str(item.get("id") or "").strip()
        if item_id not in navigation:
            continue
        previous_item, next_item = navigation[item_id]
        item["previousItemId"] = previous_item
        item["nextItemId"] = next_item
    return values, section_values


def _structured_payload(api: HeadlessLearningApi, result: dict[str, Any], course_id: object) -> dict[str, Any]:
    try:
        values = dict(result)
        items = enrich_course_items(api.context, values.get("items") or [])
        items = enrich_course_item_subtitles(api.context, items)
        items = enrich_course_item_attachments(api.context, items)
        items = enrich_course_attachment_files(api.context, items)
        sections = list_course_sections(api.context, course_id)
        items, sections = _with_navigation(items, sections)
        values["items"] = items
        values["sections"] = sections
        return values
    except (
        CourseAttachmentError,
        CourseAttachmentFileError,
        CourseStructureError,
        CourseSubtitleError,
    ) as exc:
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
