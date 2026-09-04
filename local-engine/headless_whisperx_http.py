from __future__ import annotations

from urllib.parse import urlsplit

from headless_asr_api import HeadlessAsrApiError
from headless_whisperx_api import HeadlessWhisperXApi
from headless_service import HeadlessServiceError, _safe_detail


class HeadlessWhisperXHttpMixin:
    @property
    def whisperx_api(self) -> HeadlessWhisperXApi | None:
        return self.server.whisperx_api  # type: ignore[attr-defined]

    def _whisperx_error(self, exc: HeadlessAsrApiError) -> None:
        self._json(exc.status, {"ok": False, "error": _safe_detail(exc), "code": exc.code})  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path  # type: ignore[attr-defined]
        if path != "/v1/asr/whisperx":
            super().do_GET()  # type: ignore[misc]
            return
        if not self._authorized():  # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "unauthorized"})  # type: ignore[attr-defined]
            return
        if self.whisperx_api is None:
            self._json(503, {"ok": False, "error": "whisperx api is unavailable", "code": "ASR_WHISPERX_UNAVAILABLE"})  # type: ignore[attr-defined]
            return
        try:
            self._json(200, {"ok": True, **self.whisperx_api.status()})  # type: ignore[attr-defined]
        except HeadlessAsrApiError as exc:
            self._whisperx_error(exc)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path  # type: ignore[attr-defined]
        if not path.startswith("/v1/asr/whisperx/"):
            super().do_POST()  # type: ignore[misc]
            return
        if not self._authorized():  # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "unauthorized"})  # type: ignore[attr-defined]
            return
        if self.whisperx_api is None:
            self._json(503, {"ok": False, "error": "whisperx api is unavailable", "code": "ASR_WHISPERX_UNAVAILABLE"})  # type: ignore[attr-defined]
            return
        try:
            if path == "/v1/asr/whisperx/prepare":
                result = self.whisperx_api.prepare(self._read_json())  # type: ignore[attr-defined]
            elif path == "/v1/asr/whisperx/delete":
                result = self.whisperx_api.remove()
            elif path == "/v1/asr/whisperx/diarize":
                result = self.whisperx_api.diarize(self._read_json())  # type: ignore[attr-defined]
            else:
                self._json(404, {"ok": False, "error": "not found"})  # type: ignore[attr-defined]
                return
            self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
        except HeadlessAsrApiError as exc:
            self._whisperx_error(exc)
        except HeadlessServiceError as exc:
            self._json(400, {"ok": False, "error": _safe_detail(exc), "code": "ASR_INVALID_REQUEST"})  # type: ignore[attr-defined]
