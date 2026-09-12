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

import headless_telegram_api as telegram_api_module  # noqa: E402
from headless_api import GalaxyApiRequestHandler  # noqa: E402
from headless_telegram_api import HeadlessTelegramApi, HeadlessTelegramApiError  # noqa: E402
from telegram_transfer import TelegramTransferError  # noqa: E402

AUTH = "headless-telegram-upload-contract-token-123456"
MEDIA_ID = "0123456789abcdef0123456789abcdef"
LEAK_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef1234567890"


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


def request_json(port: int, payload: object, *, token: str | None = AUTH):
    headers = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/telegram/upload",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def assert_private_details_absent(value: object, root: Path) -> None:
    rendered = json.dumps(value, ensure_ascii=False)
    assert LEAK_TOKEN not in rendered
    assert str(root) not in rendered
    assert root.as_posix() not in rendered
    assert "api.telegram.org" not in rendered
    assert "telegram-upload-secret.json" not in rendered


def expect_error(api: HeadlessTelegramApi, payload: object, *, status: int = 400, code: str = "TELEGRAM_INVALID_REQUEST") -> None:
    try:
        api.upload_media(payload)
    except HeadlessTelegramApiError as exc:
        assert (exc.status, exc.code) == (status, code), (exc.status, exc.code, str(exc))
    else:
        raise AssertionError(f"invalid Telegram upload payload accepted: {payload!r}")


def test_direct_contract(root: Path) -> None:
    api = build_api(root)
    assert api.status()["uploadEndpointSupported"] is True
    captured: list[dict[str, object]] = []

    def fake_upload(_context, **kwargs):
        captured.append(dict(kwargs))
        return [
            {
                "ok": True,
                "result": {
                    "file_path": str(root / "downloads" / "private.mp4"),
                    "token": LEAK_TOKEN,
                    "remote": "https://api.telegram.org/private",
                },
            },
            {"ok": True},
        ]

    original = telegram_api_module.upload_to_telegram
    telegram_api_module.upload_to_telegram = fake_upload
    try:
        result = api.upload_media(
            {
                "mediaId": MEDIA_ID.upper(),
                "filename": " demo export ",
                "extension": "MP4",
                "caption": "caption",
                "autoChunk": False,
            }
        )
    finally:
        telegram_api_module.upload_to_telegram = original

    assert result == {
        "uploaded": True,
        "mediaId": MEDIA_ID,
        "parts": 2,
        "mode": "bot",
        "sendAs": "document",
        "autoChunk": False,
    }
    assert len(captured) == 1
    sent = captured[0]
    assert sent == {
        "media_id": MEDIA_ID,
        "filename": " demo export ",
        "extension": "MP4",
        "caption": "caption",
        "auto_chunk": False,
    }
    assert "file_path" not in sent
    assert "thumbnail" not in sent
    assert_private_details_absent(result, root)

    invalid_payloads = (
        {},
        {"mediaId": "not-a-media-id"},
        {"mediaId": MEDIA_ID, "filePath": str(root / "private.mp4")},
        {"mediaId": MEDIA_ID, "thumbnail": str(root / "thumb.jpg")},
        {"mediaId": MEDIA_ID, "botToken": LEAK_TOKEN},
        {"mediaId": MEDIA_ID, "chatId": "@other"},
        {"mediaId": MEDIA_ID, "extra": True},
        {"mediaId": MEDIA_ID, "filename": 123},
        {"mediaId": MEDIA_ID, "filename": "x" * 181},
        {"mediaId": MEDIA_ID, "extension": "mp4.exe"},
        {"mediaId": MEDIA_ID, "extension": 123},
        {"mediaId": MEDIA_ID, "caption": 123},
        {"mediaId": MEDIA_ID, "caption": "x" * 1025},
        {"mediaId": MEDIA_ID, "autoChunk": 1},
    )
    for payload in invalid_payloads:
        expect_error(api, payload)


