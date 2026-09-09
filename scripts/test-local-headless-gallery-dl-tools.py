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
from headless_gallery_dl_api import HeadlessGalleryDlApi, HeadlessGalleryDlApiError  # noqa: E402
from headless_gallery_dl_http import HeadlessGalleryDlHttpMixin  # noqa: E402
from local_task_provider import LocalTaskActionResult, LocalTaskSnapshot  # noqa: E402
from managed_tool_actions import ManagedToolActionResult, run_managed_tool_actions_self_test  # noqa: E402


class FakeExecutor:
    def __init__(self) -> None:
        self.tasks: dict[str, str] = {}
        self.counter = 0
        self.submit_called = threading.Event()

    def submit(self, source_url: str, *, output_root: Path, max_files: int) -> str:
        del source_url, output_root, max_files
        self.submit_called.set()
        self.counter += 1
        task_id = f"gdl-{self.counter:016x}"
        self.tasks[task_id] = "queued"
        return task_id

    def snapshots(self):  # noqa: ANN201
        rows = []
        for task_id, state in self.tasks.items():
            actions = (
                ("cancel",)
                if state in {"queued", "active"}
                else (("retry",) if state in {"failed", "cancelled"} else ())
            )
            rows.append(
                LocalTaskSnapshot(
                    task_id=task_id,
                    state=state,
                    title="Gallery · example.test",
                    provider_label="gallery-dl",
                    task_type="图片 / 图库",
                    actions=actions,
                )
            )
        return tuple(rows)

    def action(self, task_id: str, action: str) -> LocalTaskActionResult:
        state = self.tasks.get(task_id)
        if action == "cancel" and state in {"queued", "active"}:
            self.tasks[task_id] = "cancelled"
            return LocalTaskActionResult(True, True, "cancelled")
        if action == "retry" and state in {"failed", "cancelled"}:
            self.tasks[task_id] = "queued"
            return LocalTaskActionResult(True, True, "retried")
        return LocalTaskActionResult(False, False, "conflict")


class FakeToolRunner:
    def __init__(self) -> None:
        self.calls = []
        self.installed = True
        self.version: str | None = "1.32.0-test"
        self.mode = "ok"
        self.started: threading.Event | None = None
        self.release: threading.Event | None = None

    def probe(self) -> tuple[bool, str | None]:
        return self.installed, self.version

    def __call__(self, engine, request):  # noqa: ANN001,ANN201
        self.calls.append((engine.tools_dir(), request))
        if self.started is not None:
            self.started.set()
        if self.release is not None and not self.release.wait(timeout=5):
            raise RuntimeError("test tool runner timed out")
        if self.mode == "raise":
            raise RuntimeError("failure at /tmp/private/tool.json Authorization: Bearer secretsecret")
        if self.mode == "runtime-busy":
            return _tool_result(request.action, ok=False, state="runtime-busy", version=self.version)
        if request.action == "check":
            return _tool_result(
                "check",
                state="update_available",
                version=self.version,
                available_version="1.33.0-test",
                available_release_tag="v1.33.0-test",
                update_available=True,
                network=True,
            )
        if request.action in {"install", "update"}:
            changed = not self.installed or self.version != "1.33.0-test"
            self.installed = True
            self.version = "1.33.0-test"
            return _tool_result(request.action, changed=changed, version=self.version, network=True)
        if request.action == "remove":
            self.installed = False
            self.version = None
            return _tool_result("remove", changed=True, source="unavailable")
        raise AssertionError(f"unexpected action: {request.action}")


def _tool_result(
    action: str,
    *,
    ok: bool = True,
    changed: bool = False,
    state: str = "completed",
    source: str = "managed",
    version: str | None = None,
    available_version: str | None = None,
    available_release_tag: str | None = None,
    update_available: bool | None = None,
    network: bool = False,
) -> ManagedToolActionResult:
    return ManagedToolActionResult(
        tool="gallery-dl",
        action=action,
        ok=ok,
        changed=changed,
        state=state,
        source=source,
        version=version,
        available_version=available_version,
        available_release_tag=available_release_tag,
        update_available=update_available,
        network_action=network,
        message="provider detail /tmp/private Authorization: Bearer secretsecret",
    )


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


