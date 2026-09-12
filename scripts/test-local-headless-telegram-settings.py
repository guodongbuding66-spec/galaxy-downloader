from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiRequestHandler, GalaxyApiServer  # noqa: E402
from headless_telegram_api import HeadlessTelegramApi, HeadlessTelegramApiError  # noqa: E402
from telegram_transfer import TelegramUploadSettings, save_telegram_upload_settings  # noqa: E402

TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef1234567890"
AUTH = "headless-telegram-settings-contract-token-123456"


class TestServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, telegram_api: HeadlessTelegramApi):
        self.auth_token = AUTH
        self.bound_host = "127.0.0.1"
        self.telegram_api = telegram_api
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
        self.gallery_dl_api = None
        self.course_download_coordinator = None
        self.course_attachment_download_service = None
        super().__init__(address, GalaxyApiRequestHandler)


class FakeTransferApi:
    """Legacy/injected Transfer API intentionally lacking the optional context attribute."""

    def shutdown(self) -> None:
        return


def request_json(
    port: int,
    method: str,
    path: str,
    *,
    token: str | None = AUTH,
    payload: object | None = None,
):
    headers = {"Host": f"127.0.0.1:{port}"}
    if token is not None:
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


def assert_no_secret(value: object, root: Path) -> None:
    serialized = json.dumps(value, ensure_ascii=False)
    assert TOKEN not in serialized
    assert str(root) not in serialized
    assert root.as_posix() not in serialized
    assert "telegram-upload-secret.json" not in serialized


def build_api(root: Path) -> HeadlessTelegramApi:
    return HeadlessTelegramApi(
        root / "downloads",
        program_dir=root / "program",
        data_dir=root / "data",
        state_dir=root / "state",
        tools_dir=root / "tools",
    )


def test_direct_contract(root: Path) -> None:
    api = build_api(root)
    status = api.status()
    assert status["settingsSupported"] is True
    assert status["secretMutationSupported"] is False
    assert status["uploadEndpointSupported"] is False
    assert status["botTokenConfigured"] is False
    assert status["modes"] == ["bot", "user"]
    assert set(status["sendAsModes"]) == {"document", "video", "audio"}
    assert status["settings"] == {
        "mode": "bot",
        "chatId": "",
        "sendAs": "document",
        "userAdapter": "galaxy-telegram-user",
    }
    assert_no_secret(status, root)

    save_telegram_upload_settings(
        api.context,
        TelegramUploadSettings(mode="bot", chat_id="@example_user", send_as="video"),
        bot_token=TOKEN,
    )
    before = api.settings()
    assert before["botTokenConfigured"] is True
    assert before["settings"]["chatId"] == "@example_user"
    assert_no_secret(before, root)

    updated = api.save_settings(
        {
            "mode": "user",
            "chatId": "-1001234567890",
            "sendAs": "audio",
            "userAdapter": " galaxy-telegram-user-v2 ",
        }
    )
    assert updated["settings"] == {
        "mode": "user",
        "chatId": "-1001234567890",
        "sendAs": "audio",
        "userAdapter": "galaxy-telegram-user-v2",
    }
    assert updated["botTokenConfigured"] is True
    assert_no_secret(updated, root)

    partial = api.save_settings({"sendAs": "document"})
    assert partial["settings"]["mode"] == "user"
    assert partial["settings"]["chatId"] == "-1001234567890"
    assert partial["settings"]["sendAs"] == "document"
    assert partial["botTokenConfigured"] is True

    for payload in (
        {"botToken": TOKEN},
        {"filePath": str(root / "private.mp4")},
        {"mediaId": "0123456789abcdef"},
        {"thumbnail": str(root / "thumb.jpg")},
        {"caption": "secret-ish upload data"},
    ):
        try:
            api.save_settings(payload)
        except HeadlessTelegramApiError as exc:
            assert (exc.status, exc.code) == (400, "TELEGRAM_INVALID_REQUEST")
            assert TOKEN not in str(exc)
            assert str(root) not in str(exc)
        else:
            raise AssertionError(f"unsafe Telegram field was accepted: {payload!r}")

    try:
        api.save_settings({"chatId": "bad chat id"})
    except HeadlessTelegramApiError as exc:
        assert exc.status == 400
        assert exc.code == "TELEGRAM_INVALID_REQUEST"
    else:
        raise AssertionError("invalid Telegram chat id was accepted")

    after = api.settings()
    assert after["botTokenConfigured"] is True
    assert after["settings"]["chatId"] == "-1001234567890"
    assert_no_secret(after, root)


