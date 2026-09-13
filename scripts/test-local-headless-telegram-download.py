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

AUTH = "headless-telegram-download-contract-token-123456"
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


def request_json(port: int, path: str, payload: object, *, token: str | None = AUTH):
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


def assert_private_details_absent(value: object, root: Path) -> None:
    rendered = json.dumps(value, ensure_ascii=False)
    assert LEAK_TOKEN not in rendered
    assert str(root) not in rendered
    assert root.as_posix() not in rendered
    assert "telegram-upload-secret.json" not in rendered
    assert "--galaxy-telegram-download-json" not in rendered


def expect_error(
    callback,
    payload: object,
    *,
    status: int = 400,
    code: str = "TELEGRAM_INVALID_REQUEST",
) -> None:
    try:
        callback(payload)
    except HeadlessTelegramApiError as exc:
        assert (exc.status, exc.code) == (status, code), (exc.status, exc.code, str(exc))
    else:
        raise AssertionError(f"invalid Telegram download payload accepted: {payload!r}")


def test_status(root: Path) -> None:
    api = build_api(root)
    status = api.status()
    assert status["downloadEndpointSupported"] is True
    assert status["chatBrowserSupported"] is True
    assert status["downloadMaxItems"] == 100
    assert status["downloadMediaKinds"] == ["image", "video", "document"]
    assert_private_details_absent(status, root)


def test_direct_contract(root: Path) -> None:
    api = build_api(root)
    calls: list[tuple[str, dict[str, object]]] = []
    originals = {
        "browse_public_telegram": telegram_api_module.browse_public_telegram,
        "list_telegram_chats": telegram_api_module.list_telegram_chats,
        "browse_telegram_chat": telegram_api_module.browse_telegram_chat,
        "download_public_telegram": telegram_api_module.download_public_telegram,
        "download_telegram_chat": telegram_api_module.download_telegram_chat,
    }

    def browse_public(_context, source, **kwargs):
        calls.append(("browse-public", {"source": source, **kwargs}))
        return {"source": {"username": "demo_channel"}, "messages": [{"messageId": 7, "fileName": "clip.mp4"}]}

    def list_chats(_context, **kwargs):
        calls.append(("chats", dict(kwargs)))
        return {"chats": [{"chatKey": "chat:1", "title": "Demo", "username": "demo", "type": "channel"}]}

    def browse_chat(_context, chat_key, **kwargs):
        calls.append(("browse-chat", {"chatKey": chat_key, **kwargs}))
        return {"chatKey": chat_key, "messages": [{"messageId": 8, "fileName": "photo.jpg"}]}

    def download_public(_context, source, **kwargs):
        calls.append(("download-public", {"source": source, **kwargs}))
        return {"items": [{"messageId": 7, "mediaKind": "video", "fileName": "clip.mp4", "sizeBytes": 123, "collection": "telegram"}], "requestedMessageIds": [7], "scope": "demo_channel"}

    def download_chat(_context, chat_key, **kwargs):
        calls.append(("download-chat", {"chatKey": chat_key, **kwargs}))
        return {"items": [{"messageId": 8, "mediaKind": "image", "fileName": "photo.jpg", "sizeBytes": 55, "collection": "telegram"}], "requestedMessageIds": [8], "scope": "chat-safe"}

    telegram_api_module.browse_public_telegram = browse_public
    telegram_api_module.list_telegram_chats = list_chats
    telegram_api_module.browse_telegram_chat = browse_chat
    telegram_api_module.download_public_telegram = download_public
    telegram_api_module.download_telegram_chat = download_chat
    try:
        public = api.browse_public({"source": "https://t.me/demo_channel", "limit": 20, "beforeMessageId": 99, "mediaKinds": ["video", "image"]})
        chats = api.list_chats({"query": "demo", "limit": 15})
        chat = api.browse_chat({"chatKey": "chat:1", "limit": 10, "mediaKinds": ["image"]})
        public_download = api.download_public({"source": "@demo_channel", "messageIds": [7, 7], "limit": 20, "mediaKinds": ["video"]})
        chat_download = api.download_chat({"chatKey": "chat:1", "messageIds": [8], "mediaKinds": ["image"]})
    finally:
        for name, value in originals.items():
            setattr(telegram_api_module, name, value)

    assert public["messages"][0]["fileName"] == "clip.mp4"
    assert chats["chats"][0]["chatKey"] == "chat:1"
    assert chat["messages"][0]["messageId"] == 8
    assert public_download["items"][0]["fileName"] == "clip.mp4"
    assert chat_download["items"][0]["fileName"] == "photo.jpg"
    assert calls == [
        ("browse-public", {"source": "https://t.me/demo_channel", "limit": 20, "before_message_id": 99, "media_kinds": ["video", "image"]}),
        ("chats", {"query": "demo", "limit": 15}),
        ("browse-chat", {"chatKey": "chat:1", "limit": 10, "before_message_id": 0, "media_kinds": ["image"]}),
        ("download-public", {"source": "@demo_channel", "message_ids": [7], "limit": 20, "media_kinds": ["video"]}),
        ("download-chat", {"chatKey": "chat:1", "message_ids": [8], "limit": 20, "media_kinds": ["image"]}),
    ]
    for result in (public, chats, chat, public_download, chat_download):
        assert_private_details_absent(result, root)

    forbidden_fields = ("filePath", "outputRoot", "outputDirectory", "botToken", "userAdapter", "chatId")
    for field in forbidden_fields:
        expect_error(api.download_public, {"source": "@demo_channel", field: "secret"})
    expect_error(api.browse_public, [])
    expect_error(api.browse_public, {"source": "@demo_channel", "limit": 101})
    expect_error(api.browse_public, {"source": "@demo_channel", "limit": True})
    expect_error(api.browse_public, {"source": "@demo_channel", "mediaKinds": ["audio"]})
    expect_error(api.download_chat, {"chatKey": "chat:1", "messageIds": list(range(1, 102))})
    expect_error(api.download_chat, {"chatKey": "chat:1", "messageIds": [True]})


