from __future__ import annotations

from http.server import ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from headless_ai_api import HeadlessAiApi, HeadlessAiApiError
from headless_api import GalaxyApiRequestHandler
from headless_service import HeadlessServiceError, _safe_detail


def _first_query_value(values: dict[str, list[str]], *names: str) -> str:
    for name in names:
        candidates = values.get(name)
        if candidates:
            return str(candidates[0])
    return ""


def _path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


class AiGalaxyApiRequestHandler(GalaxyApiRequestHandler):
    @property
    def ai_api(self) -> HeadlessAiApi | None:
        return self.server.ai_api  # type: ignore[attr-defined]

    def _ai_unavailable(self) -> bool:
        if self.ai_api is not None:
            return False
        self._json(503, {"ok": False, "error": "ai api is unavailable", "code": "AI_UNAVAILABLE"})
        return True

    def _ai_error(self, exc: HeadlessAiApiError) -> None:
        self._json(
            exc.status,
            {"ok": False, "error": _safe_detail(exc), "code": exc.code},
        )

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        if not path.startswith("/v1/ai"):
            super().do_GET()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        if self._ai_unavailable():
            return
        try:
            parts = _path_parts(path)
            values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=20)
            if parts == ["v1", "ai", "providers"]:
                result = self.ai_api.providers()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})
                return
            if parts == ["v1", "ai", "prompts"]:
                result = self.ai_api.prompts()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})
                return
            if len(parts) == 4 and parts[:3] == ["v1", "ai", "prompts"]:
                result = self.ai_api.prompt_detail(parts[3])  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})
                return
            if parts == ["v1", "ai", "queue"]:
                result = self.ai_api.queue()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})
                return
            if len(parts) == 4 and parts[:3] == ["v1", "ai", "tasks"]:
                result = self.ai_api.task_detail(parts[3])  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})
                return
            if parts == ["v1", "ai", "history"]:
                result = self.ai_api.history(  # type: ignore[union-attr]
                    media_id=_first_query_value(values, "mediaId", "media_id"),
                    provider_id=_first_query_value(values, "providerId", "provider_id"),
                    status=_first_query_value(values, "status"),
                    limit=_first_query_value(values, "limit") or 50,
                )
                self._json(200, {"ok": True, **result})
                return
            if len(parts) == 4 and parts[:3] == ["v1", "ai", "history"]:
                result = self.ai_api.history_detail(parts[3])  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})
                return
            self._json(404, {"ok": False, "error": "not found"})
        except HeadlessAiApiError as exc:
            self._ai_error(exc)
        except ValueError as exc:
            self._json(400, {"ok": False, "error": _safe_detail(exc), "code": "AI_INVALID_REQUEST"})
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        if not path.startswith("/v1/ai"):
            super().do_POST()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        if self._ai_unavailable():
            return
        try:
            parts = _path_parts(path)
            if parts == ["v1", "ai", "providers"]:
                result = self.ai_api.save_provider(self._read_json())  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})
                return
            if len(parts) == 5 and parts[:3] == ["v1", "ai", "providers"]:
                provider_id = parts[3]
                action = parts[4]
                if action == "reset":
                    result = self.ai_api.reset_provider(provider_id)  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if action == "delete":
                    result = self.ai_api.remove_provider(provider_id)  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
            if parts == ["v1", "ai", "prompts"]:
                result = self.ai_api.save_prompt(self._read_json())  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})
                return
            if parts == ["v1", "ai", "prompts", "reset"]:
                result = self.ai_api.restore_prompts()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})
                return
            if len(parts) == 5 and parts[:3] == ["v1", "ai", "prompts"]:
                prompt_id = parts[3]
                action = parts[4]
                if action == "duplicate":
                    result = self.ai_api.duplicate_prompt(  # type: ignore[union-attr]
                        prompt_id,
                        self._read_json(),
                    )
                    self._json(201, {"ok": True, **result})
                    return
                if action == "delete":
                    result = self.ai_api.remove_prompt(prompt_id)  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
            if parts == ["v1", "ai", "tasks", "text"]:
                result = self.ai_api.submit_text(self._read_json())  # type: ignore[union-attr]
                self._json(202, {"ok": True, **result})
                return
            if parts == ["v1", "ai", "tasks", "transcript"]:
                result = self.ai_api.submit_transcript(self._read_json())  # type: ignore[union-attr]
                self._json(202, {"ok": True, **result})
                return
            if len(parts) == 5 and parts[:3] == ["v1", "ai", "tasks"] and parts[4] == "cancel":
                result = self.ai_api.cancel_task(parts[3])  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})
                return
            if parts == ["v1", "ai", "history", "clear"]:
                result = self.ai_api.clear_history()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})
                return
            if len(parts) == 5 and parts[:3] == ["v1", "ai", "history"] and parts[4] == "delete":
                result = self.ai_api.remove_history(parts[3])  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})
                return
            self._json(404, {"ok": False, "error": "not found"})
        except HeadlessAiApiError as exc:
            self._ai_error(exc)
        except HeadlessServiceError as exc:
            self._json(400, {"ok": False, "error": _safe_detail(exc), "code": "AI_INVALID_REQUEST"})
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})


class AiGalaxyApiServer(ThreadingHTTPServer):
    """Composite Galaxy server using the existing routes plus /v1/ai/*.

    This intentionally lives outside headless_api.py so the AI HTTP contract can
    be tested and rolled back independently before the main server switches its
    request handler in the next integration slice.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address,
        runtime,
        auth_token: str,
        bound_host: str,
        media_api,
        *,
        ai_api: HeadlessAiApi | None = None,
        transcript_api=None,
        subscription_api=None,
        reader_api=None,
        learning_api=None,
        music_api=None,
    ) -> None:
        self.runtime = runtime
        self.auth_token = auth_token
        self.bound_host = bound_host
        self.media_api = media_api
        self.transcript_api = transcript_api
        self.subscription_api = subscription_api
        self.reader_api = reader_api
        self.learning_api = learning_api
        self.music_api = music_api
        self.ai_api = ai_api
        super().__init__(address, AiGalaxyApiRequestHandler)
