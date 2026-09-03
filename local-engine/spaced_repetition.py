from __future__ import annotations

import math
import re
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from course_workspace import _connect as _learning_connect

MAX_CARDS = 100_000
MAX_CARD_CHARS = 20_000
MAX_TAGS = 20
MAX_TAG_CHARS = 64
_CARD_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_RATINGS = frozenset({"again", "hard", "good", "easy"})


class SpacedRepetitionError(RuntimeError):
    pass


def _connect(engine_module):
    connection = _learning_connect(engine_module)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS flashcards (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL DEFAULT '',
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '',
            repetitions INTEGER NOT NULL DEFAULT 0,
            interval_days REAL NOT NULL DEFAULT 0,
            ease_factor REAL NOT NULL DEFAULT 2.5,
            due_at TEXT NOT NULL,
            last_reviewed_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_flashcards_due
            ON flashcards(due_at, id);
        CREATE INDEX IF NOT EXISTS idx_flashcards_course
            ON flashcards(course_id, due_at);
        """
    )
    connection.commit()
    return connection


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object) -> datetime:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SpacedRepetitionError("Flashcard due time 无效") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _CARD_ID_RE.fullmatch(clean):
        raise SpacedRepetitionError("Flashcard ID 无效")
    return clean


def _clean_text(value: object, label: str) -> str:
    clean = str(value or "").replace("\x00", " ").strip()[:MAX_CARD_CHARS]
    if not clean:
        raise SpacedRepetitionError(f"{label} 不能为空")
    return clean


def _clean_tags(values: object) -> list[str]:
    if values in (None, ""):
        return []
    if isinstance(values, str):
        source = values.split(",")
    elif isinstance(values, (list, tuple, set)):
        source = list(values)
    else:
        raise SpacedRepetitionError("Flashcard tags 格式无效")
    result: list[str] = []
    seen: set[str] = set()
    for value in source:
        tag = " ".join(str(value or "").split()).strip()[:MAX_TAG_CHARS]
        key = tag.casefold()
        if tag and key not in seen:
            result.append(tag)
            seen.add(key)
        if len(result) >= MAX_TAGS:
            break
    return result


def _clean_course_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not clean:
        return ""
    if not _CARD_ID_RE.fullmatch(clean):
        raise SpacedRepetitionError("Course ID 无效")
    return clean


def create_flashcard(
    engine_module,
    front: object,
    back: object,
    *,
    course_id: object = "",
    tags: object = None,
) -> dict[str, Any]:
    clean_front = _clean_text(front, "Front")
    clean_back = _clean_text(back, "Back")
    course = _clean_course_id(course_id)
    clean_tags = _clean_tags(tags)
    due = _iso(_now())
    card_id = uuid.uuid4().hex
    with closing(_connect(engine_module)) as connection:
        count = int(connection.execute("SELECT COUNT(*) FROM flashcards").fetchone()[0])
        if count >= MAX_CARDS:
            raise SpacedRepetitionError("Flashcard 数量超过安全上限")
        if course and connection.execute("SELECT 1 FROM courses WHERE id=?", (course,)).fetchone() is None:
            raise SpacedRepetitionError("关联课程不存在")
        connection.execute(
            """
            INSERT INTO flashcards(id, course_id, front, back, tags, due_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (card_id, course, clean_front, clean_back, "\n".join(clean_tags), due),
        )
        connection.commit()
    return {
        "id": card_id,
        "courseId": course,
        "front": clean_front,
        "back": clean_back,
        "tags": clean_tags,
        "repetitions": 0,
        "intervalDays": 0.0,
        "easeFactor": 2.5,
        "dueAt": due,
    }


def update_flashcard(
    engine_module,
    card_id: object,
    *,
    front: object | None = None,
    back: object | None = None,
    tags: object | None = None,
) -> dict[str, Any]:
    clean = _clean_id(card_id)
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT * FROM flashcards WHERE id=?", (clean,)).fetchone()
        if row is None:
            raise SpacedRepetitionError("Flashcard 不存在")
        clean_front = _clean_text(front, "Front") if front is not None else str(row["front"])
        clean_back = _clean_text(back, "Back") if back is not None else str(row["back"])
        clean_tags = _clean_tags(tags) if tags is not None else str(row["tags"] or "").splitlines()
        connection.execute(
            "UPDATE flashcards SET front=?, back=?, tags=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (clean_front, clean_back, "\n".join(clean_tags), clean),
        )
        connection.commit()
    return get_flashcard(engine_module, clean)


def _row_payload(row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "courseId": str(row["course_id"] or ""),
        "front": str(row["front"]),
        "back": str(row["back"]),
        "tags": [item for item in str(row["tags"] or "").splitlines() if item],
        "repetitions": max(0, int(row["repetitions"] or 0)),
        "intervalDays": max(0.0, float(row["interval_days"] or 0)),
        "easeFactor": max(1.3, float(row["ease_factor"] or 2.5)),
        "dueAt": str(row["due_at"]),
        "lastReviewedAt": str(row["last_reviewed_at"] or ""),
    }


def get_flashcard(engine_module, card_id: object) -> dict[str, Any]:
    clean = _clean_id(card_id)
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT * FROM flashcards WHERE id=?", (clean,)).fetchone()
    if row is None:
        raise SpacedRepetitionError("Flashcard 不存在")
    return _row_payload(row)


def list_flashcards(
    engine_module,
    *,
    course_id: object = "",
    due_only: bool = False,
    limit: int = 500,
) -> list[dict[str, Any]]:
    course = _clean_course_id(course_id)
    safe_limit = max(1, min(int(limit), 2_000))
    clauses: list[str] = []
    values: list[Any] = []
    if course:
        clauses.append("course_id=?")
        values.append(course)
    if due_only:
        clauses.append("due_at<=?")
        values.append(_iso(_now()))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            f"SELECT * FROM flashcards{where} ORDER BY due_at, created_at LIMIT ?",  # noqa: S608 - clauses are fixed constants
            (*values, safe_limit),
        ).fetchall()
    return [_row_payload(row) for row in rows]


