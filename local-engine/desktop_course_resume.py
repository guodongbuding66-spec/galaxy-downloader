from __future__ import annotations

import webbrowser
from collections.abc import Callable
from typing import Any

from course_workspace import create_local_player
from headless_learning_resume import resolve_headless_course_resume


BrowserOpener = Callable[[str], object]


def launch_desktop_course_resume(
    learning_api,
    course_id: object,
    *,
    opener: BrowserOpener | None = None,
) -> dict[str, Any]:
    """Open the deterministic Resume target in the existing local course player.

    Resume selection remains owned by the shared Headless contract. This adapter
    only converts an actionable `resume`/`start` result into a local player launch.
    No filesystem path is returned to the caller.
    """

    resolved = resolve_headless_course_resume(learning_api, course_id)
    resume = resolved["resume"]
    state = str(resume.get("state") or "empty")
    item = resume.get("item") if isinstance(resume.get("item"), dict) else None
    if state not in {"resume", "start"} or item is None:
        return {"resume": resume, "opened": False}

    media_id = str(item.get("mediaId") or "").strip()
    if not media_id:
        return {"resume": resume, "opened": False}

    start_seconds = float(resume.get("progressSeconds") or 0) if state == "resume" else 0.0
    page = create_local_player(
        learning_api.context,
        media_id,
        start_seconds=max(0.0, start_seconds),
    )
    target_uri = page.resolve().as_uri()
    open_target = opener or webbrowser.open_new_tab
    opened = bool(open_target(target_uri))
    return {"resume": resume, "opened": opened}
