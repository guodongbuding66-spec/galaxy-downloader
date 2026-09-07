from __future__ import annotations

import tempfile
from contextlib import suppress
from pathlib import Path

from headless_transfer_api import HeadlessTransferApiError, _safe_detail, _translate_error
from transfer_center import TORRENT_FILE_MAX_BYTES, TorrentResult, download_torrent

MAX_TORRENT_UPLOAD_BYTES = TORRENT_FILE_MAX_BYTES


def _upload_directory(transfer_api) -> Path:  # noqa: ANN001
    context = getattr(transfer_api, "context", None)
    if context is None:
        raise HeadlessTransferApiError(
            "transfer context is unavailable",
            code="TRANSFER_UNAVAILABLE",
        )
    state_root = Path(context.state_dir()).expanduser()
    if state_root.exists() and state_root.is_symlink():
        raise HeadlessTransferApiError("transfer state directory cannot be a symbolic link")
    state_root = state_root.resolve(strict=False)
    target = state_root / "torrent-upload"
    if target.exists() and target.is_symlink():
        raise HeadlessTransferApiError("torrent upload directory cannot be a symbolic link")
    target.mkdir(parents=True, exist_ok=True)
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(state_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HeadlessTransferApiError("torrent upload directory is outside managed state") from exc
    return resolved


def _transfer_roots(transfer_api) -> tuple[Path, ...]:  # noqa: ANN001
    context = getattr(transfer_api, "context", None)
    if context is None:
        return ()
    roots: list[Path] = []
    for name in ("program_path", "data_path", "state_path", "downloads_path", "tools_path"):
        value = getattr(context, name, None)
        if value is not None:
            roots.append(Path(value))
    return tuple(roots)


def download_uploaded_torrent(
    transfer_api,  # noqa: ANN001
    payload: bytes,
    *,
    timeout_seconds: int = 24 * 3600,
) -> dict[str, object]:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise HeadlessTransferApiError(
            "torrent upload must be binary",
            code="TRANSFER_TORRENT_INVALID",
        )
    raw = bytes(payload)
    if not raw or len(raw) > MAX_TORRENT_UPLOAD_BYTES:
        raise HeadlessTransferApiError(
            "torrent file is empty or exceeds 10 MB",
            code="TRANSFER_TORRENT_SIZE_INVALID",
        )

    try:
        timeout = max(60, min(int(timeout_seconds), 48 * 3600))
    except (TypeError, ValueError) as exc:
        raise HeadlessTransferApiError(
            "torrent timeout is invalid",
            code="TRANSFER_TORRENT_TIMEOUT_INVALID",
        ) from exc

    roots = _transfer_roots(transfer_api)
    temporary: Path | None = None
    try:
        upload_dir = _upload_directory(transfer_api)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix="galaxy-headless-",
            suffix=".torrent",
            dir=upload_dir,
            delete=False,
        ) as handle:
            handle.write(raw)
            handle.flush()
            temporary = Path(handle.name)
        result: TorrentResult = download_torrent(
            transfer_api.context,
            temporary,
            timeout_seconds=timeout,
        )
    except Exception as exc:
        raise _translate_error(exc, roots=roots) from exc
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink()

    return {
        "completed": True,
        "collection": "torrents",
        "message": _safe_detail(result.message, roots=roots),
        "sourceType": "torrent-file",
    }


def run_headless_torrent_upload_self_test() -> None:
    import tempfile as _tempfile
    from unittest.mock import patch

    from headless_transfer_api import HeadlessTransferApi, HeadlessTransferContext

    with _tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        downloads = root / "downloads"
        downloads.mkdir()
        context = HeadlessTransferContext(
            program_path=root / "program",
            data_path=root / "data",
            state_path=root / "state",
            downloads_path=downloads,
            tools_path=root / "tools",
        )
        api = HeadlessTransferApi(downloads, context=context)
        observed: dict[str, object] = {}

        def fake_download(engine_module, source, *, timeout_seconds=24 * 3600):  # noqa: ANN001
            path = Path(source)
            observed["path"] = path
            observed["bytes"] = path.read_bytes()
            observed["timeout"] = timeout_seconds
            assert path.suffix == ".torrent"
            assert path.resolve(strict=True).is_relative_to(context.state_path.resolve(strict=False))
            return TorrentResult(downloads / "torrents", "done")

        with patch("headless_torrent_upload.download_torrent", fake_download):
            result = download_uploaded_torrent(api, b"d4:infode")
        assert result["completed"] is True
        assert result["sourceType"] == "torrent-file"
        assert observed["bytes"] == b"d4:infode"
        assert not Path(observed["path"]).exists()
        assert str(root) not in str(result)

        try:
            download_uploaded_torrent(api, b"")
        except HeadlessTransferApiError as exc:
            assert exc.code == "TRANSFER_TORRENT_SIZE_INVALID"
        else:
            raise AssertionError("empty torrent upload was accepted")

        with patch(
            "headless_torrent_upload.download_torrent",
            side_effect=RuntimeError(f"failure at {root / 'state' / 'secret.torrent'}"),
        ):
            try:
                download_uploaded_torrent(api, b"d1:ae")
            except HeadlessTransferApiError as exc:
                assert str(root) not in str(exc)
            else:
                raise AssertionError("path-leaking torrent error was not translated")
        api.shutdown()


if __name__ == "__main__":
    run_headless_torrent_upload_self_test()
    print("Headless torrent upload self-test passed")
