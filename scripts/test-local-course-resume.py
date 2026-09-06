from __future__ import annotations

import sys
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from course_resume import resolve_course_resume  # noqa: E402
from course_workspace import CourseWorkspaceError, _connect, create_course  # noqa: E402
from headless_learning_api import (  # noqa: E402
    HeadlessLearningApi,
    HeadlessLearningContext,
    HeadlessLearningNotFoundError,
)
from headless_learning_resume import resolve_headless_course_resume  # noqa: E402


def _item(
    item_id: str,
    media_id: str,
    position: int,
    *,
    progress: float = 0,
    completed: bool = False,
    media_type: str = "video",
    available: bool = True,
) -> dict:
    return {
        "id": item_id,
        "mediaId": media_id,
        "position": position,
        "progressSeconds": progress,
        "completed": completed,
        "title": f"Lesson {position}",
        "durationSeconds": 300.0,
        "available": available,
        "mediaType": media_type,
    }


def _insert_course_item(
    engine,
    course_id: str,
    item_id: str,
    media_id: str,
    position: int,
    *,
    progress: float = 0,
    completed: bool = False,
    updated_at: str = "2026-09-06 00:00:00",
) -> None:
    with closing(_connect(engine)) as connection:
        connection.execute(
            """
            INSERT INTO course_items(
                id, course_id, media_id, position, progress_seconds, completed, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (item_id, course_id, media_id, position, progress, 1 if completed else 0, updated_at),
        )
        connection.commit()


def run_course_resume_self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        program = root / "program"
        data = root / "data"
        state = root / "state"
        downloads = root / "downloads"
        for target in (program, data, state, downloads):
            target.mkdir()

        context = HeadlessLearningContext(program, data, state, downloads)
        api = HeadlessLearningApi(downloads, context=context)

        recent_course = create_course(context, "Recent Resume")
        first_id = "1" * 32
        second_id = "2" * 32
        third_id = "3" * 32
        first_media = "a" * 32
        second_media = "b" * 32
        third_media = "c" * 32
        _insert_course_item(
            context,
            recent_course["id"],
            first_id,
            first_media,
            1,
            progress=40,
            updated_at="2026-09-06 08:00:00",
        )
        _insert_course_item(
            context,
            recent_course["id"],
            second_id,
            second_media,
            2,
            progress=15,
            updated_at="2026-09-06 09:00:00",
        )
        _insert_course_item(
            context,
            recent_course["id"],
            third_id,
            third_media,
            3,
            completed=True,
            updated_at="2026-09-06 10:00:00",
        )
        recent_items = [
            _item(first_id, first_media, 1, progress=40),
            _item(second_id, second_media, 2, progress=15),
            _item(third_id, third_media, 3, completed=True),
        ]
        with patch("course_resume.list_course_items", return_value=recent_items):
            resume = resolve_course_resume(context, recent_course["id"])
        assert resume["state"] == "resume"
        assert resume["item"]["id"] == second_id
        assert resume["progressSeconds"] == 15

        start_course = create_course(context, "Start Resume")
        image_id = "4" * 32
        completed_id = "5" * 32
        start_id = "6" * 32
        image_media = "d" * 32
        completed_media = "e" * 32
        start_media = "f" * 32
        _insert_course_item(context, start_course["id"], image_id, image_media, 1)
        _insert_course_item(context, start_course["id"], completed_id, completed_media, 2, completed=True)
        _insert_course_item(context, start_course["id"], start_id, start_media, 3)
        start_items = [
            _item(image_id, image_media, 1, media_type="image"),
            _item(completed_id, completed_media, 2, completed=True),
            _item(start_id, start_media, 3, media_type="audio"),
        ]
        with patch("course_resume.list_course_items", return_value=start_items):
            start = resolve_course_resume(context, start_course["id"])
        assert start["state"] == "start"
        assert start["item"]["id"] == start_id
        assert start["progressSeconds"] == 0

        completed_course = create_course(context, "Completed Resume")
        done_id = "7" * 32
        done_media = "0" * 32
        _insert_course_item(context, completed_course["id"], done_id, done_media, 1, completed=True)
        with patch(
            "course_resume.list_course_items",
            return_value=[_item(done_id, done_media, 1, completed=True)],
        ):
            completed = resolve_course_resume(context, completed_course["id"])
        assert completed["state"] == "completed"
        assert completed["item"] is None
        assert completed["completed"] is True

        empty_course = create_course(context, "Empty Resume")
        missing_id = "8" * 32
        missing_media = "9" * 32
        _insert_course_item(context, empty_course["id"], missing_id, missing_media, 1, progress=20)
        with patch(
            "course_resume.list_course_items",
            return_value=[_item(missing_id, missing_media, 1, progress=20, available=False)],
        ):
            empty = resolve_course_resume(context, empty_course["id"])
        assert empty["state"] == "empty"
        assert empty["item"] is None

        try:
            resolve_course_resume(context, "f" * 32)
        except CourseWorkspaceError as exc:
            assert str(exc) == "课程不存在"
        else:
            raise AssertionError("missing course was accepted by resume resolver")

        malicious = {
            "courseId": recent_course["id"],
            "state": "resume",
            "item": {
                **_item(second_id, second_media, 2, progress=15),
                "localPath": "C:/secret/lesson.mp4",
                "filePath": "/secret/lesson.mp4",
            },
            "progressSeconds": 15,
            "completed": False,
            "reason": "test",
            "localPath": "C:/secret",
        }
        with patch("headless_learning_resume.resolve_course_resume", return_value=malicious):
            payload = resolve_headless_course_resume(api, recent_course["id"])
        assert payload["resume"]["item"]["id"] == second_id
        assert "localPath" not in payload["resume"]
        assert "localPath" not in payload["resume"]["item"]
        assert "filePath" not in payload["resume"]["item"]

        with patch(
            "headless_learning_resume.resolve_course_resume",
            side_effect=CourseWorkspaceError("课程不存在"),
        ):
            try:
                resolve_headless_course_resume(api, "f" * 32)
            except HeadlessLearningNotFoundError as exc:
                assert exc.code == "LEARNING_COURSE_NOT_FOUND"
            else:
                raise AssertionError("headless resume did not translate missing course")


if __name__ == "__main__":
    run_course_resume_self_test()
    print("Course resume core self-test passed")
