#!/usr/bin/env python3
from __future__ import annotations

import json
import math
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
from headless_gallery_dl_api import HeadlessGalleryDlApi, HeadlessGalleryDlApiError  # noqa: E402
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
        return tuple(
            LocalTaskSnapshot(
                task_id=task_id,
                state=state,
                title="Gallery · 1.1.1.1",
                provider_label="gallery-dl",
                task_type="图片 / 图库",
                when="",
                detail="",
                advice="managed only",
                actions=("cancel",) if state in {"queued", "active"} else (),
            )
            for task_id, state in self.tasks.items()
        )

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
) -> tuple[int, dict[str, object]]:
    headers = {
        "Host": f"127.0.0.1:{port}",
        "Authorization": f"Bearer {token}",
    }
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


def expect_invalid(callback) -> None:  # noqa: ANN001
    try:
        callback()
    except HeadlessGalleryDlApiError as exc:
        assert (exc.status, exc.code) == (400, "GALLERY_DL_INVALID_REQUEST"), (
            exc.status,
            exc.code,
            str(exc),
        )
    else:
        raise AssertionError("expected GALLERY_DL_INVALID_REQUEST")


def build_api(root: Path) -> tuple[HeadlessGalleryDlApi, FakeExecutor]:
    executor = FakeExecutor()
    api = HeadlessGalleryDlApi(
        root / "downloads",
        tools_root=root / "tools",
        state_root=root / "state",
        executor=executor,  # type: ignore[arg-type]
        tool_probe=lambda: (True, "1.32.0-test"),
    )
    return api, executor


def test_direct_rate_contract(root: Path) -> None:
    api, executor = build_api(root)
    try:
        status = api.status()
        assert status["rateLimitSupported"] is True
        assert status["rateLimitMinMiB"] == 0.1
        assert status["rateLimitMaxMiB"] == 1024.0
        assert status["rateLimitUnit"] == "MiB/s"
        assert status["archiveSupported"] is True
        assert status["dateFilterSupported"] is True
        assert status["resumeSupported"] is True
        assert str(root) not in json.dumps(status)

        api.submit({"sourceUrl": "https://1.1.1.1/plain"})
        assert executor.last_kwargs == {
            "output_root": root / "downloads",
            "max_files": 500,
        }

        for index, rate in enumerate((0.1, 1, 12.5, 1024), start=1):
            created = api.submit(
                {"sourceUrl": f"https://1.1.1.1/rate-{index}", "rateLimitMiB": rate}
            )
            assert created["job"]["state"] == "queued"
            assert executor.last_kwargs["rate_limit_mib"] == rate

        composed = api.submit(
            {
                "sourceUrl": "https://1.1.1.1/composed",
                "maxFiles": 17,
                "archiveEnabled": True,
                "resumeEnabled": True,
                "dateAfter": " 2026-01-01 ",
                "dateBefore": " 2026-03-01 ",
                "rateLimitMiB": 3.25,
            }
        )
        assert composed["job"]["state"] == "queued"
        assert executor.last_source == "https://1.1.1.1/composed"
        assert executor.last_kwargs == {
            "output_root": root / "downloads",
            "max_files": 17,
            "archive_enabled": True,
            "resume_enabled": True,
            "date_after": "2026-01-01",
            "date_before": "2026-03-01",
            "rate_limit_mib": 3.25,
        }

        invalid_rates: tuple[object, ...] = (
            True,
            False,
            None,
            "1",
            "12.5",
            "500k",
            "1M-2M",
            [],
            {},
            0,
            -1,
            0.0999,
            1024.0001,
            math.nan,
            math.inf,
            -math.inf,
        )
        counter_before = executor.counter
        for rate in invalid_rates:
            expect_invalid(
                lambda rate=rate: api.submit(
                    {"sourceUrl": "https://1.1.1.1/invalid-rate", "rateLimitMiB": rate}
                )
            )

        for forbidden in (
            {"rate": "3M"},
            {"rateLimit": 3.25},
            {"rateString": "3.25M"},
            {"downloaderRate": 3.25},
            {"rateConfig": {"downloader.rate": "3M"}},
            {"ratePath": str(root / "secret-rate.txt")},
        ):
            payload = {"sourceUrl": "https://1.1.1.1/gallery", **forbidden}
            expect_invalid(lambda payload=payload: api.submit(payload))
        assert executor.counter == counter_before
    finally:
        api.close()


def test_http_rate_contract(root: Path) -> None:
    api, executor = build_api(root)
    token = "gallery-dl-rate-contract-token-123456"
    server = TestServer(("127.0.0.1", 0), api, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        code, body = request_json(port, "GET", "/v1/gallery-dl/status", token=token)
        assert code == 200 and body["ok"] is True
        assert body["rateLimitSupported"] is True
        assert body["rateLimitMinMiB"] == 0.1
        assert body["rateLimitMaxMiB"] == 1024.0
        assert body["rateLimitUnit"] == "MiB/s"
        assert str(root) not in json.dumps(body)

        code, body = request_json(
            port,
            "POST",
            "/v1/gallery-dl/jobs",
            token=token,
            payload={"sourceUrl": "https://1.1.1.1/gallery", "rateLimitMiB": 3.25},
        )
        assert code == 201 and body["ok"] is True
        assert executor.last_kwargs == {
            "output_root": root / "downloads",
            "max_files": 500,
            "rate_limit_mib": 3.25,
        }

        code, body = request_json(
            port,
            "POST",
            "/v1/gallery-dl/jobs",
            token=token,
            payload={
                "sourceUrl": "https://1.1.1.1/composed",
                "archiveEnabled": True,
                "resumeEnabled": True,
                "dateAfter": "2026-01-01",
                "dateBefore": "2026-03-01",
                "rateLimitMiB": 8,
            },
        )
        assert code == 201 and body["ok"] is True
        assert executor.last_kwargs["archive_enabled"] is True
        assert executor.last_kwargs["resume_enabled"] is True
        assert executor.last_kwargs["date_after"] == "2026-01-01"
        assert executor.last_kwargs["date_before"] == "2026-03-01"
        assert executor.last_kwargs["rate_limit_mib"] == 8

        counter_before = executor.counter
        for bad_payload in (
            {"rateLimitMiB": None},
            {"rateLimitMiB": True},
            {"rateLimitMiB": "3.25"},
            {"rateLimitMiB": 0},
            {"rateLimitMiB": 2048},
            {"rate": "3M"},
            {"rateLimit": 3.25},
            {"downloaderRate": 3.25},
            {"rateConfig": {"downloader.rate": "3M"}},
            {"ratePath": str(root / "secret-rate.txt")},
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
        assert executor.counter == counter_before
    finally:
        api.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def run_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        test_direct_rate_contract(root)
        test_http_rate_contract(root)


if __name__ == "__main__":
    run_test()
    print("Headless gallery-dl Rate API tests passed")