def test_error_translation(root: Path) -> None:
    api = build_api(root)
    original = telegram_api_module.upload_to_telegram
    cases = (
        ("媒体文件不可用", 404, "TELEGRAM_MEDIA_NOT_FOUND"),
        ("请先设置 Telegram Chat ID / @username", 409, "TELEGRAM_NOT_CONFIGURED"),
        ("请先保存 Telegram Bot Token", 409, "TELEGRAM_NOT_CONFIGURED"),
        ("未检测到 Galaxy Telegram User Session adapter", 409, "TELEGRAM_NOT_CONFIGURED"),
        ("文件为空或超过 4 GB 上限", 409, "TELEGRAM_UPLOAD_LIMIT"),
        ("Bot 模式单文件超过 50 MB，请开启自动分片或使用 User Session adapter", 409, "TELEGRAM_UPLOAD_LIMIT"),
    )
    try:
        for message, status, code in cases:
            def failing_upload(_context, _message=message, **_kwargs):
                raise TelegramTransferError(_message)

            telegram_api_module.upload_to_telegram = failing_upload
            expect_error(api, {"mediaId": MEDIA_ID}, status=status, code=code)

        leaked = f"request failed {root / 'downloads' / 'secret.mp4'} {LEAK_TOKEN} https://api.telegram.org/private"

        def leaking_upload(_context, **_kwargs):
            raise TelegramTransferError(leaked)

        telegram_api_module.upload_to_telegram = leaking_upload
        try:
            api.upload_media({"mediaId": MEDIA_ID})
        except HeadlessTelegramApiError as exc:
            assert (exc.status, exc.code) == (502, "TELEGRAM_UPLOAD_FAILED")
            assert str(exc) == "Telegram upload failed"
            assert_private_details_absent({"error": str(exc), "code": exc.code}, root)
        else:
            raise AssertionError("leaking Telegram error was not translated")
    finally:
        telegram_api_module.upload_to_telegram = original


def test_http_contract(root: Path) -> None:
    api = build_api(root)
    calls: list[dict[str, object]] = []

    def fake_upload(_context, **kwargs):
        calls.append(dict(kwargs))
        return [{"ok": True, "secret": LEAK_TOKEN, "path": str(root / "downloads" / "file.mp4")}]

    original = telegram_api_module.upload_to_telegram
    telegram_api_module.upload_to_telegram = fake_upload
    server = TestServer(("127.0.0.1", 0), api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        code, body = request_json(
            port,
            {"mediaId": MEDIA_ID, "filename": "clip", "extension": "mkv", "caption": "hello"},
        )
        assert code == 200
        assert body == {
            "ok": True,
            "uploaded": True,
            "mediaId": MEDIA_ID,
            "parts": 1,
            "mode": "bot",
            "sendAs": "document",
            "autoChunk": True,
        }
        assert len(calls) == 1
        assert_private_details_absent(body, root)

        code, body = request_json(port, {"mediaId": MEDIA_ID, "filePath": str(root / "private.mp4")})
        assert code == 400 and body["code"] == "TELEGRAM_INVALID_REQUEST"
        assert len(calls) == 1
        assert_private_details_absent(body, root)

        code, body = request_json(port, {"mediaId": MEDIA_ID, "thumbnail": str(root / "thumb.jpg")})
        assert code == 400 and body["code"] == "TELEGRAM_INVALID_REQUEST"
        assert len(calls) == 1
        assert_private_details_absent(body, root)

        code, body = request_json(port, {"mediaId": MEDIA_ID}, token=None)
        assert code == 401 and body["ok"] is False
        assert len(calls) == 1
        assert_private_details_absent(body, root)

        def leaking_upload(_context, **_kwargs):
            raise TelegramTransferError(f"network {LEAK_TOKEN} {root / 'private.mp4'}")

        telegram_api_module.upload_to_telegram = leaking_upload
        code, body = request_json(port, {"mediaId": MEDIA_ID})
        assert code == 502 and body["code"] == "TELEGRAM_UPLOAD_FAILED"
        assert body["error"] == "Telegram upload failed"
        assert_private_details_absent(body, root)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        telegram_api_module.upload_to_telegram = original
        assert not thread.is_alive()


def run_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        test_direct_contract(root)
        test_error_translation(root)
        test_http_contract(root)


if __name__ == "__main__":
    run_test()
    print("Headless Telegram media upload tests passed")
