#!/usr/bin/env python3
from __future__ import annotations

import json
import os
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


def request_json(port: int, method: str, path: str, *, token: str, payload: object | None = None):  # noqa: ANN201
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


def test_direct_output_directory_contract(root: Path) -> None:
    api, executor = build_api(root)
    try:
        status = api.status()
        assert status["outputDirectorySupported"] is True
        assert status["outputDirectoryMode"] == "relative"
        assert status["outputDirectorySeparator"] == "/"
        assert status["outputDirectoryMaxLength"] == 240
        assert status["outputDirectoryMaxDepth"] == 8
        assert str(root) not in json.dumps(status, ensure_ascii=False)

        api.submit({"sourceUrl": "https://1.1.1.1/plain"})
        assert executor.last_kwargs == {"output_root": root / "downloads", "max_files": 500}

        created = api.submit(
            {
                "sourceUrl": "https://1.1.1.1/custom",
                "outputDirectory": "Gallery/项目 A/2026",
            }
        )
        assert created["job"]["state"] == "queued"
        assert executor.last_kwargs == {
            "output_root": root / "downloads" / "Gallery" / "项目 A" / "2026",
            "max_files": 500,
        }

        composed = api.submit(
            {
                "sourceUrl": "https://1.1.1.1/composed",
                "maxFiles": 17,
                "archiveEnabled": True,
                "resumeEnabled": True,
                "dateAfter": "2026-01-01",
                "dateBefore": "2026-03-01",
                "rateLimitMiB": 3.25,
                "outputDirectory": "Social/Artist",
            }
        )
        assert composed["job"]["state"] == "queued"
        assert executor.last_kwargs == {
            "output_root": root / "downloads" / "Social" / "Artist",
            "max_files": 17,
            "archive_enabled": True,
            "resume_enabled": True,
            "date_after": "2026-01-01",
            "date_before": "2026-03-01",
            "rate_limit_mib": 3.25,
        }

        existing_file = root / "downloads" / "occupied"
        existing_file.parent.mkdir(parents=True, exist_ok=True)
        existing_file.write_text("not a directory", encoding="utf-8")

        invalid_values: tuple[object, ...] = (
            None,
            True,
            1,
            "",
            "   ",
            ".",
            "..",
            "../escape",
            "safe/../escape",
            "/absolute/path",
            "//server/share",
            "C:/absolute/path",
            r"safe\windows",
            "safe//nested",
            "safe/./nested",
            "safe/trailing. ",
            "safe/name:stream",
            "safe/\u0001control",
            "occupied/nested",
            "a/b/c/d/e/f/g/h/i",
            "x" * 241,
        )
        counter_before = executor.counter
        for value in invalid_values:
            expect_invalid(
                lambda value=value: api.submit(
                    {"sourceUrl": "https://1.1.1.1/invalid-output", "outputDirectory": value}
                )
            )

        for reserved in ("CON", "nul", "COM1", "LPT9"):
            expect_invalid(
                lambda reserved=reserved: api.submit(
                    {"sourceUrl": "https://1.1.1.1/reserved", "outputDirectory": f"safe/{reserved}"}
                )
            )

        link = root / "downloads" / "link-out"
        outside = root / "outside"
        outside.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pass
        else:
            expect_invalid(
                lambda: api.submit(
                    {"sourceUrl": "https://1.1.1.1/symlink", "outputDirectory": "link-out/nested"}
                )
            )

        assert executor.counter == counter_before

        for forbidden in (
            {"outputRoot": str(root / "escape")},
            {"outputPath": str(root / "escape")},
            {"directory": str(root / "escape")},
            {"path": str(root / "escape")},
        ):
            expect_invalid(
                lambda forbidden=forbidden: api.submit(
                    {"sourceUrl": "https://1.1.1.1/forbidden", **forbidden}
                )
            )
    finally:
        api.close()


def test_http_output_directory_contract(root: Path) -> None:
    api, executor = build_api(root)
    token = "gallery-dl-output-directory-contract-token-123456"
    server = TestServer(("127.0.0.1", 0), api, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        code, body = request_json(port, "GET", "/v1/gallery-dl/status", token=token)
        assert code == 200 and body["ok"] is True
        assert body["outputDirectorySupported"] is True
        assert body["outputDirectoryMode"] == "relative"
        assert body["outputDirectorySeparator"] == "/"
        assert str(root) not in json.dumps(body, ensure_ascii=False)

        code, body = request_json(
            port,
            "POST",
            "/v1/gallery-dl/jobs",
            token=token,
            payload={
                "sourceUrl": "https://1.1.1.1/gallery",
                "outputDirectory": "Exports/Album",
            },
        )
        assert code == 201 and body["ok"] is True
        assert executor.last_kwargs == {
            "output_root": root / "downloads" / "Exports" / "Album",
            "max_files": 500,
        }
        assert str(root) not in json.dumps(body, ensure_ascii=False)

        counter_before = executor.counter
        for value in ("../escape", "/tmp/escape", "C:/escape", r"..\escape", None):
            code, body = request_json(
                port,
                "POST",
                "/v1/gallery-dl/jobs",
                token=token,
                payload={"sourceUrl": "https://1.1.1.1/gallery", "outputDirectory": value},
            )
            assert code == 400 and body["code"] == "GALLERY_DL_INVALID_REQUEST"
            assert str(root) not in json.dumps(body, ensure_ascii=False)
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
        test_direct_output_directory_contract(root)
        test_http_output_directory_contract(root)


if __name__ == "__main__":
    run_test()
    print("Headless gallery-dl Output directory API tests passed")