def _build_api(root: Path, executor: FakeExecutor | None = None, runner: FakeToolRunner | None = None):  # noqa: ANN201
    selected_executor = executor or FakeExecutor()
    selected_runner = runner or FakeToolRunner()
    api = HeadlessGalleryDlApi(
        root / "downloads",
        tools_root=root / "tools",
        executor=selected_executor,  # type: ignore[arg-type]
        tool_probe=selected_runner.probe,
        tool_action_runner=selected_runner,
    )
    return api, selected_executor, selected_runner


def _expect_error(callback, status: int, code: str) -> None:  # noqa: ANN001
    try:
        callback()
    except HeadlessGalleryDlApiError as exc:
        assert (exc.status, exc.code) == (status, code)
    else:
        raise AssertionError(f"expected {code}")


def _request(port: int, method: str, path: str, *, token: str = "", payload: object | None = None):  # noqa: ANN201
    headers = {"Host": f"127.0.0.1:{port}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
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


def _test_direct(root: Path) -> None:
    api, executor, runner = _build_api(root)
    status = api.tool_status()
    assert status["installed"] is True and status["version"] == "1.32.0-test"
    assert status["supportedActions"] == ["check", "install", "update", "remove"]
    assert status["mutationBlocked"] is False
    assert status["removeConfirmation"] == "remove-gallery-dl"
    assert runner.calls == []

    checked = api.tool_action("check", {})
    assert checked["result"]["state"] == "update_available"
    assert checked["result"]["availableVersion"] == "1.33.0-test"
    serialized = json.dumps(checked)
    assert "/tmp/private" not in serialized and "secretsecret" not in serialized
    tools_root, request = runner.calls[-1]
    assert tools_root == (root / "tools").resolve()
    assert request.tool == "gallery-dl" and request.action == "check"
    assert request.user_initiated is True and request.channel is None

    _expect_error(lambda: api.tool_action("install", {"url": "https://example.com/tool.whl"}), 400, "GALLERY_DL_INVALID_REQUEST")
    _expect_error(lambda: api.tool_action("update", {"path": str(root / "private")}), 400, "GALLERY_DL_INVALID_REQUEST")
    _expect_error(lambda: api.tool_action("remove", {}), 409, "GALLERY_DL_REMOVE_CONFIRMATION_REQUIRED")
    _expect_error(lambda: api.tool_action("remove", {"confirm": "yes"}), 409, "GALLERY_DL_REMOVE_CONFIRMATION_REQUIRED")

    updated = api.tool_action("update", {})
    assert updated["tool"]["installed"] is True and updated["tool"]["version"] == "1.33.0-test"
    removed = api.tool_action("remove", {"confirm": "remove-gallery-dl"})
    assert removed["tool"]["installed"] is False and removed["tool"]["version"] is None

    executor.tasks["gdl-aaaaaaaaaaaaaaaa"] = "queued"
    call_count = len(runner.calls)
    _expect_error(lambda: api.tool_action("install", {}), 409, "GALLERY_DL_TOOL_BUSY")
    assert len(runner.calls) == call_count
    assert api.tool_action("check", {})["result"]["action"] == "check"

    executor.tasks.clear()
    runner.mode = "runtime-busy"
    _expect_error(lambda: api.tool_action("update", {}), 409, "GALLERY_DL_TOOL_BUSY")
    runner.mode = "raise"
    _expect_error(lambda: api.tool_action("update", {}), 502, "GALLERY_DL_TOOL_ACTION_FAILED")


def _test_operation_lock(root: Path) -> None:
    executor = FakeExecutor()
    runner = FakeToolRunner()
    runner.started = threading.Event()
    runner.release = threading.Event()
    api, _, _ = _build_api(root, executor, runner)
    tool_errors: list[Exception] = []
    submit_errors: list[Exception] = []
    submit_entered = threading.Event()

    def mutate() -> None:
        try:
            api.tool_action("update", {})
        except Exception as exc:  # pragma: no cover - assertion captures thread failures
            tool_errors.append(exc)

    def submit() -> None:
        submit_entered.set()
        try:
            api.submit({"sourceUrl": "https://1.1.1.1/gallery"})
        except Exception as exc:  # pragma: no cover - assertion captures thread failures
            submit_errors.append(exc)

    mutation_thread = threading.Thread(target=mutate)
    mutation_thread.start()
    assert runner.started.wait(timeout=3)
    submit_thread = threading.Thread(target=submit)
    submit_thread.start()
    assert submit_entered.wait(timeout=3)
    assert executor.submit_called.is_set() is False
    runner.release.set()
    mutation_thread.join(timeout=3)
    submit_thread.join(timeout=3)
    assert not mutation_thread.is_alive() and not submit_thread.is_alive()
    assert tool_errors == [] and submit_errors == []
    assert executor.submit_called.is_set() is True


def _test_http(root: Path) -> None:
    api, executor, runner = _build_api(root)
    assert HeadlessGalleryDlHttpMixin in GalaxyApiRequestHandler.__mro__
    token = "gallery-tool-test-token-123456789"
    server = TestServer(("127.0.0.1", 0), api, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        code, body = _request(port, "GET", "/v1/gallery-dl/tool")
        assert code == 401 and body["error"] == "unauthorized"
        code, body = _request(port, "GET", f"/v1/gallery-dl/tool?token={token}")
        assert code == 401 and body["error"] == "unauthorized"
        code, body = _request(port, "GET", "/v1/gallery-dl/tool", token=token)
        assert code == 200 and body["installed"] is True and runner.calls == []

        code, body = _request(port, "POST", "/v1/gallery-dl/tool/check", token=token, payload={})
        assert code == 200 and body["result"]["action"] == "check"
        assert "/tmp/private" not in json.dumps(body) and "secretsecret" not in json.dumps(body)

        code, body = _request(
            port, "POST", "/v1/gallery-dl/tool/install", token=token, payload={"url": "https://example.com/tool.whl"}
        )
        assert code == 400 and body["code"] == "GALLERY_DL_INVALID_REQUEST"
        code, body = _request(port, "POST", "/v1/gallery-dl/tool/remove", token=token, payload={})
        assert code == 409 and body["code"] == "GALLERY_DL_REMOVE_CONFIRMATION_REQUIRED"

        executor.tasks["gdl-bbbbbbbbbbbbbbbb"] = "queued"
        code, body = _request(port, "POST", "/v1/gallery-dl/tool/update", token=token, payload={})
        assert code == 409 and body["code"] == "GALLERY_DL_TOOL_BUSY"
        executor.tasks.clear()

        code, body = _request(
            port,
            "POST",
            "/v1/gallery-dl/tool/remove",
            token=token,
            payload={"confirm": "remove-gallery-dl"},
        )
        assert code == 200 and body["tool"]["installed"] is False

        secret = str(root / "private" / "provider.json")

        def secret_failure(engine, request):  # noqa: ANN001,ANN201
            del engine, request
            raise RuntimeError(f"provider failed at {secret} Authorization: Bearer secretsecret")

        api._tool_action_runner = secret_failure  # type: ignore[attr-defined]
        code, body = _request(port, "POST", "/v1/gallery-dl/tool/update", token=token, payload={})
        assert code == 502 and body["code"] == "GALLERY_DL_TOOL_ACTION_FAILED"
        serialized = json.dumps(body)
        assert body["error"] == "gallery-dl tool action failed"
        assert secret not in serialized and str(root) not in serialized and "secretsecret" not in serialized
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def run_test() -> None:
    import tempfile

    run_managed_tool_actions_self_test()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        _test_direct(root)
        _test_operation_lock(root)
        _test_http(root)


if __name__ == "__main__":
    run_test()
    print("Headless gallery-dl tool manager tests passed")
