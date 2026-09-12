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
from headless_telegram_api import HeadlessTelegramApi, HeadlessTelegramApiError  # noqa: E402

AUTH = "headless-telegram-secret-contract-token-123456"
BOT_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef1234567890"
OTHER_TOKEN = "987654321:abcdefghijklmnopqrstuvwxyzABCDEF0987654321"


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


def build_api(root: Path) -> HeadlessTelegramApi:
    return HeadlessTelegramApi(
        root / "downloads",
        program_dir=root / "program",
        data_dir=root / "data",
        state_dir=root / "state",
        tools_dir=root / "tools",
    )


def assert_secret_absent(value: object, root: Path) -> None:
    serialized = json.dumps(value, ensure_ascii=False)
    assert BOT_TOKEN not in serialized
    assert OTHER_TOKEN not in serialized
    assert str(root) not in serialized
    assert "telegram-upload-secret.json" not in serialized


def request_json(port: int, path: str, *, payload: object, token: str | None = AUTH):
    headers = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_direct_contract(root: Path) -> None:
    api = build_api(root)
    before = api.status()
    assert before["secretMutationSupported"] is True
    assert before["uploadEndpointSupported"] is False
    assert before["botTokenConfigured"] is False

    saved = api.save_bot_token({"botToken": BOT_TOKEN})
    assert saved == {"botTokenConfigured": True}
    assert api.settings()["botTokenConfigured"] is True
    assert_secret_absent(saved, root)
    assert_secret_absent(api.status(), root)

    replaced = api.save_bot_token({"botToken": OTHER_TOKEN})
    assert replaced == {"botTokenConfigured": True}
    assert_secret_absent(replaced, root)

    for payload in (
        {},
        {"botToken": ""},
        {"botToken": 123},
        {"botToken": "bad-token"},
        {"botToken": BOT_TOKEN, "extra": True},
        {"token": BOT_TOKEN},
    ):
        try:
            api.save_bot_token(payload)
        except HeadlessTelegramApiError as exc:
            assert exc.status == 400
            assert exc.code == "TELEGRAM_INVALID_REQUEST"
            assert BOT_TOKEN not in str(exc)
            assert OTHER_TOKEN not in str(exc)
        else:
            raise AssertionError(f"invalid Bot Token payload accepted: {payload!r}")

    try:
        api.clear_bot_token({"confirm": True})
    except HeadlessTelegramApiError as exc:
        assert exc.status == 400
    else:
        raise AssertionError("non-empty clear payload was accepted")

    cleared = api.clear_bot_token({})
    assert cleared == {"botTokenConfigured": False}
    assert api.status()["botTokenConfigured"] is False
    assert api.clear_bot_token({}) == {"botTokenConfigured": False}
    assert_secret_absent(cleared, root)


def test_http_contract(root: Path) -> None:
    api = build_api(root)
    server = TestServer(("127.0.0.1", 0), api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        code, body = request_json(port, "/v1/telegram/bot-token", payload={"botToken": BOT_TOKEN})
        assert code == 200 and body == {"ok": True, "botTokenConfigured": True}
        assert_secret_absent(body, root)

        code, body = request_json(port, "/v1/telegram/bot-token", payload={"botToken": "bad-token"})
        assert code == 400 and body["code"] == "TELEGRAM_INVALID_REQUEST"
        assert api.status()["botTokenConfigured"] is True
        assert_secret_absent(body, root)

        code, body = request_json(port, "/v1/telegram/bot-token/clear", payload={})
        assert code == 200 and body == {"ok": True, "botTokenConfigured": False}
        assert_secret_absent(body, root)

        code, body = request_json(
            port,
            "/v1/telegram/bot-token",
            payload={"botToken": BOT_TOKEN},
            token=None,
        )
        assert code == 401 and body["ok"] is False
        assert api.status()["botTokenConfigured"] is False
        assert_secret_absent(body, root)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def run_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        test_direct_contract(root)
        test_http_contract(root)


if __name__ == "__main__":
    run_test()
    print("Headless Telegram Bot Token mutation tests passed")