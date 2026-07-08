from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.history.service import HistoryRecord
from src.tasks.manager import QueueFullError, TaskManager
from src.tasks.types import TaskStage, TaskStatus


def _record(tmp_path: Path, record_id: str) -> HistoryRecord:
    record_dir = tmp_path / record_id
    record_dir.mkdir()
    audio = record_dir / "audio.wav"
    transcript = record_dir / "transcript.txt"
    summary = record_dir / "summary.md"
    markdown = record_dir / "summary.md"
    metadata = record_dir / "metadata.json"
    audio.write_bytes(b"fake")
    metadata.write_text("{}", encoding="utf-8")
    return HistoryRecord(
        record_id=record_id,
        layout="folder",
        record_dir=record_dir,
        audio_path=audio,
        transcript_path=transcript,
        summary_path=summary,
        markdown_path=markdown,
        metadata_path=metadata,
        created_at=datetime(2026, 7, 8, 12, 0, 0),
        duration_seconds=12.0,
        audio_size_bytes=4,
        total_size_bytes=4,
        notebook_id="default",
        notebook_name="默认笔记本",
    )


def test_enqueue_starts_first_task_when_idle(tmp_path: Path) -> None:
    manager = TaskManager(max_queue_size=20, completed_keep_limit=50)
    task = manager.enqueue_process_record(
        _record(tmp_path, "a"),
        source="import",
        auto_summarize=True,
    )

    started = manager.start_next_if_idle()

    assert started is not None
    assert started.task_id == task.task_id
    snapshot = manager.snapshot()
    assert [item.task_id for item in snapshot.running] == [task.task_id]
    assert snapshot.running[0].status is TaskStatus.RUNNING
    assert snapshot.running[0].stage is TaskStage.WAITING
    assert snapshot.queued == ()


def test_processing_tasks_are_serial(tmp_path: Path) -> None:
    manager = TaskManager(max_queue_size=20, completed_keep_limit=50)
    first = manager.enqueue_process_record(_record(tmp_path, "a"), source="recording", auto_summarize=False)
    second = manager.enqueue_process_record(_record(tmp_path, "b"), source="import", auto_summarize=False)

    assert manager.start_next_if_idle().task_id == first.task_id
    assert manager.start_next_if_idle() is None
    assert [item.task_id for item in manager.snapshot().queued] == [second.task_id]


def test_complete_running_starts_no_task_until_requested(tmp_path: Path) -> None:
    manager = TaskManager(max_queue_size=20, completed_keep_limit=50)
    first = manager.enqueue_process_record(_record(tmp_path, "a"), source="recording", auto_summarize=False)
    second = manager.enqueue_process_record(_record(tmp_path, "b"), source="import", auto_summarize=False)
    manager.start_next_if_idle()

    manager.complete_running(first.task_id, "转录完成")

    snapshot = manager.snapshot()
    assert snapshot.running == ()
    assert [item.task_id for item in snapshot.queued] == [second.task_id]
    assert snapshot.completed[0].task_id == first.task_id
    assert snapshot.completed[0].status is TaskStatus.COMPLETED


def test_move_and_remove_queued_tasks(tmp_path: Path) -> None:
    manager = TaskManager(max_queue_size=20, completed_keep_limit=50)
    first = manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)
    second = manager.enqueue_process_record(_record(tmp_path, "b"), source="import", auto_summarize=False)
    third = manager.enqueue_process_record(_record(tmp_path, "c"), source="import", auto_summarize=False)

    assert manager.move_queued(third.task_id, -1)
    assert [item.task_id for item in manager.snapshot().queued] == [first.task_id, third.task_id, second.task_id]
    assert manager.remove_queued(third.task_id)
    assert [item.task_id for item in manager.snapshot().queued] == [first.task_id, second.task_id]


def test_clear_queued_preserves_running(tmp_path: Path) -> None:
    manager = TaskManager(max_queue_size=20, completed_keep_limit=50)
    first = manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)
    manager.enqueue_process_record(_record(tmp_path, "b"), source="import", auto_summarize=False)
    manager.start_next_if_idle()

    removed = manager.clear_queued()

    assert removed == 1
    assert [item.task_id for item in manager.snapshot().running] == [first.task_id]
    assert manager.snapshot().queued == ()


def test_queue_full_rejects_new_task(tmp_path: Path) -> None:
    manager = TaskManager(max_queue_size=1, completed_keep_limit=50)
    manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)

    with pytest.raises(QueueFullError):
        manager.enqueue_process_record(_record(tmp_path, "b"), source="import", auto_summarize=False)


def test_failure_can_pause_queue(tmp_path: Path) -> None:
    manager = TaskManager(max_queue_size=20, completed_keep_limit=50)
    task = manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)
    manager.start_next_if_idle()

    manager.fail_running(task.task_id, "模型未下载", pause_queue=True)

    snapshot = manager.snapshot()
    assert snapshot.paused_reason == "模型未下载"
    assert snapshot.completed[0].status is TaskStatus.FAILED
    assert snapshot.completed[0].error_message == "模型未下载"
    assert manager.start_next_if_idle() is None


def test_resume_clears_pause_reason(tmp_path: Path) -> None:
    manager = TaskManager(max_queue_size=20, completed_keep_limit=50)
    task = manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)
    manager.start_next_if_idle()
    manager.fail_running(task.task_id, "模型未下载", pause_queue=True)

    manager.resume()

    assert manager.snapshot().paused_reason == ""
