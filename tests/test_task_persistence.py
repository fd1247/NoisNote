from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.history.service import HistoryRecord
from src.tasks.persistence import TaskQueueStore
from src.tasks.types import AppTask, TaskKind, TaskOptions, TaskStage, TaskStatus


class FakeHistoryService:
    def __init__(self, records: dict[str, HistoryRecord]):
        self.records = records

    def get_record_by_key(self, record_key: str) -> HistoryRecord | None:
        return self.records.get(record_key)


def _record(tmp_path: Path, record_id: str, *, transcript: bool = False, audio: bool = True) -> HistoryRecord:
    record_dir = tmp_path / record_id
    record_dir.mkdir()
    audio = record_dir / "audio.wav"
    transcript_path = record_dir / "transcript.txt"
    summary = record_dir / "summary.md"
    metadata = record_dir / "metadata.json"
    if audio:
        audio.write_bytes(b"fake")
    if transcript:
        transcript_path.write_text("done", encoding="utf-8")
    metadata.write_text("{}", encoding="utf-8")
    return HistoryRecord(
        record_id=record_id,
        layout="folder",
        record_dir=record_dir,
        audio_path=audio,
        transcript_path=transcript_path,
        summary_path=summary,
        markdown_path=summary,
        metadata_path=metadata,
        created_at=datetime(2026, 7, 8, 12, 0, 0),
        duration_seconds=1.0,
        audio_size_bytes=4,
        total_size_bytes=4,
        notebook_id="default",
        notebook_name="默认笔记本",
    )


def _task(
    record: HistoryRecord,
    *,
    overwrite: bool = False,
    summary_only: bool = False,
    status: TaskStatus = TaskStatus.QUEUED,
) -> AppTask:
    return AppTask(
        task_id=f"task-{record.record_id}",
        kind=TaskKind.PROCESS_RECORD,
        status=status,
        stage=TaskStage.WAITING,
        record_key=record.record_key,
        notebook_id=record.notebook_id,
        record_id=record.record_id,
        title=record.display_name,
        created_at="2026-07-08T12:00:00",
        queued_at="2026-07-08T12:00:00",
        options=TaskOptions(overwrite_existing=overwrite, summary_only=summary_only),
    )


def test_store_round_trips_queued_tasks(tmp_path: Path) -> None:
    record = _record(tmp_path, "a")
    store = TaskQueueStore(tmp_path / "task_queue.json")

    store.save([_task(record)])
    loaded = store.load(FakeHistoryService({record.record_key: record}))

    assert len(loaded) == 1
    assert loaded[0].record_key == record.record_key
    assert loaded[0].status is TaskStatus.QUEUED


def test_store_filters_missing_records(tmp_path: Path) -> None:
    record = _record(tmp_path, "a")
    store = TaskQueueStore(tmp_path / "task_queue.json")
    store.save([_task(record)])

    loaded = store.load(FakeHistoryService({}))

    assert loaded == []


def test_store_filters_finished_records_without_overwrite(tmp_path: Path) -> None:
    record = _record(tmp_path, "a", transcript=True)
    store = TaskQueueStore(tmp_path / "task_queue.json")
    store.save([_task(record, overwrite=False)])

    loaded = store.load(FakeHistoryService({record.record_key: record}))

    assert loaded == []


def test_store_keeps_overwrite_task_for_finished_record(tmp_path: Path) -> None:
    record = _record(tmp_path, "a", transcript=True)
    store = TaskQueueStore(tmp_path / "task_queue.json")
    store.save([_task(record, overwrite=True)])

    loaded = store.load(FakeHistoryService({record.record_key: record}))

    assert len(loaded) == 1
    assert loaded[0].options.overwrite_existing is True


def test_store_round_trips_summary_only_task_without_audio(tmp_path: Path) -> None:
    record = _record(tmp_path, "a", transcript=True, audio=False)
    store = TaskQueueStore(tmp_path / "task_queue.json")

    store.save([_task(record, summary_only=True)])
    loaded = store.load(FakeHistoryService({record.record_key: record}))

    assert len(loaded) == 1
    assert loaded[0].record_key == record.record_key
    assert loaded[0].options.summary_only is True


def test_store_saves_only_queued_tasks(tmp_path: Path) -> None:
    queued = _record(tmp_path, "queued")
    running = _record(tmp_path, "running")
    store = TaskQueueStore(tmp_path / "task_queue.json")

    store.save([_task(queued), _task(running, status=TaskStatus.RUNNING)])
    loaded = store.load(FakeHistoryService({queued.record_key: queued, running.record_key: running}))

    assert [task.record_key for task in loaded] == [queued.record_key]
