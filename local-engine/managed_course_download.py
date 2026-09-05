from __future__ import annotations

from contextlib import suppress
from typing import Any
from urllib.parse import unquote, urlsplit

from course_download_coordinator import CourseDownloadCoordinatorError
from course_providers import build_course_provider_plan


def build_managed_course_plan(
    source_url: object,
    *,
    provider: object = "auto",
    browser: object = "none",
    include_subtitles: object = True,
) -> dict[str, Any]:
    """Build the bounded provider plan shared by Headless HTTP and Desktop."""

    return build_course_provider_plan(
        source_url,
        provider=provider,
        browser=browser,
        include_subtitles=include_subtitles,
    )


def managed_course_name(value: object, source_url: str) -> str:
    explicit = " ".join(str(value or "").split()).strip()[:160]
    if explicit:
        return explicit
    try:
        parts = [unquote(part) for part in urlsplit(source_url).path.split("/") if part]
    except ValueError:
        parts = []
    slug = parts[-1] if parts else "Udemy Course"
    rendered = " ".join(slug.replace("-", " ").replace("_", " ").split()).strip()
    return (rendered or "Udemy Course")[:160]


def _source_identity(value: object) -> tuple[str, str, str] | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        host = str(parsed.hostname or "").strip().lower().rstrip(".")
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not host:
            return None
        path = "/" + "/".join(part for part in parsed.path.split("/") if part)
        return scheme, host, path.rstrip("/") or "/"
    except ValueError:
        return None


def validate_managed_course_binding(course: dict[str, Any], plan: dict[str, Any]) -> None:
    course_provider = str(course.get("provider") or "").strip().lower()
    provider = str(plan.get("provider") or "").strip().lower()
    if course_provider != provider:
        raise CourseDownloadCoordinatorError("existing course provider does not match course download provider")
    existing_source = _source_identity(course.get("sourceUrl"))
    requested_source = _source_identity(plan.get("sourceUrl"))
    if existing_source is not None and existing_source != requested_source:
        raise CourseDownloadCoordinatorError("existing course source does not match course download URL")


def submit_managed_course_download(
    learning_api,
    coordinator,
    plan: dict[str, Any],
    *,
    course_id: object = "",
    course_name: object = "",
) -> dict[str, Any]:
    """Bind a safe provider plan to a Course and submit it atomically.

    This core intentionally accepts no cookie/header/file-path inputs. Provider
    authentication remains constrained to the browser source already validated
    by `build_managed_course_plan`.
    """

    if learning_api is None or coordinator is None:
        raise CourseDownloadCoordinatorError("managed course downloads are unavailable")
    if not isinstance(plan, dict):
        raise CourseDownloadCoordinatorError("course provider plan is invalid")

    created_course = False
    clean_course_id = str(course_id or "").strip().lower()
    if clean_course_id:
        course = learning_api.course_detail(clean_course_id, item_limit=1)["course"]
        validate_managed_course_binding(course, plan)
    else:
        source_url = str(plan.get("sourceUrl") or "").strip()
        provider = str(plan.get("provider") or "").strip().lower()
        if not source_url or not provider:
            raise CourseDownloadCoordinatorError("course provider plan is incomplete")
        course = learning_api.create_course(
            {
                "name": managed_course_name(course_name, source_url),
                "sourceUrl": source_url,
                "provider": provider,
            }
        )["course"]
        created_course = True

    try:
        job, session = coordinator.submit(plan, course["id"])
    except Exception:
        if created_course:
            with suppress(Exception):
                learning_api.remove_course(course["id"])
        raise

    return {
        "provider": str(plan.get("provider") or "").strip().lower(),
        "course": course,
        "session": session,
        "job": job,
        "warnings": list(plan.get("warnings") or []),
    }
