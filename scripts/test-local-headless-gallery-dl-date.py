#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
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
)
from local_task_provider import LocalTaskActionResult, LocalTaskSnapshot  # noqa: E402


class FakeExecutor:
    def __init__(self) -> None:
        self.tasks: dict[str, str] = {}
        self.counter = 0
        self.last_source = ""
        self.last_kwargs: dict[str, object] = {}

    def submit(self, source_url: str, **kwargs: object) -> str:
        self.counter += 1
        task_id = f"gdl-{self.counter:016x}"
        self.last_source = source_url
        self.last_kwargs = dict(kwargs)
        self.tasks[task_id] = "queued"
        return task_id

    def snapshots(self):  # noqa: ANN201
        rows = []
        for task_id, state in self.tasks.items():
            actions = ("cancel",) if state in {"queued", "active"} else ()
            rows.append(
                LocalTaskSnapshot(
                    task_id=task_id,
                    state=state,
                    title="Gallery · 1.1.1.1",
                    provider_label="gallery-dl",
                    task_type="图片 / 图库",
                    when="",
                    detail="",
                    advice="managed only",
                    actions=actions,
                )
            )
        return tuple(rows)

    def action(self, task_id: str, action: str) -> LocalTaskActionResult:
        if task_id not in self.tasks:
            return LocalTaskActionResult(False, False, "missing")
        if action == "cancel" and self.tasks[task_id] in {"queued", "active"}:
            self.tasks[task_id] = "cancelled"
            return LocalTaskActionResult(True, True, "cancelled")
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


