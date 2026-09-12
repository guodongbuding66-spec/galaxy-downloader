from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import telegram_transfer  # noqa: E402


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


class _Response:
    def __init__(self, *, status_code: int = 200, payload: object | None = None) -> None:
        self.status_code = status_code
        self._payload = {"ok": True, "result": {"message_id": 1}} if payload is None else payload

    def json(self):
        return self._payload


class TelegramTransferTests(unittest.TestCase):
    def test_self_test(self) -> None:
        telegram_transfer.run_telegram_transfer_self_test()

    def test_settings_and_secret_are_separated_and_token_can_be_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            token = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd"
            settings = telegram_transfer.TelegramUploadSettings(
                mode="bot",
                chat_id="@example_user",
                send_as="video",
                user_adapter="galaxy-telegram-user",
            )
            saved = telegram_transfer.save_telegram_upload_settings(engine, settings, bot_token=token)
            self.assertEqual(saved, settings)
            self.assertTrue(telegram_transfer.telegram_bot_token_configured(engine))

            public_payload = json.loads((engine.state / telegram_transfer.SETTINGS_FILENAME).read_text(encoding="utf-8"))
            secret_payload = json.loads((engine.state / telegram_transfer.SECRETS_FILENAME).read_text(encoding="utf-8"))
            self.assertNotIn("botToken", public_payload)
            self.assertNotIn(token, json.dumps(public_payload))
            self.assertEqual(secret_payload["botToken"], token)
            self.assertNotIn("botToken", saved.public_payload())
            if os.name != "nt":
                mode = stat.S_IMODE((engine.state / telegram_transfer.SECRETS_FILENAME).stat().st_mode)
                self.assertEqual(mode, 0o600)

            telegram_transfer.clear_telegram_bot_token(engine)
            self.assertFalse(telegram_transfer.telegram_bot_token_configured(engine))
            self.assertFalse((engine.state / telegram_transfer.SECRETS_FILENAME).exists())

    def test_invalid_token_does_not_get_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            with self.assertRaises(telegram_transfer.TelegramTransferError):
                telegram_transfer.save_telegram_upload_settings(
                    engine,
                    telegram_transfer.TelegramUploadSettings(chat_id="@example_user"),
                    bot_token="bad-token",
                )
            self.assertFalse((engine.state / telegram_transfer.SECRETS_FILENAME).exists())
            self.assertFalse((engine.state / telegram_transfer.SETTINGS_FILENAME).exists())

    def test_settings_validation_and_adapter_name_sanitization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            saved = telegram_transfer.save_telegram_upload_settings(
                engine,
                telegram_transfer.TelegramUploadSettings(
                    mode="unexpected",
                    chat_id="-100123456789",
                    send_as="unexpected",
                    user_adapter="../../galaxy user.exe",
                ),
            )
            self.assertEqual(saved.mode, "bot")
            self.assertEqual(saved.send_as, "document")
            self.assertNotIn("/", saved.user_adapter)
            self.assertNotIn("\\", saved.user_adapter)
            self.assertEqual(saved.chat_id, "-100123456789")

            with self.assertRaises(telegram_transfer.TelegramTransferError):
                telegram_transfer.save_telegram_upload_settings(
                    engine,
                    telegram_transfer.TelegramUploadSettings(chat_id="not a chat id"),
                )

    def test_source_file_is_restricted_to_galaxy_download_root_and_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = _Engine(root)
            inside = engine.downloads / "inside.bin"
            outside = root / "outside.bin"
            inside.write_bytes(b"inside")
            outside.write_bytes(b"outside")

            self.assertEqual(
                telegram_transfer._galaxy_file(engine, file_path=str(inside)),
                inside.resolve(),
            )
            with self.assertRaises(telegram_transfer.TelegramTransferError):
                telegram_transfer._galaxy_file(engine, file_path=str(outside))

            symlink = engine.downloads / "link.bin"
            try:
                symlink.symlink_to(inside)
            except (OSError, NotImplementedError):
                return
            with self.assertRaises(telegram_transfer.TelegramTransferError):
                telegram_transfer._galaxy_file(engine, file_path=str(symlink))

    def test_media_id_path_uses_media_library_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            media = engine.downloads / "media.mp4"
            media.write_bytes(b"media")
            with patch.object(telegram_transfer, "resolve_media_item_path", return_value=media) as resolver:
                resolved = telegram_transfer._galaxy_file(engine, media_id="media-1")
            self.assertEqual(resolved, media)
            resolver.assert_called_once_with(engine, "media-1")

    def test_thumbnail_follows_official_jpeg_size_and_dimension_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / "valid.jpg"
            too_wide = root / "wide.jpg"
            Image.new("RGB", (320, 320), "white").save(valid, "JPEG", quality=70)
            Image.new("RGB", (321, 120), "white").save(too_wide, "JPEG", quality=70)

            self.assertEqual(telegram_transfer._thumbnail(valid), valid.resolve())
            with self.assertRaises(telegram_transfer.TelegramTransferError):
                telegram_transfer._thumbnail(too_wide)

            fake = root / "fake.jpg"
            fake.write_text("not jpeg", encoding="utf-8")
            with self.assertRaises(telegram_transfer.TelegramTransferError):
                telegram_transfer._thumbnail(fake)

    def test_bot_upload_uses_https_multipart_no_redirect_and_redacts_token_from_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demo.mp4"
            source.write_bytes(b"demo")
            token = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd"
            with patch.object(telegram_transfer.requests, "post", return_value=_Response()) as post:
                result = telegram_transfer._bot_upload_one(
                    token,
                    "@example_user",
                    source,
                    send_as="video",
                    filename="renamed.mp4",
                    caption="demo",
                )
            self.assertTrue(result["ok"])
            post.assert_called_once()
            args, kwargs = post.call_args
            self.assertEqual(args[0], f"https://api.telegram.org/bot{token}/sendVideo")
            self.assertEqual(kwargs["data"]["chat_id"], "@example_user")
            self.assertEqual(kwargs["data"]["caption"], "demo")
            self.assertEqual(kwargs["files"]["video"][0], "renamed.mp4")
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(kwargs["timeout"], (20, 300))

            leaked = requests.ConnectionError(f"POST https://api.telegram.org/bot{token}/sendVideo failed")
            with patch.object(telegram_transfer.requests, "post", side_effect=leaked):
                with self.assertRaises(telegram_transfer.TelegramTransferError) as caught:
                    telegram_transfer._bot_upload_one(
                        token,
                        "@example_user",
                        source,
                        send_as="video",
                        filename="renamed.mp4",
                    )
            self.assertNotIn(token, str(caught.exception))
            self.assertIn("<redacted>", str(caught.exception))

    def test_bot_api_error_description_is_bounded_and_secret_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demo.bin"
            source.write_bytes(b"demo")
            token = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd"
            response = _Response(status_code=400, payload={"ok": False, "description": f"bad {token}"})
            with patch.object(telegram_transfer.requests, "post", return_value=response):
                with self.assertRaises(telegram_transfer.TelegramTransferError) as caught:
                    telegram_transfer._bot_upload_one(
                        token,
                        "@example_user",
                        source,
                        send_as="document",
                        filename="demo.bin",
                    )
            self.assertNotIn(token, str(caught.exception))

    def test_chunk_writer_is_streamed_bounded_and_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(b"abcdefghij")
            parts = telegram_transfer._chunk_file(source, root / "parts", chunk_bytes=4)
            self.assertEqual([part.read_bytes() for part in parts], [b"abcd", b"efgh", b"ij"])
            self.assertEqual(len(parts), 3)
            with self.assertRaises(telegram_transfer.TelegramTransferError):
                telegram_transfer._chunk_file(source, root / "bad", chunk_bytes=0)

    def test_large_bot_upload_requires_opt_in_chunking_and_forces_document_parts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            token = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd"
            telegram_transfer.save_telegram_upload_settings(
                engine,
                telegram_transfer.TelegramUploadSettings(chat_id="@example_user", send_as="video"),
                bot_token=token,
            )
            source = engine.downloads / "large.mp4"
            with source.open("wb") as handle:
                handle.truncate(telegram_transfer.BOT_SINGLE_FILE_LIMIT + 1)

            with self.assertRaises(telegram_transfer.TelegramTransferError):
                telegram_transfer.upload_to_telegram(engine, file_path=source, auto_chunk=False)

            chunk_dir = engine.root / "synthetic-parts"
            chunk_dir.mkdir()
            part1 = chunk_dir / "p1"
            part2 = chunk_dir / "p2"
            part1.write_bytes(b"1")
            part2.write_bytes(b"2")
            calls: list[dict[str, object]] = []

            def fake_upload(_token, _chat_id, _source, **kwargs):
                calls.append(dict(kwargs))
                return {"ok": True}

            with (
                patch.object(telegram_transfer, "_chunk_file", return_value=[part1, part2]),
                patch.object(telegram_transfer, "_bot_upload_one", side_effect=fake_upload),
            ):
                result = telegram_transfer.upload_to_telegram(engine, file_path=source, auto_chunk=True)
            self.assertEqual(len(result), 2)
            self.assertEqual([call["send_as"] for call in calls], ["document", "document"])
            self.assertIn("part001-of-002", str(calls[0]["filename"]))
            self.assertIn("Part 1/2", str(calls[0]["caption"]))

    def test_user_adapter_is_explicit_argument_array_without_shell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            telegram_transfer.save_telegram_upload_settings(
                engine,
                telegram_transfer.TelegramUploadSettings(
                    mode="user",
                    chat_id="@example_user",
                    send_as="audio",
                    user_adapter="galaxy-telegram-user",
                ),
            )
            source = engine.downloads / "track.mp3"
            source.write_bytes(b"track")
            completed = SimpleNamespace(returncode=0, stdout="uploaded", stderr="")
            with (
                patch.object(telegram_transfer.shutil, "which", return_value="/usr/bin/galaxy-telegram-user"),
                patch.object(telegram_transfer.subprocess, "run", return_value=completed) as run,
            ):
                result = telegram_transfer.upload_to_telegram(engine, file_path=source)
            self.assertEqual(result[0]["mode"], "user")
            run.assert_called_once()
            args, kwargs = run.call_args
            self.assertEqual(args[0], ["/usr/bin/galaxy-telegram-user", "--galaxy-telegram-json"])
            self.assertNotIn("shell", kwargs)
            request = json.loads(kwargs["input"])
            self.assertEqual(request["protocol"], "galaxy-telegram-user-v1")
            self.assertEqual(request["chatId"], "@example_user")
            self.assertEqual(request["sendAs"], "audio")
            self.assertEqual(request["source"], str(source.resolve()))

    def test_default_bot_upload_flow_never_returns_token_or_local_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = _Engine(Path(directory))
            token = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd"
            telegram_transfer.save_telegram_upload_settings(
                engine,
                telegram_transfer.TelegramUploadSettings(chat_id="@example_user"),
                bot_token=token,
            )
            source = engine.downloads / "demo.bin"
            source.write_bytes(b"demo")
            with patch.object(telegram_transfer, "_bot_upload_one", return_value={"ok": True, "result": {"message_id": 1}}):
                result = telegram_transfer.upload_to_telegram(engine, file_path=source)
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertNotIn(token, serialized)
            self.assertNotIn(str(source), serialized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
