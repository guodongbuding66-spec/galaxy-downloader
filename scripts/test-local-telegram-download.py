from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import telegram_download  # noqa: E402


class _Engine:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.downloads = root / "downloads"
        self.state = root / "state"
        self.downloads.mkdir(parents=True, exist_ok=True)
        self.state.mkdir(parents=True, exist_ok=True)

    def app_dir(self) -> Path:
        return self.root

    def state_dir(self) -> Path:
        return self.state

    def default_download_dir(self) -> Path:
        return self.downloads


class TelegramDownloadTests(unittest.TestCase):
    def test_self_test(self) -> None:
        telegram_download.run_telegram_download_self_test()

    def test_public_source_parsing_accepts_supported_forms_and_rejects_private_links(self) -> None:
        cases = {
            "https://t.me/example_channel/123": {"username": "example_channel", "postId": 123},
            "https://t.me/s/example_channel/456": {"username": "example_channel", "postId": 456},
            "https://telegram.me/example_channel": {"username": "example_channel"},
            "tg://resolve?domain=example_channel&post=789": {"username": "example_channel", "postId": 789},
            "@example_channel": {"username": "example_channel"},
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(telegram_download.parse_public_telegram_source(raw).public_payload(), expected)

        rejected = (
            "https://t.me/c/123/456",
            "https://t.me/+abcdef",
            "https://example.com/example_channel/1",
            "https://t.me/abc/1/extra",
            "https://t.me/abcd/0",
            "https://t.me/example_channel/not-a-number",
            "bad host",
        )
        for raw in rejected:
            with self.subTest(raw=raw):
                with self.assertRaises(telegram_download.TelegramTransferError):
                    telegram_download.parse_public_telegram_source(raw)

    def _adapter_result(self, payload: object, *, returncode: int = 0, stderr: str = "") -> SimpleNamespace:
        return SimpleNamespace(returncode=returncode, stdout=json.dumps(payload, ensure_ascii=False), stderr=stderr)

    def test_browse_public_uses_user_session_adapter_and_sanitizes_messages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            response = self._adapter_result(
                {
                    "ok": True,
                    "messages": [
                        {
                            "messageId": 123,
                            "date": "2026-09-12T01:02:03Z",
                            "text": "  hello   world  ",
                            "mediaKind": "video",
                            "fileName": "../../clip.mp4",
                            "sizeBytes": 99,
                            "absolutePath": str(engine.root / "private.mp4"),
                        },
                        {"messageId": "bad", "text": "ignored"},
                    ],
                }
            )
            with (
                patch.object(telegram_download.shutil, "which", return_value="/usr/bin/galaxy-telegram-user"),
                patch.object(telegram_download.subprocess, "run", return_value=response) as run,
            ):
                result = telegram_download.browse_public_telegram(
                    engine,
                    "https://t.me/example_channel/123",
                    limit=250,
                    before_message_id=130,
                    media_kinds=["video", "image", "video"],
                )

            self.assertEqual(result["source"], {"username": "example_channel", "postId": 123})
            self.assertEqual(len(result["messages"]), 1)
            self.assertEqual(result["messages"][0]["fileName"], "clip.mp4")
            self.assertEqual(result["messages"][0]["text"], "hello world")
            self.assertNotIn("absolutePath", result["messages"][0])
            args, kwargs = run.call_args
            self.assertEqual(args[0], ["/usr/bin/galaxy-telegram-user", "--galaxy-telegram-download-json"])
            self.assertNotIn("shell", kwargs)
            request = json.loads(kwargs["input"])
            self.assertEqual(request["protocol"], telegram_download.DOWNLOAD_PROTOCOL)
            self.assertEqual(request["action"], "browse")
            self.assertEqual(request["limit"], 100)
            self.assertEqual(request["beforeMessageId"], 130)
            self.assertEqual(request["mediaKinds"], ["video", "image"])

    def test_chat_browser_lists_and_browses_sanitized_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            chats = self._adapter_result(
                {
                    "ok": True,
                    "chats": [
                        {"chatKey": "channel:123", "title": "  Demo  Channel ", "username": "demo_channel", "type": "channel"},
                        {"chatKey": "bad key!", "title": "bad"},
                        {"chatKey": "user:9", "title": "User", "username": "bad name", "type": "unexpected"},
                    ],
                }
            )
            messages = self._adapter_result(
                {"ok": True, "messages": [{"messageId": 9, "text": "message", "mediaKind": "document", "fileName": "doc.pdf"}]}
            )
            with patch.object(telegram_download.shutil, "which", return_value="adapter"):
                with patch.object(telegram_download.subprocess, "run", return_value=chats) as run:
                    listed = telegram_download.list_telegram_chats(engine, query="  course   channel ", limit=500)
                with patch.object(telegram_download.subprocess, "run", return_value=messages) as browse_run:
                    browsed = telegram_download.browse_telegram_chat(engine, "channel:123", media_kinds="document")

            self.assertEqual(len(listed["chats"]), 2)
            self.assertEqual(listed["chats"][0]["title"], "Demo Channel")
            self.assertEqual(listed["chats"][1]["username"], "")
            self.assertEqual(listed["chats"][1]["type"], "")
            list_request = json.loads(run.call_args.kwargs["input"])
            self.assertEqual(list_request["query"], "course channel")
            self.assertEqual(list_request["limit"], 100)
            browse_request = json.loads(browse_run.call_args.kwargs["input"])
            self.assertEqual(browse_request["chatKey"], "channel:123")
            self.assertEqual(browse_request["mediaKinds"], ["document"])
            self.assertEqual(browsed["messages"][0]["messageId"], 9)

    def _download_side_effect(self, *, relative_paths: list[str], media_kinds: list[str] | None = None):
        def run(_argv, **kwargs):
            request = json.loads(kwargs["input"])
            output_root = Path(request["outputRoot"])
            output_root.mkdir(parents=True, exist_ok=True)
            items = []
            kinds = media_kinds or ["video"] * len(relative_paths)
            for index, (relative_path, kind) in enumerate(zip(relative_paths, kinds), 1):
                target = output_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(f"item-{index}".encode())
                items.append({"messageId": request["messageIds"][index - 1] if index <= len(request["messageIds"]) else index, "mediaKind": kind, "relativePath": relative_path})
            return self._adapter_result({"ok": True, "items": items})
        return run

    def test_public_post_and_batch_download_are_confined_to_galaxy_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            with (
                patch.object(telegram_download.shutil, "which", return_value="adapter"),
                patch.object(telegram_download.subprocess, "run", side_effect=self._download_side_effect(relative_paths=["123/clip.mp4"])),
            ):
                result = telegram_download.download_public_telegram(engine, "https://t.me/example_channel/123")
            self.assertEqual(result["requestedMessageIds"], [123])
            self.assertEqual(result["items"][0]["fileName"], "clip.mp4")
            self.assertEqual(result["items"][0]["collection"], "telegram")
            self.assertNotIn(str(engine.downloads), json.dumps(result))

            with (
                patch.object(telegram_download.shutil, "which", return_value="adapter"),
                patch.object(
                    telegram_download.subprocess,
                    "run",
                    side_effect=self._download_side_effect(relative_paths=["1/a.jpg", "2/b.pdf"], media_kinds=["image", "document"]),
                ),
            ):
                batch = telegram_download.download_public_telegram(
                    engine,
                    "@example_channel",
                    message_ids=[1, 2, 2],
                    media_kinds=["image", "document"],
                )
            self.assertEqual(batch["requestedMessageIds"], [1, 2])
            self.assertEqual([row["mediaKind"] for row in batch["items"]], ["image", "document"])

    def test_public_post_rejects_mismatched_batch_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            with self.assertRaises(telegram_download.TelegramTransferError):
                telegram_download.download_public_telegram(engine, "https://t.me/example_channel/123", message_ids=[124])

    def test_chat_download_uses_hashed_scope_not_raw_chat_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            captured: dict[str, object] = {}

            def run(_argv, **kwargs):
                request = json.loads(kwargs["input"])
                captured.update(request)
                output_root = Path(request["outputRoot"])
                output_root.mkdir(parents=True, exist_ok=True)
                (output_root / "file.bin").write_bytes(b"x")
                return self._adapter_result({"ok": True, "items": [{"messageId": 7, "mediaKind": "document", "relativePath": "file.bin"}]})

            with (
                patch.object(telegram_download.shutil, "which", return_value="adapter"),
                patch.object(telegram_download.subprocess, "run", side_effect=run),
            ):
                result = telegram_download.download_telegram_chat(engine, "channel:secret-room", message_ids=[7])
            self.assertTrue(result["scope"].startswith("chat-"))
            self.assertNotIn("secret-room", result["scope"])
            self.assertNotIn("secret-room", str(captured["outputRoot"]))
            self.assertNotIn(str(engine.downloads), json.dumps(result))

    def test_adapter_paths_cannot_escape_or_use_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            root = telegram_download._output_root(engine, "example")
            outside = engine.root / "outside.bin"
            outside.write_bytes(b"outside")
            for relative in ("../outside.bin", str(outside.resolve())):
                with self.subTest(relative=relative):
                    with self.assertRaises(telegram_download.TelegramTransferError):
                        telegram_download._managed_download(root, relative)

            target = root / "target.bin"
            target.write_bytes(b"x")
            link = root / "link.bin"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                return
            with self.assertRaises(telegram_download.TelegramTransferError):
                telegram_download._managed_download(root, "link.bin")

    def test_adapter_failures_are_generic_and_do_not_leak_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            secret = str(engine.root / "private.secret")
            with patch.object(telegram_download.shutil, "which", return_value="adapter"):
                cases = (
                    SimpleNamespace(returncode=2, stdout="", stderr=f"leak {secret}"),
                    SimpleNamespace(returncode=0, stdout="not-json", stderr=""),
                    self._adapter_result({"ok": False, "error": secret}),
                )
                for completed in cases:
                    with patch.object(telegram_download.subprocess, "run", return_value=completed):
                        with self.assertRaises(telegram_download.TelegramTransferError) as caught:
                            telegram_download.list_telegram_chats(engine)
                        self.assertNotIn(secret, str(caught.exception))

    def test_missing_adapter_and_batch_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            with patch.object(telegram_download.shutil, "which", return_value=None):
                with self.assertRaises(telegram_download.TelegramTransferError):
                    telegram_download.list_telegram_chats(engine)
            with self.assertRaises(telegram_download.TelegramTransferError):
                telegram_download.download_public_telegram(engine, "@example_channel", message_ids=list(range(1, 102)))
            with self.assertRaises(telegram_download.TelegramTransferError):
                telegram_download.browse_public_telegram(engine, "@example_channel", media_kinds=["audio"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
