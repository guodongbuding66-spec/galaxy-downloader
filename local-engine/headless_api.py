from __future__ import annotations

import argparse
import os
import signal
import threading
from contextlib import suppress
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from headless_learning_api import HeadlessLearningApi, HeadlessLearningApiError
from headless_media_api import HeadlessMediaApi, HeadlessMediaApiError
from headless_music_api import HeadlessMusicApi, HeadlessMusicApiError
from headless_reader_api import HeadlessReaderApi, HeadlessReaderApiError
from headless_service import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    HeadlessRequestHandler,
    HeadlessRuntime,
    HeadlessServiceError,
    _bounded_int,
    _download_root,
    _loopback_host,
    _safe_detail,
)
from headless_subscription_api import HeadlessSubscriptionApi, HeadlessSubscriptionApiError
from headless_transcript_api import HeadlessTranscriptApi, HeadlessTranscriptApiError


def _first_query_value(values: dict[str, list[str]], *names: str) -> str:
    for name in names:
        candidates = values.get(name)
        if candidates:
            return str(candidates[0])
    return ""


def _path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _optional_bool(value: object) -> bool | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError("boolean query value must be true or false")


class GalaxyApiRequestHandler(HeadlessRequestHandler):
    @property
    def media_api(self) -> HeadlessMediaApi:
        return self.server.media_api  # type: ignore[attr-defined]

    @property
    def transcript_api(self) -> HeadlessTranscriptApi | None:
        return self.server.transcript_api  # type: ignore[attr-defined]

    @property
    def subscription_api(self) -> HeadlessSubscriptionApi | None:
        return self.server.subscription_api  # type: ignore[attr-defined]

    @property
    def reader_api(self) -> HeadlessReaderApi | None:
        return self.server.reader_api  # type: ignore[attr-defined]

    @property
    def learning_api(self) -> HeadlessLearningApi | None:
        return self.server.learning_api  # type: ignore[attr-defined]

    @property
    def music_api(self) -> HeadlessMusicApi | None:
        return self.server.music_api  # type: ignore[attr-defined]

    def _transcript_unavailable(self) -> bool:
        if self.transcript_api is not None:
            return False
        self._json(503, {"ok": False, "error": "transcript api is unavailable"})
        return True

    def _subscription_unavailable(self) -> bool:
        if self.subscription_api is not None:
            return False
        self._json(503, {"ok": False, "error": "subscription api is unavailable"})
        return True

    def _reader_unavailable(self) -> bool:
        if self.reader_api is not None:
            return False
        self._json(503, {"ok": False, "error": "reader api is unavailable"})
        return True

    def _learning_unavailable(self) -> bool:
        if self.learning_api is not None:
            return False
        self._json(503, {"ok": False, "error": "learning api is unavailable"})
        return True

    def _music_unavailable(self) -> bool:
        if self.music_api is not None:
            return False
        self._json(503, {"ok": False, "error": "music api is unavailable"})
        return True

    def _transcript_error(self, exc: Exception) -> None:
        detail = _safe_detail(exc)
        status = 404 if detail == "media item not found" else 400
        self._json(status, {"ok": False, "error": detail})

    def _subscription_error(self, exc: Exception) -> None:
        detail = _safe_detail(exc)
        if detail in {"subscription not found", "subscription item not found"}:
            status = 404
        elif "invalid subscription item transition" in detail or "already subscribed" in detail:
            status = 409
        else:
            status = 400
        self._json(status, {"ok": False, "error": detail})

    def _reader_error(self, exc: Exception) -> None:
        detail = _safe_detail(exc)
        status = 404 if detail in {"book not found", "bookmark not found", "annotation not found"} else 400
        self._json(status, {"ok": False, "error": detail})

    def _learning_error(self, exc: HeadlessLearningApiError) -> None:
        payload = {"ok": False, "error": _safe_detail(exc), "code": exc.code}
        self._json(exc.status, payload)

    def _music_error(self, exc: HeadlessMusicApiError) -> None:
        payload = {"ok": False, "error": _safe_detail(exc), "code": exc.code}
        self._json(exc.status, payload)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        if path.startswith("/v1/music"):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            if self._music_unavailable():
                return
            try:
                parts = _path_parts(path)
                values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=20)
                if parts == ["v1", "music", "songs"]:
                    favorites = _optional_bool(_first_query_value(values, "favoritesOnly", "favorites_only"))
                    result = self.music_api.list_songs(  # type: ignore[union-attr]
                        query=_first_query_value(values, "q", "query"),
                        favorites_only=False if favorites is None else favorites,
                        limit=_first_query_value(values, "limit") or 500,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 4 and parts[:3] == ["v1", "music", "songs"]:
                    result = self.music_api.song_detail(parts[3])  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 5 and parts[:3] == ["v1", "music", "songs"] and parts[4] == "lyrics":
                    result = self.music_api.song_lyrics(parts[3])  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if parts == ["v1", "music", "albums"]:
                    result = self.music_api.list_albums(  # type: ignore[union-attr]
                        limit=_first_query_value(values, "limit") or 500,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if parts == ["v1", "music", "artists"]:
                    result = self.music_api.list_artists(  # type: ignore[union-attr]
                        limit=_first_query_value(values, "limit") or 500,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if parts == ["v1", "music", "recent"]:
                    result = self.music_api.recent(  # type: ignore[union-attr]
                        limit=_first_query_value(values, "limit") or 100,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if parts == ["v1", "music", "most-played"]:
                    result = self.music_api.most_played(  # type: ignore[union-attr]
                        limit=_first_query_value(values, "limit") or 100,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if parts == ["v1", "music", "queue"]:
                    result = self.music_api.queue()  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if parts == ["v1", "music", "player"]:
                    result = self.music_api.player()  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                self._json(404, {"ok": False, "error": "not found"})
            except HeadlessMusicApiError as exc:
                self._music_error(exc)
            except ValueError as exc:
                self._json(400, {"ok": False, "error": _safe_detail(exc)})
            except Exception as exc:
                self._json(502, {"ok": False, "error": _safe_detail(exc)})
            return

        if path.startswith("/v1/learning"):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            if self._learning_unavailable():
                return
            try:
                parts = _path_parts(path)
                values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=20)
                if parts == ["v1", "learning", "courses"]:
                    result = self.learning_api.courses(  # type: ignore[union-attr]
                        limit=_first_query_value(values, "limit") or 100,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 4 and parts[:3] == ["v1", "learning", "courses"]:
                    result = self.learning_api.course_detail(  # type: ignore[union-attr]
                        parts[3],
                        item_limit=_first_query_value(values, "itemLimit", "limit") or 500,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 5 and parts[:3] == ["v1", "learning", "courses"] and parts[4] == "items":
                    result = self.learning_api.items(  # type: ignore[union-attr]
                        parts[3],
                        limit=_first_query_value(values, "limit") or 500,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 5 and parts[:3] == ["v1", "learning", "items"] and parts[4] == "notes":
                    result = self.learning_api.notes(  # type: ignore[union-attr]
                        parts[3],
                        limit=_first_query_value(values, "limit") or 1000,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if parts == ["v1", "learning", "flashcards"]:
                    due_only = _optional_bool(_first_query_value(values, "dueOnly", "due_only"))
                    result = self.learning_api.flashcards(  # type: ignore[union-attr]
                        course_id=_first_query_value(values, "courseId", "course_id"),
                        due_only=False if due_only is None else due_only,
                        limit=_first_query_value(values, "limit") or 500,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 4 and parts[:3] == ["v1", "learning", "flashcards"]:
                    result = self.learning_api.flashcard_detail(parts[3])  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                self._json(404, {"ok": False, "error": "not found"})
            except HeadlessLearningApiError as exc:
                self._learning_error(exc)
            except ValueError as exc:
                self._json(400, {"ok": False, "error": _safe_detail(exc)})
            except Exception as exc:
                self._json(502, {"ok": False, "error": _safe_detail(exc)})
            return

        if path.startswith("/v1/reader"):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            if self._reader_unavailable():
                return
            try:
                parts = _path_parts(path)
                values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=20)
                if parts == ["v1", "reader", "books"]:
                    result = self.reader_api.books(  # type: ignore[union-attr]
                        limit=_first_query_value(values, "limit") or 100,
                        offset=_first_query_value(values, "offset") or 0,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if parts == ["v1", "reader", "search"]:
                    result = self.reader_api.search(  # type: ignore[union-attr]
                        _first_query_value(values, "q", "query"),
                        limit=_first_query_value(values, "limit") or 100,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 4 and parts[:3] == ["v1", "reader", "books"]:
                    result = self.reader_api.detail(parts[3])  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 5 and parts[:3] == ["v1", "reader", "books"]:
                    book_id = parts[3]
                    action = parts[4]
                    if action == "bookmarks":
                        result = self.reader_api.bookmarks(  # type: ignore[union-attr]
                            book_id,
                            limit=_first_query_value(values, "limit") or 1000,
                        )
                        self._json(200, {"ok": True, **result})
                        return
                    if action == "annotations":
                        result = self.reader_api.annotations(  # type: ignore[union-attr]
                            book_id,
                            limit=_first_query_value(values, "limit") or 2000,
                        )
                        self._json(200, {"ok": True, **result})
                        return
                    if action == "pages":
                        result = self.reader_api.pages(  # type: ignore[union-attr]
                            book_id,
                            limit=_first_query_value(values, "limit") or 1000,
                        )
                        self._json(200, {"ok": True, **result})
                        return
                self._json(404, {"ok": False, "error": "not found"})
            except (HeadlessReaderApiError, ValueError) as exc:
                self._reader_error(exc)
            except Exception as exc:
                self._json(502, {"ok": False, "error": _safe_detail(exc)})
            return

        if path.startswith("/v1/subscriptions"):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            if self._subscription_unavailable():
                return
            try:
                parts = _path_parts(path)
                values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=20)
                if parts == ["v1", "subscriptions"]:
                    result = self.subscription_api.list_subscriptions()  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 3 and parts[:2] == ["v1", "subscriptions"]:
                    result = self.subscription_api.detail(parts[2])  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 4 and parts[:2] == ["v1", "subscriptions"]:
                    subscription_id = parts[2]
                    if parts[3] == "rules":
                        rules = self.subscription_api.rules(subscription_id)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, "rules": rules})
                        return
                    if parts[3] == "counts":
                        counts = self.subscription_api.counts(subscription_id)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, "counts": counts})
                        return
                    if parts[3] == "items":
                        result = self.subscription_api.items(  # type: ignore[union-attr]
                            subscription_id,
                            state=_first_query_value(values, "state"),
                            present=_optional_bool(_first_query_value(values, "present")),
                            limit=_first_query_value(values, "limit") or 200,
                        )
                        self._json(200, {"ok": True, **result})
                        return
                self._json(404, {"ok": False, "error": "not found"})
            except (HeadlessSubscriptionApiError, ValueError) as exc:
                self._subscription_error(exc)
            except Exception as exc:
                self._json(502, {"ok": False, "error": _safe_detail(exc)})
            return

        if path.startswith("/v1/transcripts"):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            if self._transcript_unavailable():
                return
            try:
                values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=20)
                if path == "/v1/transcripts/search":
                    result = self.transcript_api.search(  # type: ignore[union-attr]
                        query=_first_query_value(values, "q", "query"),
                        media_id=_first_query_value(values, "mediaId", "media_id"),
                        speaker=_first_query_value(values, "speaker"),
                        start_seconds=_first_query_value(values, "startSeconds", "start"),
                        end_seconds=_first_query_value(values, "endSeconds", "end"),
                        limit=_first_query_value(values, "limit") or 100,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                parts = _path_parts(path)
                if len(parts) == 3 and parts[:2] == ["v1", "transcripts"]:
                    result = self.transcript_api.list_segments(  # type: ignore[union-attr]
                        parts[2],
                        limit=_first_query_value(values, "limit") or 1000,
                    )
                    self._json(200, {"ok": True, **result})
                    return
                self._json(404, {"ok": False, "error": "not found"})
            except (HeadlessTranscriptApiError, ValueError) as exc:
                self._transcript_error(exc)
            except Exception as exc:
                self._json(502, {"ok": False, "error": _safe_detail(exc)})
            return

        if not path.startswith("/v1/media"):
            super().do_GET()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            if path == "/v1/media/summary":
                self._json(200, {"ok": True, "summary": self.media_api.summary()})
                return
            if path == "/v1/media":
                values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=20)
                result = self.media_api.list_items(
                    query=_first_query_value(values, "q", "query"),
                    limit=_first_query_value(values, "limit") or 100,
                    offset=_first_query_value(values, "offset") or 0,
                    media_type=_first_query_value(values, "type", "mediaType"),
                )
                self._json(200, {"ok": True, **result})
                return
            self._json(404, {"ok": False, "error": "not found"})
        except (HeadlessMediaApiError, ValueError) as exc:
            self._json(400, {"ok": False, "error": _safe_detail(exc)})
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        if path.startswith("/v1/music"):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            if self._music_unavailable():
                return
            try:
                parts = _path_parts(path)
                if parts == ["v1", "music", "sync"]:
                    result = self.music_api.sync()  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if parts == ["v1", "music", "queue"]:
                    result = self.music_api.enqueue(self._read_json())  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if parts == ["v1", "music", "queue", "clear"]:
                    result = self.music_api.clear_queue()  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if parts == ["v1", "music", "player"]:
                    result = self.music_api.update_player(self._read_json())  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 5 and parts[:3] == ["v1", "music", "songs"]:
                    media_id = parts[3]
                    action = parts[4]
                    payload = self._read_json()
                    if action == "metadata":
                        result = self.music_api.update_metadata(media_id, payload)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                    if action == "state":
                        result = self.music_api.update_song_state(media_id, payload)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                if len(parts) == 5 and parts[:3] == ["v1", "music", "queue"]:
                    item_id = parts[3]
                    action = parts[4]
                    if action == "delete":
                        result = self.music_api.remove_queue_item(item_id)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                    if action == "move":
                        result = self.music_api.move_queue_item(item_id, self._read_json())  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                self._json(404, {"ok": False, "error": "not found"})
            except HeadlessMusicApiError as exc:
                self._music_error(exc)
            except HeadlessServiceError as exc:
                self._json(400, {"ok": False, "error": _safe_detail(exc)})
            except Exception as exc:
                self._json(502, {"ok": False, "error": _safe_detail(exc)})
            return

        if path.startswith("/v1/learning"):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            if self._learning_unavailable():
                return
            try:
                parts = _path_parts(path)
                if parts == ["v1", "learning", "courses"]:
                    result = self.learning_api.create_course(self._read_json())  # type: ignore[union-attr]
                    self._json(201, {"ok": True, **result})
                    return
                if len(parts) == 5 and parts[:3] == ["v1", "learning", "courses"]:
                    course_id = parts[3]
                    action = parts[4]
                    if action == "delete":
                        result = self.learning_api.remove_course(course_id)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                    payload = self._read_json()
                    if action == "update":
                        result = self.learning_api.update_course(course_id, payload)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                    if action == "items":
                        result = self.learning_api.add_item(course_id, payload)  # type: ignore[union-attr]
                        self._json(201, {"ok": True, **result})
                        return
                if len(parts) == 5 and parts[:3] == ["v1", "learning", "items"]:
                    item_id = parts[3]
                    action = parts[4]
                    payload = self._read_json()
                    if action == "progress":
                        result = self.learning_api.set_progress(item_id, payload)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                    if action == "notes":
                        result = self.learning_api.create_note(item_id, payload)  # type: ignore[union-attr]
                        self._json(201, {"ok": True, **result})
                        return
                if len(parts) == 5 and parts[:3] == ["v1", "learning", "notes"] and parts[4] == "delete":
                    result = self.learning_api.remove_note(parts[3])  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if parts == ["v1", "learning", "flashcards"]:
                    result = self.learning_api.create_flashcard(self._read_json())  # type: ignore[union-attr]
                    self._json(201, {"ok": True, **result})
                    return
                if len(parts) == 5 and parts[:3] == ["v1", "learning", "flashcards"]:
                    card_id = parts[3]
                    action = parts[4]
                    if action == "delete":
                        result = self.learning_api.remove_flashcard(card_id)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                    payload = self._read_json()
                    if action == "update":
                        result = self.learning_api.update_flashcard(card_id, payload)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                    if action == "review":
                        result = self.learning_api.review_flashcard(card_id, payload)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                self._json(404, {"ok": False, "error": "not found"})
            except HeadlessLearningApiError as exc:
                self._learning_error(exc)
            except HeadlessServiceError as exc:
                self._json(400, {"ok": False, "error": _safe_detail(exc)})
            except Exception as exc:
                self._json(502, {"ok": False, "error": _safe_detail(exc)})
            return

        if path.startswith("/v1/reader/"):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            if self._reader_unavailable():
                return
            try:
                parts = _path_parts(path)
                if len(parts) == 5 and parts[:3] == ["v1", "reader", "books"]:
                    book_id = parts[3]
                    action = parts[4]
                    payload = self._read_json()
                    if action == "progress":
                        result = self.reader_api.set_progress(book_id, payload)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                    if action == "settings":
                        result = self.reader_api.set_settings(book_id, payload)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                    if action == "bookmarks":
                        result = self.reader_api.create_bookmark(book_id, payload)  # type: ignore[union-attr]
                        self._json(201, {"ok": True, **result})
                        return
                    if action == "annotations":
                        result = self.reader_api.create_annotation(book_id, payload)  # type: ignore[union-attr]
                        self._json(201, {"ok": True, **result})
                        return
                if len(parts) == 5 and parts[:3] == ["v1", "reader", "bookmarks"] and parts[4] == "delete":
                    result = self.reader_api.remove_bookmark(parts[3])  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 5 and parts[:3] == ["v1", "reader", "annotations"] and parts[4] == "delete":
                    result = self.reader_api.remove_annotation(parts[3])  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                self._json(404, {"ok": False, "error": "not found"})
            except (HeadlessReaderApiError, ValueError) as exc:
                self._reader_error(exc)
            except HeadlessServiceError as exc:
                self._json(400, {"ok": False, "error": _safe_detail(exc)})
            except Exception as exc:
                self._json(502, {"ok": False, "error": _safe_detail(exc)})
            return

        if path.startswith("/v1/subscriptions"):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            if self._subscription_unavailable():
                return
            try:
                parts = _path_parts(path)
                if parts == ["v1", "subscriptions"]:
                    payload = self._read_json()
                    created = self.subscription_api.create(payload)  # type: ignore[union-attr]
                    self._json(201, {"ok": True, "subscription": created})
                    return
                if len(parts) >= 4 and parts[:2] == ["v1", "subscriptions"]:
                    subscription_id = parts[2]
                    action = parts[3:]
                    if action == ["delete"]:
                        result = self.subscription_api.delete(subscription_id)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                    payload = self._read_json()
                    if action == ["update"]:
                        updated = self.subscription_api.update(subscription_id, payload)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, "subscription": updated})
                        return
                    if action == ["rules"]:
                        rules = self.subscription_api.configure_rules(subscription_id, payload)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, "rules": rules})
                        return
                    if action == ["items", "transition"]:
                        item = self.subscription_api.transition(subscription_id, payload)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, "item": item})
                        return
                    if action == ["reconcile"]:
                        result = self.subscription_api.reconcile(subscription_id, payload)  # type: ignore[union-attr]
                        self._json(200, {"ok": True, **result})
                        return
                self._json(404, {"ok": False, "error": "not found"})
            except (HeadlessSubscriptionApiError, ValueError) as exc:
                self._subscription_error(exc)
            except HeadlessServiceError as exc:
                self._json(400, {"ok": False, "error": _safe_detail(exc)})
            except Exception as exc:
                self._json(502, {"ok": False, "error": _safe_detail(exc)})
            return

        if path.startswith("/v1/transcripts/"):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            if self._transcript_unavailable():
                return
            try:
                parts = _path_parts(path)
                if len(parts) < 4 or parts[:2] != ["v1", "transcripts"]:
                    self._json(404, {"ok": False, "error": "not found"})
                    return
                media_id = parts[2]
                if len(parts) == 4 and parts[3] == "index":
                    result = self.transcript_api.index(media_id)  # type: ignore[union-attr]
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 5 and parts[3:] == ["speakers", "relabel"]:
                    payload = self._read_json()
                    result = self.transcript_api.relabel(  # type: ignore[union-attr]
                        media_id,
                        payload.get("oldLabel"),
                        payload.get("newLabel"),
                    )
                    self._json(200, {"ok": True, **result})
                    return
                if len(parts) == 4 and parts[3] == "export":
                    payload = self._read_json()
                    result = self.transcript_api.export(  # type: ignore[union-attr]
                        media_id,
                        format=payload.get("format", "txt"),
                        basename=payload.get("basename", ""),
                        include_speaker=payload.get("includeSpeaker", True),
                    )
                    self._json(200, {"ok": True, "export": result})
                    return
                self._json(404, {"ok": False, "error": "not found"})
            except (HeadlessTranscriptApiError, ValueError) as exc:
                self._transcript_error(exc)
            except HeadlessServiceError as exc:
                self._json(400, {"ok": False, "error": _safe_detail(exc)})
            except Exception as exc:
                self._json(502, {"ok": False, "error": _safe_detail(exc)})
            return

        if path != "/v1/media/sync":
            super().do_POST()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            result = self.media_api.sync()
            self._json(200, {"ok": True, **result})
        except HeadlessMediaApiError as exc:
            self._json(400, {"ok": False, "error": _safe_detail(exc)})
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})


class GalaxyApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address,
        runtime: HeadlessRuntime,
        auth_token: str,
        bound_host: str,
        media_api: HeadlessMediaApi,
        transcript_api: HeadlessTranscriptApi | None = None,
        subscription_api: HeadlessSubscriptionApi | None = None,
        reader_api: HeadlessReaderApi | None = None,
        learning_api: HeadlessLearningApi | None = None,
        music_api: HeadlessMusicApi | None = None,
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
        super().__init__(address, GalaxyApiRequestHandler)


def run_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    download_root: Path | None = None,
    auth_token: str = "",
    media_api: HeadlessMediaApi | None = None,
    transcript_api: HeadlessTranscriptApi | None = None,
    subscription_api: HeadlessSubscriptionApi | None = None,
    reader_api: HeadlessReaderApi | None = None,
    learning_api: HeadlessLearningApi | None = None,
    music_api: HeadlessMusicApi | None = None,
) -> int:
    clean_host = str(host or DEFAULT_HOST).strip()
    clean_port = _bounded_int(port, DEFAULT_PORT, 1, 65535)
    token = str(auth_token or "").strip()
    if not _loopback_host(clean_host) and len(token) < 24:
        raise HeadlessServiceError("a bearer token with at least 24 characters is required for non-loopback binding")
    root = Path(download_root or _download_root()).expanduser().resolve(strict=False)
    runtime = HeadlessRuntime(root)
    media = media_api or HeadlessMediaApi(root)
    transcripts = transcript_api or HeadlessTranscriptApi(root)
    subscriptions = subscription_api or HeadlessSubscriptionApi()
    reader = reader_api or HeadlessReaderApi()
    learning = learning_api or HeadlessLearningApi(root)
    music = music_api or HeadlessMusicApi(root)
    server = GalaxyApiServer(
        (clean_host, clean_port),
        runtime,
        token,
        clean_host,
        media,
        transcripts,
        subscriptions,
        reader,
        learning,
        music,
    )
    stopping = threading.Event()

    def stop_handler(_signum, _frame) -> None:
        if stopping.is_set():
            return
        stopping.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    for signal_name in ("SIGINT", "SIGTERM"):
        value = getattr(signal, signal_name, None)
        if value is not None:
            with suppress(OSError, RuntimeError, ValueError):
                signal.signal(value, stop_handler)
    try:
        print(f"Galaxy Headless API listening on {clean_host}:{clean_port}", flush=True)
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        runtime.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="galaxy-headless", description="Galaxy Local Engine headless API")
    parser.add_argument("--host", default=os.getenv("GALAXY_HEADLESS_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("GALAXY_HEADLESS_PORT", str(DEFAULT_PORT))))
    parser.add_argument("--download-dir", default=os.getenv("GALAXY_DOWNLOAD_DIR", ""))
    args = parser.parse_args(argv)
    token = os.getenv("GALAXY_HEADLESS_TOKEN", "")
    root = _download_root(args.download_dir)
    return run_server(host=args.host, port=args.port, download_root=root, auth_token=token)


if __name__ == "__main__":
    raise SystemExit(main())
