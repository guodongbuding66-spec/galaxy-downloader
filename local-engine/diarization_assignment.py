from __future__ import annotations

import re
from contextlib import closing
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from transcript_workspace import MAX_SEGMENTS, TranscriptWorkspaceError, _clean_media_id, _connect

MAX_DIARIZATION_TURNS = 100_000
MAX_SPEAKERS = 64
SPEAKER_RE = re.compile(r"^[^\x00\r\n]{1,80}$")


class DiarizationAssignmentError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiarizationTurn:
    start_seconds: float
    end_seconds: float
    speaker: str

    def public_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["startSeconds"] = data.pop("start_seconds")
        data["endSeconds"] = data.pop("end_seconds")
        return data


@dataclass(frozen=True)
class DiarizationAssignmentResult:
    media_id: str
    assigned_segments: int
    unmatched_segments: int
    speaker_count: int
    turn_count: int

    def public_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["mediaId"] = data.pop("media_id")
        data["assignedSegments"] = data.pop("assigned_segments")
        data["unmatchedSegments"] = data.pop("unmatched_segments")
        data["speakerCount"] = data.pop("speaker_count")
        data["turnCount"] = data.pop("turn_count")
        return data


def _clean_seconds(value: object, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise DiarizationAssignmentError(f"{field} 无效") from exc
    if parsed < 0 or parsed != parsed or parsed in {float("inf"), float("-inf")}:
        raise DiarizationAssignmentError(f"{field} 无效")
    return round(parsed, 3)


def _clean_speaker(value: object) -> str:
    clean = " ".join(str(value or "").split()).strip()
    if not SPEAKER_RE.fullmatch(clean):
        raise DiarizationAssignmentError("Speaker 标签无效")
    return clean


def normalize_diarization_turns(values: Iterable[object]) -> list[DiarizationTurn]:
    turns: list[DiarizationTurn] = []
    for item in values:
        if len(turns) >= MAX_DIARIZATION_TURNS:
            raise DiarizationAssignmentError("Diarization turn 数量超过安全上限")
        if isinstance(item, DiarizationTurn):
            start = _clean_seconds(item.start_seconds, "startSeconds")
            end = _clean_seconds(item.end_seconds, "endSeconds")
            speaker = _clean_speaker(item.speaker)
        elif isinstance(item, dict):
            start = _clean_seconds(item.get("startSeconds", item.get("start")), "startSeconds")
            end = _clean_seconds(item.get("endSeconds", item.get("end")), "endSeconds")
            speaker = _clean_speaker(item.get("speaker"))
        else:
            raise DiarizationAssignmentError("Diarization turn 格式无效")
        if end <= start:
            raise DiarizationAssignmentError("Diarization turn 结束时间必须晚于开始时间")
        turns.append(DiarizationTurn(start, end, speaker))

    turns.sort(key=lambda item: (item.start_seconds, item.end_seconds, item.speaker.lower()))
    speakers = {item.speaker.casefold() for item in turns}
    if len(speakers) > MAX_SPEAKERS:
        raise DiarizationAssignmentError("Speaker 数量超过安全上限")
    return turns


def _best_speaker(
    segment_start: float,
    segment_end: float,
    turns: list[DiarizationTurn],
    start_index: int,
    *,
    minimum_overlap_seconds: float,
) -> tuple[str, int]:
    index = start_index
    while index < len(turns) and turns[index].end_seconds <= segment_start:
        index += 1

    scores: dict[str, float] = {}
    first_seen: dict[str, tuple[float, str]] = {}
    cursor = index
    while cursor < len(turns) and turns[cursor].start_seconds < segment_end:
        turn = turns[cursor]
        overlap = min(segment_end, turn.end_seconds) - max(segment_start, turn.start_seconds)
        if overlap > 0:
            key = turn.speaker.casefold()
            scores[key] = scores.get(key, 0.0) + overlap
            first_seen.setdefault(key, (turn.start_seconds, turn.speaker))
        cursor += 1

    if not scores:
        return "", index
    winner = min(
        scores,
        key=lambda key: (-scores[key], first_seen[key][0], first_seen[key][1].lower()),
    )
    if scores[winner] + 1e-9 < minimum_overlap_seconds:
        return "", index
    return first_seen[winner][1], index


def apply_diarization(
    engine_module,
    media_id: object,
    turns: Iterable[object],
    *,
    minimum_overlap_seconds: object = 0.05,
    clear_unmatched: bool = False,
) -> DiarizationAssignmentResult:
    try:
        clean_id = _clean_media_id(media_id)
    except TranscriptWorkspaceError as exc:
        raise DiarizationAssignmentError(str(exc)) from exc

    normalized = normalize_diarization_turns(turns)
    if not normalized:
        raise DiarizationAssignmentError("Diarization turn 不能为空")
    minimum = _clean_seconds(minimum_overlap_seconds, "minimumOverlapSeconds")
    if minimum > 60:
        raise DiarizationAssignmentError("minimumOverlapSeconds 超过合理上限")

    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT segment_index, start_seconds, end_seconds, speaker FROM transcript_segments "
            "WHERE media_id=? ORDER BY start_seconds, segment_index LIMIT ?",
            (clean_id, MAX_SEGMENTS + 1),
        ).fetchall()
        if len(rows) > MAX_SEGMENTS:
            raise DiarizationAssignmentError("Transcript segment 数量超过安全上限")
        if not rows:
            raise DiarizationAssignmentError("Transcript 尚未建立可分配 Speaker 的索引")

        updates: list[tuple[str, str, int]] = []
        assigned = 0
        unmatched = 0
        turn_index = 0
        for row in rows:
            start = max(0.0, float(row["start_seconds"]))
            end = max(start, float(row["end_seconds"]))
            speaker, turn_index = _best_speaker(
                start,
                end,
                normalized,
                turn_index,
                minimum_overlap_seconds=minimum,
            )
            if speaker:
                assigned += 1
                updates.append((speaker, clean_id, int(row["segment_index"])))
            else:
                unmatched += 1
                if clear_unmatched and str(row["speaker"]):
                    updates.append(("", clean_id, int(row["segment_index"])))

        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "UPDATE transcript_segments SET speaker=? WHERE media_id=? AND segment_index=?",
                updates,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return DiarizationAssignmentResult(
        media_id=clean_id,
        assigned_segments=assigned,
        unmatched_segments=unmatched,
        speaker_count=len({item.speaker.casefold() for item in normalized}),
        turn_count=len(normalized),
    )


