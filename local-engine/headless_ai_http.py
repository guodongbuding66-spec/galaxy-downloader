from __future__ import annotations

from urllib.parse import parse_qs

from headless_ai_api import HeadlessAiApiError
from headless_service import HeadlessServiceError, _safe_detail


def _parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _query(values: dict[str, list[str]], *names: str) -> str:
    for name in names:
        candidates = values.get(name)
        if candidates:
            return str(candidates[0])
    return ""


def _api(handler):
    return getattr(handler.server, "ai_api", None)


def _guard(handler) -> bool:
    if not handler._authorized():
        handler._json(401, {"ok": False, "error": "unauthorized"})
        return False
    if _api(handler) is None:
        handler._json(503, {"ok": False, "error": "ai api is unavailable"})
        return False
    return True


def _error(handler, exc: HeadlessAiApiError) -> None:
    detail = "raw AI credentials are not accepted" if exc.code == "AI_RAW_CREDENTIAL_REJECTED" else _safe_detail(exc)
    handler._json(exc.status, {"ok": False, "error": detail, "code": exc.code})


def handle_ai_get(handler, parsed) -> bool:
    path = parsed.path
    if not path.startswith("/v1/ai"):
        return False
    if not _guard(handler):
        return True
    api = _api(handler)
    try:
        parts = _parts(path)
        values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=20)
        if parts == ["v1", "ai", "providers"]:
            handler._json(200, {"ok": True, **api.providers()})
            return True
        if len(parts) == 4 and parts[:3] == ["v1", "ai", "providers"]:
            handler._json(200, {"ok": True, **api.provider_detail(parts[3])})
            return True
        if parts == ["v1", "ai", "prompts"]:
            handler._json(200, {"ok": True, **api.prompts()})
            return True
        if len(parts) == 4 and parts[:3] == ["v1", "ai", "prompts"]:
            handler._json(200, {"ok": True, **api.prompt_detail(parts[3])})
            return True
        if parts == ["v1", "ai", "tasks"]:
            handler._json(200, {"ok": True, **api.tasks()})
            return True
        if len(parts) == 4 and parts[:3] == ["v1", "ai", "tasks"]:
            handler._json(200, {"ok": True, **api.task_detail(parts[3])})
            return True
        if parts == ["v1", "ai", "history"]:
            handler._json(
                200,
                {
                    "ok": True,
                    **api.history(
                        media_id=_query(values, "mediaId", "media_id"),
                        provider_id=_query(values, "providerId", "provider_id"),
                        status=_query(values, "status"),
                        limit=_query(values, "limit") or 50,
                    ),
                },
            )
            return True
        if len(parts) == 4 and parts[:3] == ["v1", "ai", "history"]:
            handler._json(200, {"ok": True, **api.history_detail(parts[3])})
            return True
        handler._json(404, {"ok": False, "error": "not found"})
    except HeadlessAiApiError as exc:
        _error(handler, exc)
    except Exception as exc:
        handler._json(502, {"ok": False, "error": _safe_detail(exc)})
    return True


def handle_ai_post(handler, parsed) -> bool:
    path = parsed.path
    if not path.startswith("/v1/ai"):
        return False
    if not _guard(handler):
        return True
    api = _api(handler)
    try:
        parts = _parts(path)
        if parts == ["v1", "ai", "providers"]:
            handler._json(201, {"ok": True, **api.save_provider(handler._read_json())})
            return True
        if len(parts) == 5 and parts[:3] == ["v1", "ai", "providers"]:
            provider_id = parts[3]
            action = parts[4]
            if action == "delete":
                handler._json(200, {"ok": True, **api.remove_provider(provider_id)})
                return True
            if action == "reset":
                handler._json(200, {"ok": True, **api.reset_provider(provider_id)})
                return True
            if action == "test":
                handler._json(200, {"ok": True, **api.test_provider(provider_id)})
                return True
            if action == "update":
                handler._json(200, {"ok": True, **api.save_provider(handler._read_json(), provider_id=provider_id)})
                return True
        if parts == ["v1", "ai", "prompts"]:
            handler._json(201, {"ok": True, **api.save_prompt(handler._read_json())})
            return True
        if parts == ["v1", "ai", "prompts", "reset"]:
            handler._json(200, {"ok": True, **api.reset_prompts()})
            return True
        if len(parts) == 5 and parts[:3] == ["v1", "ai", "prompts"]:
            prompt_id = parts[3]
            action = parts[4]
            if action == "delete":
                handler._json(200, {"ok": True, **api.remove_prompt(prompt_id)})
                return True
            if action == "update":
                handler._json(200, {"ok": True, **api.save_prompt(handler._read_json(), prompt_id=prompt_id)})
                return True
            if action == "duplicate":
                handler._json(201, {"ok": True, **api.duplicate_prompt(prompt_id, handler._read_json())})
                return True
        if parts == ["v1", "ai", "tasks", "text"]:
            handler._json(202, {"ok": True, **api.submit_text(handler._read_json())})
            return True
        if parts == ["v1", "ai", "tasks", "transcript"]:
            handler._json(202, {"ok": True, **api.submit_transcript(handler._read_json())})
            return True
        if parts == ["v1", "ai", "tasks", "clear-waiting"]:
            handler._json(200, {"ok": True, **api.clear_waiting()})
            return True
        if len(parts) == 5 and parts[:3] == ["v1", "ai", "tasks"] and parts[4] == "cancel":
            handler._json(200, {"ok": True, **api.cancel_task(parts[3])})
            return True
        if parts == ["v1", "ai", "history", "clear"]:
            handler._json(200, {"ok": True, **api.clear_history()})
            return True
        if len(parts) == 5 and parts[:3] == ["v1", "ai", "history"] and parts[4] == "delete":
            handler._json(200, {"ok": True, **api.remove_history(parts[3])})
            return True
        handler._json(404, {"ok": False, "error": "not found"})
    except HeadlessAiApiError as exc:
        _error(handler, exc)
    except HeadlessServiceError as exc:
        handler._json(400, {"ok": False, "error": _safe_detail(exc)})
    except Exception as exc:
        handler._json(502, {"ok": False, "error": _safe_detail(exc)})
    return True
