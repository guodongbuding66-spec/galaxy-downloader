from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiRequestHandler  # noqa: E402
from headless_gallery_dl_api import (  # noqa: E402
    HeadlessGalleryDlApi,
    HeadlessGalleryDlApiError,
    run_headless_gallery_dl_api_self_test,
)
from headless_gallery_dl_http import HeadlessGalleryDlHttpMixin  # noqa: E402
from local_task_provider import LocalTaskActionResult, LocalTaskSnapshot  # noqa: E402


class FakeExecutor:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, object]] = {}
        self.counter = 0
        self.last_submit: tuple[str, Path, int] | None = None

    def submit(self, source_url: str, *, output_root: Path, max_files: int) -> str:
        self.counter += 1
        task_id = f"gdl-{self.counter:016x}"
        self.last_submit = (source_url, Path(output_root), int(max_files))
        self.tasks[task_id] = {
            "state": "queued",
            "detail": "等待任务 /tmp/private/cookie.txt Authorization: Bearer abcdefghijklmnop",
            "attempt": 1,
        }
        return task_id

    def snapshots(self):  # noqa: ANN201
        rows = []
        for task_id, task in self.tasks.items():
            state = str(task["state"])
            if state in {"queued", "active"}:
                actions = ("cancel",)
            elif state in {"failed", "cancelled"}:
                actions = ("retry",)
            else:
                actions = ()
            rows.append(
                LocalTaskSnapshot(
                    task_id=task_id,
                    state=state,
                    title="Gallery · example.test",
                    provider_label="gallery-dl",
                    task_type="图片 / 图库",
                    when="1 项",
                    detail=str(task["detail"]),
                    advice="managed only",
                    actions=actions,
                )
            )
        return tuple(rows)

    def action(self, task_id: str, action: str) -> LocalTaskActionResult:
        task = self.tasks.get(task_id)
        if task is None:
            return LocalTaskActionResult(False, False, "missing")
        state = str(task["state"])
        if action == "cancel" and state in {"queued", "active"}:
            task["state"] = "cancelled"
            task["detail"] = "cancelled"
            return LocalTaskActionResult(True, True, "cancelled")
        if action == "retry" and state in {"failed", "cancelled"}:
            task["state"] = "queued"
            task["detail"] = "queued again"
            task["attempt"] = int(task["attempt"]) + 1
            return LocalTaskActionResult(True, True, "retried")
        return LocalTaskActionResult(False, False, "conflict")


class TestServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, gallery_api: HeadlessGalleryDlApi, auth_token: str):
        self.auth_token = auth_token
        self.bound_host = "127.0.0.1"
        self.gallery_dl_api = gallery_api
        self.runtime = None
        self.media_api = None
        self.transcript_api = None
        self.subscription_api = None
        self.reader_api = None
        self.learning_api = None
        self.music_api = None
        self.ai_api = None
        self.asr_api = None
        self.whisperx_api = None
        self.plugin_api = None
        self.transfer_api = None
        super().__init__(address, GalaxyApiRequestHandler)