def request_json(
    port: int,
    method: str,
    path: str,
    *,
    token: str,
    payload: object | None = None,
):  # noqa: ANN201
    headers = {"Host": f"127.0.0.1:{port}", "Authorization": f"Bearer {token}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def expect_api_error(callback, *, status: int = 400, code: str = "GALLERY_DL_INVALID_REQUEST") -> None:  # noqa: ANN001
    try:
        callback()
    except HeadlessGalleryDlApiError as exc:
        assert (exc.status, exc.code) == (status, code), (exc.status, exc.code, str(exc))
    else:
        raise AssertionError(f"expected {code}")


def build_fake_api(root: Path) -> tuple[HeadlessGalleryDlApi, FakeExecutor]:
    executor = FakeExecutor()
    api = HeadlessGalleryDlApi(
        root / "downloads",
        tools_root=root / "tools",
        state_root=root / "trusted-state",
        executor=executor,  # type: ignore[arg-type]
        tool_probe=lambda: (True, "1.32.0-test"),
    )
    return api, executor


def test_direct_api_contract(root: Path) -> None:
    api, executor = build_fake_api(root)
    status = api.status()
    assert status["dateFilterSupported"] is True
    assert status["archiveSupported"] is True
    assert str(root) not in json.dumps(status)

    created = api.submit(
        {
            "sourceUrl": "https://1.1.1.1/gallery",
            "maxFiles": 25,
            "archiveEnabled": True,
            "dateAfter": "  2026-01-01T00:00:00+08:00  ",
            "dateBefore": " 1767225600 ",
        }
    )
    assert created["job"]["state"] == "queued"
    assert executor.last_source == "https://1.1.1.1/gallery"
    assert executor.last_kwargs == {
        "output_root": root / "downloads",
        "max_files": 25,
        "archive_enabled": True,
        "date_after": "2026-01-01T00:00:00+08:00",
        "date_before": "1767225600",
    }

    api.submit({"sourceUrl": "https://1.1.1.1/plain", "archiveEnabled": False})
    assert executor.last_kwargs == {
        "output_root": root / "downloads",
        "max_files": 500,
    }

    api.submit(
        {
            "sourceUrl": "https://1.1.1.1/null-date",
            "dateAfter": None,
            "dateBefore": None,
        }
    )
    assert executor.last_kwargs == {
        "output_root": root / "downloads",
        "max_files": 500,
    }

    invalid_payloads = [
        {"dateAfter": True},
        {"dateAfter": 1767225600},
        {"dateAfter": []},
        {"dateAfter": {}},
        {"dateBefore": False},
        {"dateBefore": 1767225600},
        {"dateAfter": ""},
        {"dateAfter": "   "},
        {"dateBefore": ""},
        {"dateBefore": "x" * 65},
        {"dateAfterConfig": "2026-01-01"},
        {"dateAfterPath": str(root / "secret")},
    ]
    for extra in invalid_payloads:
        payload = {"sourceUrl": "https://1.1.1.1/gallery", **extra}
        expect_api_error(lambda payload=payload: api.submit(payload))

    api.close()


def test_real_executor_validation_maps_to_400(root: Path) -> None:
    api = HeadlessGalleryDlApi(
        root / "downloads-real",
        tools_root=root / "tools-real",
        state_root=root / "state-real",
        tool_probe=lambda: (True, "1.32.0-test"),
    )
    try:
        expect_api_error(
            lambda: api.submit(
                {"sourceUrl": "https://1.1.1.1/gallery", "dateAfter": "not-a-date"}
            )
        )
        expect_api_error(
            lambda: api.submit(
                {
                    "sourceUrl": "https://1.1.1.1/gallery",
                    "dateAfter": "2026-02-01T00:00:00Z",
                    "dateBefore": "2026-01-01T00:00:00Z",
                }
            )
        )
        expect_api_error(
            lambda: api.submit(
                {
                    "sourceUrl": "https://1.1.1.1/gallery",
                    "dateAfter": "2026-01-01T00:00:00+08:00",
                    "dateBefore": "2025-12-31T16:00:00Z",
                }
            )
        )
        assert str(root) not in json.dumps(api.status())
    finally:
        api.close()


def test_http_contract(root: Path) -> None:
    api, executor = build_fake_api(root)
    token = "gallery-dl-date-contract-token-123456"
    server = TestServer(("127.0.0.1", 0), api, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    real_api: HeadlessGalleryDlApi | None = None
    try:
        code, body = request_json(port, "GET", "/v1/gallery-dl/status", token=token)
        assert code == 200 and body["ok"] is True
        assert body["dateFilterSupported"] is True

        code, body = request_json(
            port,
            "POST",
            "/v1/gallery-dl/jobs",
            token=token,
            payload={
                "sourceUrl": "https://1.1.1.1/gallery",
                "maxFiles": 9,
                "archiveEnabled": True,
                "dateAfter": " 2026-01-01 ",
                "dateBefore": " 2026-03-01 ",
            },
        )
        assert code == 201 and body["ok"] is True
        assert executor.last_kwargs == {
            "output_root": root / "downloads",
            "max_files": 9,
            "archive_enabled": True,
            "date_after": "2026-01-01",
            "date_before": "2026-03-01",
        }

        for bad_payload in (
            {"dateAfter": 1767225600},
            {"dateBefore": False},
            {"dateAfter": "   "},
            {"dateBefore": "x" * 65},
            {"dateConfig": {"after": "2026-01-01"}},
        ):
            code, body = request_json(
                port,
                "POST",
                "/v1/gallery-dl/jobs",
                token=token,
                payload={"sourceUrl": "https://1.1.1.1/gallery", **bad_payload},
            )
            assert code == 400 and body["code"] == "GALLERY_DL_INVALID_REQUEST"
            assert str(root) not in json.dumps(body)

        real_api = HeadlessGalleryDlApi(
            root / "downloads-http-real",
            tools_root=root / "tools-http-real",
            state_root=root / "state-http-real",
            tool_probe=lambda: (True, "1.32.0-test"),
        )
        original_api = server.gallery_dl_api
        server.gallery_dl_api = real_api
        try:
            code, body = request_json(
                port,
                "POST",
                "/v1/gallery-dl/jobs",
                token=token,
                payload={"sourceUrl": "https://1.1.1.1/gallery", "dateAfter": "invalid-date"},
            )
            assert code == 400 and body["code"] == "GALLERY_DL_INVALID_REQUEST"
            assert str(root) not in json.dumps(body)

            code, body = request_json(
                port,
                "POST",
                "/v1/gallery-dl/jobs",
                token=token,
                payload={
                    "sourceUrl": "https://1.1.1.1/gallery",
                    "dateAfter": "2026-04-01",
                    "dateBefore": "2026-03-01",
                },
            )
            assert code == 400 and body["code"] == "GALLERY_DL_INVALID_REQUEST"
            assert str(root) not in json.dumps(body)
        finally:
            server.gallery_dl_api = original_api
    finally:
        if real_api is not None:
            real_api.close()
        api.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def run_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        test_direct_api_contract(root)
        test_real_executor_validation_maps_to_400(root)
        test_http_contract(root)


if __name__ == "__main__":
    run_test()
    print("Headless gallery-dl Date API tests passed")