def run_diarization_assignment_self_test() -> None:
    import tempfile
    from pathlib import Path

    from transcript_workspace import transcript_segments

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

        media_id = "a" * 32
        with closing(_connect(Engine)) as connection:
            connection.executemany(
                "INSERT INTO transcript_segments(media_id, segment_index, start_seconds, end_seconds, speaker, text) "
                "VALUES(?,?,?,?,?,?)",
                [
                    (media_id, 1, 0.0, 2.0, "", "first"),
                    (media_id, 2, 2.0, 4.0, "", "second"),
                    (media_id, 3, 4.0, 5.0, "Existing", "third"),
                    (media_id, 4, 8.0, 9.0, "Existing", "unmatched"),
                ],
            )
            connection.commit()

        result = apply_diarization(
            Engine,
            media_id,
            [
                {"startSeconds": 0.0, "endSeconds": 1.2, "speaker": "Speaker 1"},
                {"startSeconds": 1.2, "endSeconds": 3.0, "speaker": "Speaker 2"},
                {"startSeconds": 3.0, "endSeconds": 5.0, "speaker": "Speaker 2"},
            ],
        )
        assert result.assigned_segments == 3
        assert result.unmatched_segments == 1
        assert result.speaker_count == 2
        rows = transcript_segments(Engine, media_id, limit=10)
        assert [row["speaker"] for row in rows] == ["Speaker 1", "Speaker 2", "Speaker 2", "Existing"]

        cleared = apply_diarization(
            Engine,
            media_id,
            [{"start": 0.0, "end": 5.0, "speaker": "Host"}],
            clear_unmatched=True,
        )
        assert cleared.assigned_segments == 3 and cleared.unmatched_segments == 1
        rows = transcript_segments(Engine, media_id, limit=10)
        assert [row["speaker"] for row in rows] == ["Host", "Host", "Host", ""]

        tie_id = "b" * 32
        with closing(_connect(Engine)) as connection:
            connection.execute(
                "INSERT INTO transcript_segments(media_id, segment_index, start_seconds, end_seconds, speaker, text) "
                "VALUES(?,?,?,?,?,?)",
                (tie_id, 1, 0.0, 2.0, "", "tie"),
            )
            connection.commit()
        apply_diarization(
            Engine,
            tie_id,
            [
                {"start": 0.0, "end": 1.0, "speaker": "A"},
                {"start": 1.0, "end": 2.0, "speaker": "B"},
            ],
        )
        assert transcript_segments(Engine, tie_id, limit=10)[0]["speaker"] == "A"

        try:
            normalize_diarization_turns([{"start": 2, "end": 1, "speaker": "Bad"}])
        except DiarizationAssignmentError:
            pass
        else:
            raise AssertionError("invalid diarization turn was accepted")
