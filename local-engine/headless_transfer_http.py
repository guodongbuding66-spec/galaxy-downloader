from __future__ import annotations

from urllib.parse import urlsplit

from headless_service import HeadlessServiceError, _safe_detail
from headless_transfer_api import HeadlessTransferApi, HeadlessTransferApiError


def _path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


class HeadlessTransferHttpMixin:
    """Composable `/v1/transfers/*` routes for Galaxy Headless."""

    @property
    def transfer_api(self) -> HeadlessTransferApi | None:
        return self.server.transfer_api  # type: ignore[attr-defined]

    def _transfer_unavailable(self) -> bool:
        if self.transfer_api is not None:
            return False
        self._json(  # type: ignore[attr-defined]
            503,
            {"ok": False, "error": "transfer api is unavailable", "code": "TRANSFER_UNAVAILABLE"},
        )
        return True

    def _transfer_error(self, exc: HeadlessTransferApiError) -> None:
        self._json(  # type: ignore[attr-defined]
            exc.status,
            {"ok": False, "error": _safe_detail(exc), "code": exc.code},
        )

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path  # type: ignore[attr-defined]
        if not path.startswith("/v1/transfers"):
            super().do_GET()  # type: ignore[misc]
            return
        if not self._authorized():  # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "unauthorized"})  # type: ignore[attr-defined]
            return
        if self._transfer_unavailable():
            return
        try:
            parts = _path_parts(path)
            if parts == ["v1", "transfers", "status"]:
                result = self.transfer_api.status()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "transfers", "senders"]:
                result = self.transfer_api.senders()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if len(parts) == 4 and parts[:3] == ["v1", "transfers", "senders"]:
                result = self.transfer_api.sender_detail(parts[3])  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            self._json(404, {"ok": False, "error": "not found"})  # type: ignore[attr-defined]
        except HeadlessTransferApiError as exc:
            self._transfer_error(exc)
        except ValueError as exc:
            self._json(  # type: ignore[attr-defined]
                400,
                {"ok": False, "error": _safe_detail(exc), "code": "TRANSFER_INVALID_REQUEST"},
            )
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})  # type: ignore[attr-defined]

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path  # type: ignore[attr-defined]
        if not path.startswith("/v1/transfers"):
            super().do_POST()  # type: ignore[misc]
            return
        if not self._authorized():  # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "unauthorized"})  # type: ignore[attr-defined]
            return
        if self._transfer_unavailable():
            return
        try:
            parts = _path_parts(path)
            if parts == ["v1", "transfers", "senders"]:
                result = self.transfer_api.start_sender(self._read_json())  # type: ignore[union-attr,attr-defined]
                self._json(201, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if (
                len(parts) == 5
                and parts[:3] == ["v1", "transfers", "senders"]
                and parts[4] == "stop"
            ):
                result = self.transfer_api.stop_sender(parts[3])  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "transfers", "receive"]:
                result = self.transfer_api.receive(self._read_json())  # type: ignore[union-attr,attr-defined]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "transfers", "magnet"]:
                result = self.transfer_api.download_magnet(self._read_json())  # type: ignore[union-attr,attr-defined]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            self._json(404, {"ok": False, "error": "not found"})  # type: ignore[attr-defined]
        except HeadlessTransferApiError as exc:
            self._transfer_error(exc)
        except HeadlessServiceError as exc:
            self._json(  # type: ignore[attr-defined]
                400,
                {"ok": False, "error": _safe_detail(exc), "code": "TRANSFER_INVALID_REQUEST"},
            )
        except ValueError as exc:
            self._json(  # type: ignore[attr-defined]
                400,
                {"ok": False, "error": _safe_detail(exc), "code": "TRANSFER_INVALID_REQUEST"},
            )
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})  # type: ignore[attr-defined]
