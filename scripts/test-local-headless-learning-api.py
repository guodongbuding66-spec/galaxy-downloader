from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiServer  # noqa: E402
from headless_learning_api import (  # noqa: E402
    HeadlessLearningApi,
    HeadlessLearningContext,
    run_headless_learning_api_self_test,
)
from headless_media_api import HeadlessMediaApi, HeadlessMediaContext  # noqa: E402
from headless_service import HeadlessRuntime  # noqa: E402
from media_library import list_media_items, sync_media_library  # noqa: E402


def _request_json(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, method=method, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=4) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _http_error_json(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    try:
        _request_json(url, method=method, payload=payload)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    raise AssertionError(f"expected HTTP error for {method} {url}")


def run() -> None:
    run_headless_learning_api_self_test()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        program = root / "program"
        for target in (downloads, state, data, program):
            target.mkdir()

        media = downloads / "HTTP Lesson.mp4"
        media.write_bytes(b"lesson")
        learning_context = HeadlessLearningContext(program, data, state, downloads)
        history = [
            {
                "state": "completed",
                "filePath": str(media),
                "fileName": media.name,
                "label": "HTTP Lesson",
                "durationSeconds": 180,
                "sourceUrl": "https://example.com/course/http-lesson",
                "finishedAt": "2026-09-04T00:00:00Z",
            }
        ]
        assert sync_media_library(learning_context, history) == 1
        media_id = list_media_items(learning_context, limit=1)[0]["id"]
        learning_api = HeadlessLearningApi(downloads, context=learning_context)

        media_context = HeadlessMediaContext(program, state, downloads)
        media_api = HeadlessMediaApi(downloads, context=media_context)
        runtime = HeadlessRuntime(downloads, max_queue_size=2)
        server = GalaxyApiServer(
            ("127.0.0.1", 0),
            runtime,
            "",
            "127.0.0.1",
            media_api,
            learning_api=learning_api,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            code, status = _request_json(base + "/v1/status")
            assert code == 200 and status["ok"] is True and status["protocol"] == 2

            code, created = _request_json(
                base + "/v1/learning/courses",
                method="POST",
                payload={"name": "HTTP Course", "provider": "generic"},
            )
            assert code == 201 and created["course"]["name"] == "HTTP Course"
            course_id = created["course"]["id"]

            code, listed = _request_json(base + "/v1/learning/courses?limit=10")
            assert code == 200 and listed["courses"][0]["id"] == course_id
            serialized = json.dumps(listed, ensure_ascii=False)
            assert "filePath" not in serialized and "managedPath" not in serialized
            assert str(downloads) not in serialized and str(state) not in serialized and str(data) not in serialized

            code, updated = _request_json(
                base + f"/v1/learning/courses/{course_id}/update",
                method="POST",
                payload={"name": "HTTP Course Updated"},
            )
            assert code == 200 and updated["course"]["name"] == "HTTP Course Updated"

            code, added = _request_json(
                base + f"/v1/learning/courses/{course_id}/items",
                method="POST",
                payload={"mediaId": media_id},
            )
            assert code == 201 and added["item"]["title"] == "HTTP Lesson"
            item_id = added["item"]["id"]
            assert "filePath" not in json.dumps(added, ensure_ascii=False)

            code, items = _request_json(base + f"/v1/learning/courses/{course_id}/items")
            assert code == 200 and items["items"][0]["id"] == item_id

            code, detail = _request_json(base + f"/v1/learning/courses/{course_id}")
            assert code == 200 and detail["course"]["id"] == course_id
            assert detail["items"][0]["id"] == item_id

            code, progress = _request_json(
                base + f"/v1/learning/items/{item_id}/progress",
                method="POST",
                payload={"progressSeconds": 45.5, "completed": False},
            )
            assert code == 200 and progress["progressSeconds"] == 45.5

            code, note = _request_json(
                base + f"/v1/learning/items/{item_id}/notes",
                method="POST",
                payload={"timestampSeconds": 44, "body": "HTTP note"},
            )
            assert code == 201 and note["note"]["body"] == "HTTP note"
            note_id = note["note"]["id"]
            code, notes = _request_json(base + f"/v1/learning/items/{item_id}/notes")
            assert code == 200 and notes["notes"][0]["id"] == note_id

            code, card = _request_json(
                base + "/v1/learning/flashcards",
                method="POST",
                payload={"courseId": course_id, "front": "Question", "back": "Answer", "tags": ["http"]},
            )
            assert code == 201 and card["flashcard"]["courseId"] == course_id
            card_id = card["flashcard"]["id"]

            code, cards = _request_json(base + f"/v1/learning/flashcards?courseId={course_id}&dueOnly=true")
            assert code == 200 and cards["flashcards"][0]["id"] == card_id and cards["dueOnly"] is True

            code, card_detail = _request_json(base + f"/v1/learning/flashcards/{card_id}")
            assert code == 200 and card_detail["flashcard"]["front"] == "Question"

            code, reviewed = _request_json(
                base + f"/v1/learning/flashcards/{card_id}/review",
                method="POST",
                payload={"rating": "good"},
            )
            assert code == 200 and reviewed["flashcard"]["repetitions"] == 1

            code, card_updated = _request_json(
                base + f"/v1/learning/flashcards/{card_id}/update",
                method="POST",
                payload={"front": "Updated Question", "tags": ["http", "updated"]},
            )
            assert code == 200 and card_updated["flashcard"]["front"] == "Updated Question"

            code, invalid_progress = _http_error_json(
                base + f"/v1/learning/items/{item_id}/progress",
                method="POST",
                payload={"progressSeconds": "nan"},
            )
            assert code == 400 and invalid_progress["code"] == "LEARNING_INVALID_REQUEST"

            missing = "00000000000000000000000000000000"
            code, missing_course = _http_error_json(base + f"/v1/learning/courses/{missing}")
            assert code == 404 and missing_course["code"] == "LEARNING_COURSE_NOT_FOUND"

            code, invalid_due = _http_error_json(base + "/v1/learning/flashcards?dueOnly=maybe")
            assert code == 400 and invalid_due["ok"] is False

            code, removed_note = _request_json(
                base + f"/v1/learning/notes/{note_id}/delete",
                method="POST",
            )
            assert code == 200 and removed_note["deleted"] is True
            code, removed_card = _request_json(
                base + f"/v1/learning/flashcards/{card_id}/delete",
                method="POST",
            )
            assert code == 200 and removed_card["deleted"] is True
            code, removed_course = _request_json(
                base + f"/v1/learning/courses/{course_id}/delete",
                method="POST",
            )
            assert code == 200 and removed_course["deleted"] is True
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()


if __name__ == "__main__":
    run()
    print("Headless Learning API self-test passed")