def _review_schedule(
    repetitions: int,
    interval_days: float,
    ease_factor: float,
    rating: str,
) -> tuple[int, float, float]:
    repetitions = max(0, int(repetitions))
    interval = max(0.0, float(interval_days))
    ease = max(1.3, min(float(ease_factor), 3.5))
    if rating == "again":
        return 0, 0.02, max(1.3, ease - 0.2)
    if rating == "hard":
        next_interval = max(0.25, interval * 1.2 if interval else 0.25)
        return max(1, repetitions), min(next_interval, 36_500.0), max(1.3, ease - 0.15)
    if rating == "good":
        if repetitions <= 0:
            next_interval = 1.0
        elif repetitions == 1:
            next_interval = 6.0
        else:
            next_interval = max(1.0, interval * ease)
        return repetitions + 1, min(next_interval, 36_500.0), ease
    if rating == "easy":
        if repetitions <= 0:
            next_interval = 4.0
        else:
            next_interval = max(4.0, interval * ease * 1.3)
        return repetitions + 1, min(next_interval, 36_500.0), min(3.5, ease + 0.15)
    raise SpacedRepetitionError("Review rating 无效")


def review_flashcard(
    engine_module,
    card_id: object,
    rating: object,
    *,
    reviewed_at: datetime | None = None,
) -> dict[str, Any]:
    clean = _clean_id(card_id)
    clean_rating = str(rating or "").strip().lower()
    if clean_rating not in _RATINGS:
        raise SpacedRepetitionError("Review rating 必须是 again / hard / good / easy")
    now = reviewed_at or _now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT * FROM flashcards WHERE id=?", (clean,)).fetchone()
        if row is None:
            raise SpacedRepetitionError("Flashcard 不存在")
        repetitions, interval, ease = _review_schedule(
            int(row["repetitions"] or 0),
            float(row["interval_days"] or 0),
            float(row["ease_factor"] or 2.5),
            clean_rating,
        )
        if not all(math.isfinite(value) for value in (interval, ease)):
            raise SpacedRepetitionError("Review schedule 计算结果无效")
        due = now + timedelta(days=interval)
        connection.execute(
            """
            UPDATE flashcards
            SET repetitions=?, interval_days=?, ease_factor=?, due_at=?, last_reviewed_at=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (repetitions, round(interval, 6), round(ease, 4), _iso(due), _iso(now), clean),
        )
        connection.commit()
    payload = get_flashcard(engine_module, clean)
    payload["rating"] = clean_rating
    return payload


def delete_flashcard(engine_module, card_id: object) -> bool:
    clean = _clean_id(card_id)
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute("DELETE FROM flashcards WHERE id=?", (clean,))
        connection.commit()
        return cursor.rowcount == 1


def run_spaced_repetition_self_test() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        state.mkdir()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return state

        card = create_flashcard(Engine, "Question", "Answer", tags=["One", "one", "Two"])
        assert card["tags"] == ["One", "Two"]
        assert len(list_flashcards(Engine, due_only=True)) == 1
        reviewed = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)
        good = review_flashcard(Engine, card["id"], "good", reviewed_at=reviewed)
        assert good["repetitions"] == 1 and good["intervalDays"] == 1.0
        assert _parse_iso(good["dueAt"]) == reviewed + timedelta(days=1)
        easy = review_flashcard(Engine, card["id"], "easy", reviewed_at=reviewed + timedelta(days=1))
        assert easy["repetitions"] == 2 and easy["intervalDays"] >= 4.0
        again = review_flashcard(Engine, card["id"], "again", reviewed_at=reviewed + timedelta(days=2))
        assert again["repetitions"] == 0 and 0 < again["intervalDays"] < 1
        updated = update_flashcard(Engine, card["id"], front="Updated", tags="A,B")
        assert updated["front"] == "Updated" and updated["tags"] == ["A", "B"]
        try:
            review_flashcard(Engine, card["id"], "invalid")
        except SpacedRepetitionError:
            pass
        else:
            raise AssertionError("invalid review rating was accepted")
        assert delete_flashcard(Engine, card["id"])
        assert list_flashcards(Engine) == []
