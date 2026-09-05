from __future__ import annotations

from contextlib import suppress
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

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


def managed_course_source_url(value: object) -> str:
    """Return stable Course metadata without query, fragment or credentials."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.lower()
        host = str(parsed.hostname or "").strip().lower().rstrip(".")
        if scheme not in {"http", "https"} or not host:
            return ""
        if parsed.username is not None or parsed.password is not None:
            return ""
        netloc = host
        try:
            if parsed.port:
                netloc = f"{host}:{parsed.port}"
        except ValueError:
            return ""
        return urlunsplit((scheme, netloc, parsed.path or "/", "", ""))
    except ValueError:
        return ""


def _source_identity(value: object) -> tuple[str, str, str] | None:
    clean = managed_course_source_url(value)
    if not clean:
        return None
    try:
        parsed = urlsplit(clean)
        host = str(parsed.hostname or "").strip().lower().rstrip(".")
        path = "/" + "/".join(part for part in parsed.path.split("/") if part)
        return parsed.scheme.lower(), host, path.rstrip("/") or "/"
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

    requested_source = managed_course_source_url(plan.get("sourceUrl"))
    provider = str(plan.get("provider") or "").strip().lower()
    if not requested_source or not provider:
        raise CourseDownloadCoordinatorError("course provider plan is incomplete")

    created_course = False
    clean_course_id = str(course_id or "").strip().lower()
    if clean_course_id:
        course = learning_api.course_detail(clean_course_id, item_limit=1)["course"]
        validate_managed_course_binding(course, plan)
    else:
        course = learning_api.create_course(
            {
                "name": managed_course_name(course_name, requested_source),
                "sourceUrl": requested_source,
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

    public_course = dict(course)
    public_course["sourceUrl"] = managed_course_source_url(course.get("sourceUrl")) or requested_source
    return {
        "provider": provider,
        "course": public_course,
        "session": session,
        "job": job,
        "warnings": list(plan.get("warnings") or []),
    }