def test_http_contract(root: Path) -> None:
    api = build_api(root)
    save_telegram_upload_settings(
        api.context,
        TelegramUploadSettings(mode="bot", chat_id="@example_user", send_as="document"),
        bot_token=TOKEN,
    )
    server = TestServer(("127.0.0.1", 0), api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        code, body = request_json(port, "GET", "/v1/telegram/status")
        assert code == 200 and body["ok"] is True
        assert body["botTokenConfigured"] is True
        assert body["secretMutationSupported"] is False
        assert_no_secret(body, root)

        code, body = request_json(port, "GET", "/v1/telegram/settings")
        assert code == 200 and body["ok"] is True
        assert body["settings"]["chatId"] == "@example_user"
        assert_no_secret(body, root)

        code, body = request_json(
            port,
            "POST",
            "/v1/telegram/settings",
            payload={"mode": "user", "chatId": "@new_user", "sendAs": "audio"},
        )
        assert code == 200 and body["ok"] is True
        assert body["settings"]["mode"] == "user"
        assert body["settings"]["chatId"] == "@new_user"
        assert body["botTokenConfigured"] is True
        assert_no_secret(body, root)

        code, body = request_json(
            port,
            "POST",
            "/v1/telegram/settings",
            payload={"botToken": TOKEN},
        )
        assert code == 400 and body["code"] == "TELEGRAM_INVALID_REQUEST"
        assert_no_secret(body, root)

        code, body = request_json(port, "GET", "/v1/telegram/status", token=None)
        assert code == 401 and body["ok"] is False
        assert_no_secret(body, root)

        code, body = request_json(port, "GET", "/v1/telegram/not-real")
        assert code == 404 and body["ok"] is False
        assert_no_secret(body, root)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_production_server_tolerates_injected_transfer_without_context(root: Path) -> None:
    downloads = root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    runtime = SimpleNamespace(download_root=downloads)
    server = GalaxyApiServer(
        ("127.0.0.1", 0),
        runtime,
        AUTH,
        "127.0.0.1",
        media_api=SimpleNamespace(),
        transfer_api=FakeTransferApi(),
        ai_api=SimpleNamespace(shutdown=lambda: None),
        asr_api=SimpleNamespace(context=None),
        whisperx_api=SimpleNamespace(),
        plugin_api=SimpleNamespace(),
        gallery_dl_api=SimpleNamespace(close=lambda: None),
    )
    try:
        assert isinstance(server.telegram_api, HeadlessTelegramApi)
        assert server.telegram_api.context.download_root == downloads.resolve(strict=False)
    finally:
        server.server_close()


def test_production_wiring() -> None:
    source = (LOCAL_ENGINE / "headless_api.py").read_text(encoding="utf-8")
    assert "HeadlessTelegramHttpMixin" in source
    assert "HeadlessTelegramApi" in source
    assert "telegram_api: HeadlessTelegramApi | None = None" in source
    assert 'shared_transfer_context = getattr(transfer, "context", None)' in source
    assert "context=shared_transfer_context" in source
    assert "self.telegram_api = telegram" in source


def run_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        test_direct_contract(root)
        test_http_contract(root)
        test_production_server_tolerates_injected_transfer_without_context(root)
    test_production_wiring()


if __name__ == "__main__":
    run_test()
    print("Headless Telegram public settings tests passed")