def test_error_translation(root: Path) -> None:
    api = build_api(root)
    original = telegram_api_module.browse_public_telegram
    try:
        def not_configured(_context, *_args, **_kwargs):
            raise TelegramTransferError("未检测到 Galaxy Telegram User Session adapter")

        telegram_api_module.browse_public_telegram = not_configured
        expect_error(
            api.browse_public,
            {"source": "@demo_channel"},
            status=409,
            code="TELEGRAM_DOWNLOAD_NOT_CONFIGURED",
        )

        def invalid(_context, *_args, **_kwargs):
            raise TelegramTransferError("只支持 Telegram public channel / post")

        telegram_api_module.browse_public_telegram = invalid
        expect_error(
            api.browse_public,
            {"source": "https://example.com"},
            status=400,
            code="TELEGRAM_DOWNLOAD_INVALID_REQUEST",
        )

        def leaking(_context, *_args, **_kwargs):
            raise TelegramTransferError(f"adapter failed {root / 'downloads' / 'secret.mp4'} {LEAK_TOKEN}")

        telegram_api_module.browse_public_telegram = leaking
        try:
            api.browse_public({"source": "@demo_channel"})
        except HeadlessTelegramApiError as exc:
            assert (exc.status, exc.code) == (502, "TELEGRAM_DOWNLOAD_FAILED")
            assert str(exc) == "Telegram download failed"
            assert_private_details_absent({"error": str(exc), "code": exc.code}, root)
        else:
            raise AssertionError("leaking Telegram download error was not translated")
    finally:
        telegram_api_module.browse_public_telegram = original


def test_http_contract(root: Path) -> None:
    api = build_api(root)
    originals = {
        "browse_public_telegram": telegram_api_module.browse_public_telegram,
        "list_telegram_chats": telegram_api_module.list_telegram_chats,
        "browse_telegram_chat": telegram_api_module.browse_telegram_chat,
        "download_public_telegram": telegram_api_module.download_public_telegram,
        "download_telegram_chat": telegram_api_module.download_telegram_chat,
    }
    telegram_api_module.browse_public_telegram = lambda _context, source, **_kwargs: {"source": {"username": "demo_channel"}, "messages": [{"messageId": 1, "fileName": "clip.mp4"}]}
    telegram_api_module.list_telegram_chats = lambda _context, **_kwargs: {"chats": [{"chatKey": "chat:1", "title": "Demo", "username": "demo", "type": "channel"}]}
    telegram_api_module.browse_telegram_chat = lambda _context, chat_key, **_kwargs: {"chatKey": chat_key, "messages": [{"messageId": 2, "fileName": "photo.jpg"}]}
    telegram_api_module.download_public_telegram = lambda _context, source, **_kwargs: {"items": [{"messageId": 1, "mediaKind": "video", "fileName": "clip.mp4", "sizeBytes": 1, "collection": "telegram"}], "requestedMessageIds": [1], "scope": "demo_channel"}
    telegram_api_module.download_telegram_chat = lambda _context, chat_key, **_kwargs: {"items": [{"messageId": 2, "mediaKind": "image", "fileName": "photo.jpg", "sizeBytes": 1, "collection": "telegram"}], "requestedMessageIds": [2], "scope": "chat-safe"}

    server = TestServer(("127.0.0.1", 0), api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        cases = (
            ("/v1/telegram/download/public/browse", {"source": "@demo_channel"}, "messages"),
            ("/v1/telegram/download/chats", {"query": "demo"}, "chats"),
            ("/v1/telegram/download/chat/browse", {"chatKey": "chat:1"}, "messages"),
            ("/v1/telegram/download/public", {"source": "@demo_channel", "messageIds": [1]}, "items"),
            ("/v1/telegram/download/chat", {"chatKey": "chat:1", "messageIds": [2]}, "items"),
        )
        for path, payload, key in cases:
            code, body = request_json(port, path, payload)
            assert code == 200 and body["ok"] is True and key in body, (path, code, body)
            assert_private_details_absent(body, root)

        code, body = request_json(port, "/v1/telegram/download/public", {"source": "@demo_channel", "filePath": str(root / "private")})
        assert code == 400 and body["code"] == "TELEGRAM_INVALID_REQUEST"
        assert_private_details_absent(body, root)

        code, body = request_json(port, "/v1/telegram/download/public", {"source": "@demo_channel"}, token=None)
        assert code == 401 and body["ok"] is False
        assert_private_details_absent(body, root)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        for name, value in originals.items():
            setattr(telegram_api_module, name, value)
        assert not thread.is_alive()


def run_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        test_status(root)
        test_direct_contract(root)
        test_error_translation(root)
        test_http_contract(root)


if __name__ == "__main__":
    run_test()
    print("Headless Telegram download tests passed")
