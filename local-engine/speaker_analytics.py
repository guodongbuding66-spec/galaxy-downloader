from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from typing import Any

from transcript_workspace import MAX_SEGMENTS, TranscriptWorkspaceError, _clean_media_id, _connect

UNLABELED = "Unlabeled"


class SpeakerAnalyticsError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpeakerStatistics:
    speaker: str
    segment_count: int
    talking_seconds: float
    share_percent: float
    timeline_percent: float
    first_start_seconds: float
    last_end_seconds: float

    def public_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["segmentCount"] = data.pop("segment_count")
        data["talkingSeconds"] = data.pop("talking_seconds")
        data["sharePercent"] = data.pop("share_percent")
        data["timelinePercent"] = data.pop("timeline_percent")
        data["firstStartSeconds"] = data.pop("first_start_seconds")
        data["lastEndSeconds"] = data.pop("last_end_seconds")
        return data


def _speaker_label(value: object) -> str:
    clean = " ".join(str(value or "").split()).strip()
    return clean[:80] or UNLABELED


def _merge_duration(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    total = 0.0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        total += max(0.0, current_end - current_start)
        current_start, current_end = start, end
    total += max(0.0, current_end - current_start)
    return round(total, 3)


def speaker_statistics(engine_module, media_id: object) -> dict[str, Any]:
    try:
        clean_id = _clean_media_id(media_id)
    except TranscriptWorkspaceError as exc:
        raise SpeakerAnalyticsError(str(exc)) from exc

    rows: list[tuple[str, float, float]] = []
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute(
            "SELECT speaker, start_seconds, end_seconds FROM transcript_segments "
            "WHERE media_id=? ORDER BY start_seconds, segment_index LIMIT ?",
            (clean_id, MAX_SEGMENTS + 1),
        )
        fetched = cursor.fetchall()
    if len(fetched) > MAX_SEGMENTS:
        raise SpeakerAnalyticsError("Transcript speaker analytics exceeded the segment safety limit")
    if not fetched:
        raise SpeakerAnalyticsError("Transcript 尚未建立可分析的索引")

    for row in fetched:
        start = max(0.0, float(row["start_seconds"]))
        end = max(start, float(row["end_seconds"]))
        rows.append((_speaker_label(row["speaker"]), start, end))

    by_speaker: dict[str, list[tuple[float, float]]] = {}
    counts: dict[str, int] = {}
    firsts: dict[str, float] = {}
    lasts: dict[str, float] = {}
    for speaker, start, end in rows:
        by_speaker.setdefault(speaker, []).append((start, end))
        counts[speaker] = counts.get(speaker, 0) + 1
        firsts[speaker] = min(firsts.get(speaker, start), start)
        lasts[speaker] = max(lasts.get(speaker, end), end)

    durations = {speaker: _merge_duration(intervals) for speaker, intervals in by_speaker.items()}
    total_speaking = round(sum(durations.values()), 3)
    timeline_start = min(start for _speaker, start, _end in rows)
    timeline_end = max(end for _speaker, _start, end in rows)
    timeline_seconds = round(max(0.0, timeline_end - timeline_start), 3)

    statistics = []
    for speaker in sorted(by_speaker, key=lambda item: (-durations[item], item.lower())):
        talking = durations[speaker]
        share = round((talking / total_speaking) * 100, 2) if total_speaking > 0 else 0.0
        timeline_share = round((talking / timeline_seconds) * 100, 2) if timeline_seconds > 0 else 0.0
        statistics.append(
            SpeakerStatistics(
                speaker=speaker,
                segment_count=counts[speaker],
                talking_seconds=talking,
                share_percent=share,
                timeline_percent=timeline_share,
                first_start_seconds=round(firsts[speaker], 3),
                last_end_seconds=round(lasts[speaker], 3),
            ).public_payload()
        )

    labeled = [item for item in statistics if item["speaker"] != UNLABELED]
    unlabeled_count = counts.get(UNLABELED, 0)
    return {
        "mediaId": clean_id,
        "speakerCount": len(labeled),
        "segmentCount": len(rows),
        "unlabeledSegmentCount": unlabeled_count,
        "totalTalkingSeconds": total_speaking,
        "timelineStartSeconds": round(timeline_start, 3),
        "timelineEndSeconds": round(timeline_end, 3),
        "timelineSeconds": timeline_seconds,
        "speakers": statistics,
    }


def run_speaker_analytics_self_test() -> None:
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

        media_id = "a" * 32
        with closing(_connect(Engine)) as connection:
            connection.executemany(
                "INSERT INTO transcript_segments(media_id, segment_index, start_seconds, end_seconds, speaker, text) "
                "VALUES(?,?,?,?,?,?)",
                [
                    (media_id, 1, 0.0, 2.0, "Speaker 1", "hello"),
                    (media_id, 2, 1.5, 3.0, "Speaker 1", "overlap"),
                    (media_id, 3, 3.0, 5.0, "Speaker 2", "world"),
                    (media_id, 4, 5.0, 6.0, "", "unknown"),
                ],
            )
            connection.commit()

        payload = speaker_statistics(Engine, media_id)
        assert payload["speakerCount"] == 2
        assert payload["segmentCount"] == 4
        assert payload["unlabeledSegmentCount"] == 1
        assert payload["timelineSeconds"] == 6.0
        rows = {item["speaker"]: item for item in payload["speakers"]}
        assert rows["Speaker 1"]["segmentCount"] == 2
        assert rows["Speaker 1"]["talkingSeconds"] == 3.0
        assert rows["Speaker 2"]["talkingSeconds"] == 2.0
        assert rows[UNLABELED]["talkingSeconds"] == 1.0
        assert rows["Speaker 1"]["sharePercent"] == 50.0
        assert rows["Speaker 1"]["timelinePercent"] == 50.0

        try:
            speaker_statistics(Engine, "../bad")
        except SpeakerAnalyticsError:
            pass
        else:
            raise AssertionError("unsafe media id was accepted")
