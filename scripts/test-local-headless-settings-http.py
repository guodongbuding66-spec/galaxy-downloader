from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiServer
from headless_service import HeadlessRuntime


class FakeAiApi:
    def shutdown(self) -> None:
        raise AssertionError("caller-owned AI API must not be shut down")


class FakeAsrApi:
    pass


class FakeWhisperXApi:
    pass


class FakePluginApi:
    pass


class FakeTransferApi:
    def shutdown(self) -> None:
        raise AssertionError("caller-owned Transfer API must not be shut down")


def _get(port: int, path: str, token: str = "") -> tuple[int, dict]:
    headers = {"Host": f"127.0.0.1:{port}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _run_server_case(root: Path, *, bound_host: str, token: str) -> None:
    runtime = HeadlessRuntime(root)
    server = GalaxyApiServer(
        ("127.0.0.1", 0),
        runtime,
        token,
        bound_host,
        None,
        ai_api=FakeAiApi(),
        asr_api=FakeAsrApi(),
        whisperx_api=FakeWhisperXApi(),
        plugin_api=FakePluginApi(),
        transfer_api=FakeTransferApi(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        code, body = _get(port, "/v1/settings")
        assert code == 401 and body["ok"] is False

        code, body = _get(port, "/v1/settings?view=runtime", token)
        assert code == 200 and body["ok"] is True
        settings = body["settings"]
        remote = bound_host != "127.0.0.1"
        assert settings["bindingMode"] == ("remote" if remote else "loopback")
        assert settings["remoteAccess"] is remote
        assert settings["authentication"]["configured"] is True
        assert settings["authentication"]["required"] is remote
        assert settings["configuration"]["writable"] is False
        assert settings["configuration"]["mode"] == "environment-or-cli"
        assert settings["features"]["ai"] is True
        assert settings["features"]["asr"] is True
        assert settings["features"]["whisperx"] is True
        assert settings["features"]["plugins"] is True
        assert settings["features"]["transfer"] is True

        rendered = json.dumps(body, ensure_ascii=False)
        assert token not in rendered
        assert bound_host not in rendered
        assert str(root) not in rendered
        assert "download_root" not in rendered

        code, body = _get(port, "/v1/status", token)
        assert code == 200 and body["ok"] is True and body["protocol"] == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        runtime.stop()


def run_test() -> None:
    import tempfile

    token = "settings-production-test-token-123456789"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        _run_server_case(root / "loopback", bound_host="127.0.0.1", token=token)
        _run_server_case(root / "remote", bound_host="0.0.0.0", token=token)


if __name__ == "__main__":
    run_test()
    print("Headless settings production HTTP self-test passed")
