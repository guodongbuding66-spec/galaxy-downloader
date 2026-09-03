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
from headless_media_api import HeadlessMediaApi, HeadlessMediaContext  # noqa: E402
from headless_reader_api import (  # noqa: E402
    HeadlessReaderApi,
    HeadlessReaderContext,
    run_headless_reader_api_self_test,
)
from headless_service import HeadlessRuntime  # noqa: E402
from reader_workspace import import_book  # noqa: E402


def _request_json(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, method=method, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=4) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def run() -> None:
    run_headless_reader_api_self_test()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        program = root / "program"
        source = root / "source"
        for target in (downloads, state, data, program, source):
            target.mkdir()

        reader_context = HeadlessReaderContext(program, data, state)
        text = source / "HTTP Reader.txt"
        text.write_text("Headless Reader API searchable sentence", encoding="utf-8")
        imported = import_book(reader_context, text, title="HTTP Reader")
        reader_api = HeadlessReaderApi(context=reader_context)

        media_context = HeadlessMediaContext(program, state, downloads)
        media_api = HeadlessMediaApi(downloads, context=media_context)
        runtime = HeadlessRuntime(downloads, max_queue_size=2)
        server = GalaxyApiServer(
            ("127.0.0.1", 0),
            runtime,
            "",
            "127.0.0.1",
            media_api,
            reader_api=reader_api,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            code, status = _request_json(base + "/v1/status")
            assert code == 200 and status["ok"] is True and status["protocol"] == 2

            code, listed = _request_json(base + "/v1/reader/books?limit=10")
            assert code == 200 and listed["books"][0]["id"] == imported["id"]
            serialized = json.dumps(listed, ensure_ascii=False)
            assert "managedPath" not in serialized and "filePath" not in serialized
            assert str(data) not in serialized and str(source) not in serialized

            code, detail = _request_json(base + f"/v1/reader/books/{imported['id']}")
            assert code == 200 and detail["book"]["title"] == "HTTP Reader"

            code, searched = _request_json(base + "/v1/reader/search?q=searchable")
            assert code == 200 and searched["results"][0]["bookId"] == imported["id"]

            code, progress = _request_json(
                base + f"/v1/reader/books/{imported['id']}/progress",
                method="POST",
                payload={"progressPercent": 37.25, "locator": "line:1"},
            )
            assert code == 200 and progress["book"]["progressPercent"] == 37.25

            code, settings = _request_json(
                base + f"/v1/reader/books/{imported['id']}/settings",
                method="POST",
                payload={"fontSize": 24, "theme": "dark", "focusMode": True},
            )
            assert code == 200 and settings["settings"]["fontSize"] == 24

            code, bookmark = _request_json(
                base + f"/v1/reader/books/{imported['id']}/bookmarks",
                method="POST",
                payload={"locator": "line:1", "label": "Start"},
            )
            assert code == 201 and bookmark["bookmark"]["label"] == "Start"
            bookmark_id = bookmark["bookmark"]["id"]
            code, bookmarks = _request_json(base + f"/v1/reader/books/{imported['id']}/bookmarks")
            assert code == 200 and bookmarks["bookmarks"][0]["id"] == bookmark_id

            code, annotation = _request_json(
                base + f"/v1/reader/books/{imported['id']}/annotations",
                method="POST",
                payload={
                    "locator": "line:1",
                    "kind": "highlight",
                    "selectedText": "searchable sentence",
                    "note": "API note",
                },
            )
            assert code == 201 and annotation["annotation"]["note"] == "API note"
            annotation_id = annotation["annotation"]["id"]
            code, annotations = _request_json(base + f"/v1/reader/books/{imported['id']}/annotations")
            assert code == 200 and annotations["annotations"][0]["id"] == annotation_id

            code, removed_bookmark = _request_json(
                base + f"/v1/reader/bookmarks/{bookmark_id}/delete",
                method="POST",
            )
            assert code == 200 and removed_bookmark["deleted"] is True
            code, removed_annotation = _request_json(
                base + f"/v1/reader/annotations/{annotation_id}/delete",
                method="POST",
            )
            assert code == 200 and removed_annotation["deleted"] is True

            try:
                _request_json(
                    base + f"/v1/reader/books/{imported['id']}/progress",
                    method="POST",
                    payload={"progressPercent": "nan"},
                )
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
            else:
                raise AssertionError("non-finite Reader progress did not return 400")

            try:
                _request_json(base + "/v1/reader/books/00000000000000000000000000000000")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
            else:
                raise AssertionError("missing Reader book did not return 404")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()


if __name__ == "__main__":
    run()
    print("Headless Reader API self-test passed")