def _request(
    port: int,
    method: str,
    path: str,
    *,
    token: str = "",
    payload: object | None = None,
) -> tuple[int, dict]:
    headers = {"Host": f"127.0.0.1:{port}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _expect_api_error(callback, *, status: int, code: str) -> None:  # noqa: ANN001
    try:
        callback()
    except HeadlessGalleryDlApiError as exc:
        assert exc.status == status
        assert exc.code == code
    else:
        raise AssertionError(f"expected {code}")


def _test_api_contract(root: Path) -> HeadlessGalleryDlApi:
    executor = FakeExecutor()
    api = HeadlessGalleryDlApi(
        root / "downloads",
        tools_root=root / "tools",
        executor=executor,  # type: ignore[arg-type]
        tool_probe=lambda: (True, "1.32.0-test"),
    )

    status = api.status()
    assert status["available"] is True
    assert status["version"] == "1.32.0-test"
    assert status["maxFilesPerJob"] == 500
    assert status["maxTrackedJobs"] == 200
    assert status["managedOnly"] is True

    created = api.submit({"sourceUrl": "https://1.1.1.1/gallery", "maxFiles": 25})
    task = created["job"]
    assert task["id"] == "gdl-0000000000000001"
    assert task["state"] == "queued"
    assert task["actions"] == ["cancel"]
    assert executor.last_submit == ("https://1.1.1.1/gallery", root / "downloads", 25)

    serialized = json.dumps(created)
    assert "/tmp/private" not in serialized
    assert "abcdefghijklmnop" not in serialized
    assert "[local path hidden]" in serialized
    assert "Bearer [redacted]" in serialized

    listing = api.jobs(limit=10)
    assert listing["count"] == 1
    assert listing["jobs"][0]["id"] == task["id"]
    assert api.job(task["id"])["job"]["provider"] == "gallery-dl"

    cancelled = api.action(task["id"], "cancel")
    assert cancelled["changed"] is True
    assert cancelled["job"]["state"] == "cancelled"
    assert cancelled["job"]["actions"] == ["retry"]

    retried = api.action(task["id"], "retry")
    assert retried["changed"] is True
    assert retried["job"]["state"] == "queued"
    _expect_api_error(
        lambda: api.action(task["id"], "retry"),
        status=409,
        code="GALLERY_DL_ACTION_CONFLICT",
    )

    _expect_api_error(
        lambda: api.submit({"sourceUrl": "file:///tmp/private"}),
        status=400,
        code="GALLERY_DL_INVALID_REQUEST",
    )
    _expect_api_error(
        lambda: api.submit({"sourceUrl": "http://127.0.0.1/private"}),
        status=400,
        code="GALLERY_DL_INVALID_REQUEST",
    )
    _expect_api_error(
        lambda: api.submit({"sourceUrl": "https://1.1.1.1/gallery", "maxFiles": True}),
        status=400,
        code="GALLERY_DL_INVALID_REQUEST",
    )
    _expect_api_error(
        lambda: api.submit({"sourceUrl": "https://1.1.1.1/gallery", "maxFiles": 501}),
        status=400,
        code="GALLERY_DL_INVALID_REQUEST",
    )
    _expect_api_error(
        lambda: api.submit({"sourceUrl": "https://1.1.1.1/gallery", "cookies": "secret"}),
        status=400,
        code="GALLERY_DL_INVALID_REQUEST",
    )
    _expect_api_error(
        lambda: api.jobs(limit=201),
        status=400,
        code="GALLERY_DL_INVALID_REQUEST",
    )
    _expect_api_error(
        lambda: api.job("../../secret"),
        status=400,
        code="GALLERY_DL_INVALID_REQUEST",
    )
    _expect_api_error(
        lambda: api.job("gdl-ffffffffffffffff"),
        status=404,
        code="GALLERY_DL_JOB_NOT_FOUND",
    )

    unavailable = HeadlessGalleryDlApi(
        root / "downloads",
        tools_root=root / "tools",
        executor=FakeExecutor(),  # type: ignore[arg-type]
        tool_probe=lambda: (False, None),
    )
    assert unavailable.status()["available"] is False
    _expect_api_error(
        lambda: unavailable.submit({"sourceUrl": "https://1.1.1.1/gallery"}),
        status=503,
        code="GALLERY_DL_UNAVAILABLE",
    )
    return api


def _test_http_contract(api: HeadlessGalleryDlApi, root: Path) -> None:
    assert HeadlessGalleryDlHttpMixin in GalaxyApiRequestHandler.__mro__
    token = "gallery-dl-headless-test-token-123456"
    server = TestServer(("127.0.0.1", 0), api, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        code, body = _request(port, "GET", "/v1/gallery-dl/status")
        assert code == 401 and body["error"] == "unauthorized"

        code, body = _request(port, "GET", f"/v1/gallery-dl/status?token={token}")
        assert code == 401 and body["error"] == "unauthorized"

        code, body = _request(port, "GET", "/v1/gallery-dl/status", token=token)
        assert code == 200 and body["ok"] is True and body["available"] is True
        assert "tools" not in json.dumps(body).lower()

        code, body = _request(
            port,
            "POST",
            "/v1/gallery-dl/jobs",
            token=token,
            payload={"sourceUrl": "https://1.1.1.1/gallery", "maxFiles": 9},
        )
        assert code == 201 and body["ok"] is True
        task_id = body["job"]["id"]
        assert task_id.startswith("gdl-")

        code, body = _request(port, "GET", f"/v1/gallery-dl/jobs/{task_id}", token=token)
        assert code == 200 and body["job"]["id"] == task_id

        code, body = _request(port, "GET", "/v1/gallery-dl/jobs?limit=2", token=token)
        assert code == 200 and body["count"] >= 1

        code, body = _request(port, "POST", f"/v1/gallery-dl/jobs/{task_id}/cancel", token=token)
        assert code == 200 and body["job"]["state"] == "cancelled"

        code, body = _request(port, "POST", f"/v1/gallery-dl/jobs/{task_id}/retry", token=token)
        assert code == 200 and body["job"]["state"] == "queued"

        code, body = _request(
            port,
            "POST",
            "/v1/gallery-dl/jobs",
            token=token,
            payload={"sourceUrl": "file:///tmp/private"},
        )
        assert code == 400 and body["code"] == "GALLERY_DL_INVALID_REQUEST"

        code, body = _request(
            port,
            "POST",
            "/v1/gallery-dl/jobs",
            token=token,
            payload={"sourceUrl": "https://1.1.1.1/gallery", "cookieFile": str(root / "secret.txt")},
        )
        assert code == 400 and body["code"] == "GALLERY_DL_INVALID_REQUEST"
        assert str(root) not in json.dumps(body)

        code, body = _request(port, "GET", "/v1/gallery-dl/jobs?limit=999", token=token)
        assert code == 400 and body["code"] == "GALLERY_DL_INVALID_REQUEST"

        class ExplodingApi:
            def status(self):  # noqa: ANN201
                raise RuntimeError(f"failure at {root / 'private' / 'tool-state.json'}")

        original = server.gallery_dl_api
        server.gallery_dl_api = ExplodingApi()
        try:
            code, body = _request(port, "GET", "/v1/gallery-dl/status", token=token)
        finally:
            server.gallery_dl_api = original
        assert code == 502
        assert body["error"] == "gallery-dl request failed"
        assert str(root) not in json.dumps(body)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def run_test() -> None:
    import tempfile

    run_headless_gallery_dl_api_self_test()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        api = _test_api_contract(root)
        _test_http_contract(api, root)


if __name__ == "__main__":
    run_test()
    print("Headless gallery-dl API tests passed")
