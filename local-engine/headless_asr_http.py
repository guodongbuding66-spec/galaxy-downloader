from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from headless_asr_api import HeadlessAsrApi, HeadlessAsrApiError
from headless_service import HeadlessServiceError, _safe_detail


def _first_query_value(values: dict[str, list[str]], *names: str) -> str:
    for name in names:
        candidates = values.get(name)
        if candidates:
            return str(candidates[0])
    return ""


def _path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


class HeadlessAsrHttpMixin:
    """Composable `/v1/asr/*` routes for any Galaxy Headless handler.

    The mixin deliberately has no dependency on `headless_api` or the AI HTTP
    handler. Production can therefore place it before the current composite
    handler in the MRO without creating an import cycle.
    """

    @property
    def asr_api(self) -> HeadlessAsrApi | None:
        return self.server.asr_api  # type: ignore[attr-defined]

    def _asr_unavailable(self) -> bool:
        if self.asr_api is not None:
            return False
        self._json(  # type: ignore[attr-defined]
            503,
            {"ok": False, "error": "asr api is unavailable", "code": "ASR_UNAVAILABLE"},
        )
        return True

    def _asr_error(self, exc: HeadlessAsrApiError) -> None:
        self._json(  # type: ignore[attr-defined]
            exc.status,
            {"ok": False, "error": _safe_detail(exc), "code": exc.code},
        )

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)  # type: ignore[attr-defined]
        path = parsed.path
        if not path.startswith("/v1/asr"):
            super().do_GET()  # type: ignore[misc]
            return
        if not self._authorized():  # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "unauthorized"})  # type: ignore[attr-defined]
            return
        if self._asr_unavailable():
            return
        try:
            parts = _path_parts(path)
            values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=20)
            if parts == ["v1", "asr", "providers"]:
                result = self.asr_api.providers()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "asr", "preferences"]:
                result = self.asr_api.preferences()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "asr", "models"]:
                result = self.asr_api.models(  # type: ignore[union-attr]
                    _first_query_value(values, "provider", "providerId", "provider_id")
                )
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            self._json(404, {"ok": False, "error": "not found"})  # type: ignore[attr-defined]
        except HeadlessAsrApiError as exc:
            self._asr_error(exc)
        except ValueError as exc:
            self._json(  # type: ignore[attr-defined]
                400,
                {"ok": False, "error": _safe_detail(exc), "code": "ASR_INVALID_REQUEST"},
            )
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})  # type: ignore[attr-defined]

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)  # type: ignore[attr-defined]
        path = parsed.path
        if not path.startswith("/v1/asr"):
            super().do_POST()  # type: ignore[misc]
            return
        if not self._authorized():  # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "unauthorized"})  # type: ignore[attr-defined]
            return
        if self._asr_unavailable():
            return
        try:
            parts = _path_parts(path)
            if parts == ["v1", "asr", "recommend"]:
                result = self.asr_api.recommend(self._read_json())  # type: ignore[union-attr,attr-defined]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "asr", "preferences"]:
                result = self.asr_api.save_preferences(self._read_json())  # type: ignore[union-attr,attr-defined]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "asr", "preferences", "reset"]:
                result = self.asr_api.reset_preferences()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if (
                len(parts) == 6
                and parts[:3] == ["v1", "asr", "models"]
                and parts[5] in {"install", "delete"}
            ):
                provider_id = parts[3]
                model_id = parts[4]
                if parts[5] == "install":
                    result = self.asr_api.install_model(  # type: ignore[union-attr]
                        provider_id,
                        model_id,
                        self._read_json(),  # type: ignore[attr-defined]
                    )
                else:
                    result = self.asr_api.remove_model(provider_id, model_id)  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "asr", "transcribe"]:
                result = self.asr_api.transcribe(self._read_json())  # type: ignore[union-attr,attr-defined]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            self._json(404, {"ok": False, "error": "not found"})  # type: ignore[attr-defined]
        except HeadlessAsrApiError as exc:
            self._asr_error(exc)
        except HeadlessServiceError as exc:
            self._json(  # type: ignore[attr-defined]
                400,
                {"ok": False, "error": _safe_detail(exc), "code": "ASR_INVALID_REQUEST"},
            )
        except ValueError as exc:
            self._json(  # type: ignore[attr-defined]
                400,
                {"ok": False, "error": _safe_detail(exc), "code": "ASR_INVALID_REQUEST"},
            )
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})  # type: ignore[attr-defined]
