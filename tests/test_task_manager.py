from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.history.service import HistoryRecord
from src.tasks import manager as manager_module
from src.tasks.manager import QueueFullError, TaskManager
from src.tasks.types import TaskKind, TaskStage, TaskStatus


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
    manager = TaskManager()
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
    assert snapshot.running[0].message == ""
    assert snapshot.running[0].message != "准备处理"
    assert snapshot.queued == ()


def test_remote_import_task_keeps_auto_summarize_option() -> None:
    manager = TaskManager()

    task = manager.enqueue_remote_import("https://example.com/video", auto_summarize=True)

    assert task.options.auto_summarize is True


def test_remote_import_task_uses_processing_lane(tmp_path: Path) -> None:
    manager = TaskManager()
    remote = manager.enqueue_remote_import("https://example.com/video")
    local = manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)

    started = manager.start_next_if_idle()

    assert started is not None
    assert started.task_id == remote.task_id
    assert started.kind is TaskKind.REMOTE_IMPORT
    assert started.input_url == "https://example.com/video"
    assert started.message != "准备处理"
    assert manager.start_next_if_idle() is None
    assert [task.task_id for task in manager.snapshot().queued] == [local.task_id]


def test_remote_workflow_uses_record_bound_process_task(tmp_path: Path) -> None:
    manager = TaskManager()
    record = _record(tmp_path, "remote")

    task = manager.enqueue_process_record(
        record,
        source="remote_import",
        auto_summarize=True,
        input_url="https://example.com/video",
    )

    assert task.kind is TaskKind.PROCESS_RECORD
    assert task.record_key == record.record_key
    assert task.input_url == "https://example.com/video"


def test_remote_import_terminal_rows_deduplicate_by_url(tmp_path: Path) -> None:
    manager = TaskManager()
    first = manager.enqueue_remote_import("https://example.com/missing")
    manager.start_next_if_idle()
    manager.fail_running(first.task_id, "下载失败")
    second = manager.enqueue_remote_import("https://example.com/missing")
    manager.start_next_if_idle()
    manager.fail_running(second.task_id, "下载失败")

    completed = manager.snapshot().completed
    assert len(completed) == 1
    assert completed[0].task_id == second.task_id
    assert completed[0].input_url == "https://example.com/missing"


def test_processing_tasks_are_serial(tmp_path: Path) -> None:
    manager = TaskManager()
    first = manager.enqueue_process_record(_record(tmp_path, "a"), source="recording", auto_summarize=False)
    second = manager.enqueue_process_record(_record(tmp_path, "b"), source="import", auto_summarize=False)

    assert manager.start_next_if_idle().task_id == first.task_id
    assert manager.start_next_if_idle() is None
    assert [item.task_id for item in manager.snapshot().queued] == [second.task_id]


def test_complete_running_starts_no_task_until_requested(tmp_path: Path) -> None:
    manager = TaskManager()
    first = manager.enqueue_process_record(_record(tmp_path, "a"), source="recording", auto_summarize=False)
    second = manager.enqueue_process_record(_record(tmp_path, "b"), source="import", auto_summarize=False)
    manager.start_next_if_idle()

    manager.complete_running(first.task_id, "转录完成")

    snapshot = manager.snapshot()
    assert snapshot.running == ()
    assert [item.task_id for item in snapshot.queued] == [second.task_id]
    assert snapshot.completed[0].task_id == first.task_id
    assert snapshot.completed[0].status is TaskStatus.COMPLETED


def test_reorder_and_remove_queued_tasks(tmp_path: Path) -> None:
    manager = TaskManager()
    first = manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)
    second = manager.enqueue_process_record(_record(tmp_path, "b"), source="import", auto_summarize=False)
    third = manager.enqueue_process_record(_record(tmp_path, "c"), source="import", auto_summarize=False)

    assert not hasattr(manager, "move_queued")
    assert manager.move_queued_to_index(third.task_id, 1)
    assert [item.task_id for item in manager.snapshot().queued] == [first.task_id, third.task_id, second.task_id]
    assert manager.remove_queued(third.task_id)
    assert [item.task_id for item in manager.snapshot().queued] == [first.task_id, second.task_id]


def test_cancel_queued_task_moves_it_to_completed(tmp_path: Path) -> None:
    manager = TaskManager()
    record = _record(tmp_path, "a")
    task = manager.enqueue_process_record(record, source="import", auto_summarize=False)

    assert manager.cancel_queued(task.task_id, "从排队列表中移出")

    snapshot = manager.snapshot()
    assert snapshot.queued == ()
    assert snapshot.completed[0].task_id == task.task_id
    assert snapshot.completed[0].status is TaskStatus.CANCELLED
    assert snapshot.completed[0].stage is TaskStage.CANCELLED
    assert snapshot.completed[0].message == "从排队列表中移出"
    assert snapshot.completed[0].finished_at is not None


def test_interrupt_unfinished_process_tasks_moves_running_and_queued_to_completed(tmp_path: Path) -> None:
    manager = TaskManager()
    running = manager.enqueue_process_record(_record(tmp_path, "running"), source="import", auto_summarize=False)
    queued = manager.enqueue_process_record(_record(tmp_path, "queued"), source="import", auto_summarize=False)
    manager.start_next_if_idle()
    manager.mark_running(running.task_id, TaskStage.TRANSCRIBING, "转录中", 37)

    manager.interrupt_unfinished_process_tasks("应用退出，任务中断")

    snapshot = manager.snapshot()
    assert snapshot.running == ()
    assert snapshot.queued == ()
    assert [(task.record_key, task.status, task.message) for task in snapshot.completed] == [
        (queued.record_key, TaskStatus.INTERRUPTED, "应用退出，任务中断"),
        (running.record_key, TaskStatus.INTERRUPTED, "应用退出，任务中断"),
    ]
    assert snapshot.completed[0].restart_stage is None
    assert snapshot.completed[1].restart_stage is TaskStage.TRANSCRIBING
    assert all(task.progress_percent is None for task in snapshot.completed)


def test_repeated_enqueue_for_queued_record_reuses_task_and_merges_options(tmp_path: Path) -> None:
    manager = TaskManager()
    record = _record(tmp_path, "same-record")

    first = manager.enqueue_process_record(
        record,
        source="manual",
        auto_summarize=False,
        summary_only=True,
    )
    repeated = manager.enqueue_process_record(
        record,
        source="manual",
        auto_summarize=True,
        overwrite_existing=True,
        manual=True,
        summary_only=False,
    )

    snapshot = manager.snapshot()
    assert repeated is first
    assert [task.task_id for task in snapshot.queued] == [first.task_id]
    assert first.options.summary_only is False
    assert first.options.auto_summarize is True
    assert first.options.overwrite_existing is True
    assert first.options.manual is True


def test_repeated_enqueue_for_running_record_keeps_running_task_unchanged(tmp_path: Path) -> None:
    manager = TaskManager()
    record = _record(tmp_path, "running-record")
    running = manager.enqueue_process_record(
        record,
        source="manual",
        auto_summarize=False,
        summary_only=False,
    )
    manager.start_next_if_idle()

    repeated = manager.enqueue_process_record(
        record,
        source="manual",
        auto_summarize=True,
        overwrite_existing=True,
        manual=True,
        summary_only=True,
    )

    snapshot = manager.snapshot()
    assert repeated is running
    assert [task.task_id for task in snapshot.running] == [running.task_id]
    assert snapshot.queued == ()
    assert running.options.summary_only is False
    assert running.options.auto_summarize is False
    assert running.options.overwrite_existing is False


def test_enqueue_after_terminal_task_creates_fresh_task(tmp_path: Path) -> None:
    manager = TaskManager()
    record = _record(tmp_path, "terminal-record")
    terminal = manager.enqueue_process_record(record, source="import", auto_summarize=False)
    manager.start_next_if_idle()
    manager.complete_running(terminal.task_id)

    fresh = manager.enqueue_process_record(record, source="manual", auto_summarize=True)

    snapshot = manager.snapshot()
    assert fresh is not terminal
    assert snapshot.completed == ()
    assert [task.task_id for task in snapshot.queued] == [fresh.task_id]


def test_stage_change_requests_task_persistence_checkpoint(tmp_path: Path) -> None:
    manager = TaskManager()
    task = manager.enqueue_process_record(_record(tmp_path, "checkpoint"), source="import", auto_summarize=False)
    manager.start_next_if_idle()
    checkpoint_count: list[None] = []
    manager.persistence_checkpoint.connect(lambda: checkpoint_count.append(None))

    manager.mark_running(task.task_id, TaskStage.TRANSCRIBING, "转录中", 17)
    manager.mark_running(task.task_id, TaskStage.TRANSCRIBING, "转录中", 18)

    assert checkpoint_count == [None]


def test_clear_queued_preserves_running(tmp_path: Path) -> None:
    manager = TaskManager()
    first = manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)
    manager.enqueue_process_record(_record(tmp_path, "b"), source="import", auto_summarize=False)
    manager.start_next_if_idle()

    removed = manager.clear_queued()

    assert removed == 1
    assert [item.task_id for item in manager.snapshot().running] == [first.task_id]
    assert manager.snapshot().queued == ()


def test_queue_full_rejects_new_task(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(manager_module, "MAX_QUEUE_SIZE", 1)
    manager = TaskManager()
    manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)

    with pytest.raises(QueueFullError):
        manager.enqueue_process_record(_record(tmp_path, "b"), source="import", auto_summarize=False)


def test_queue_capacity_reports_when_new_record_can_be_admitted(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(manager_module, "MAX_QUEUE_SIZE", 1)
    manager = TaskManager()

    assert manager.has_queue_capacity()

    manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)

    assert not manager.has_queue_capacity()


def test_queue_full_terminal_task_keeps_manual_retry_entry(tmp_path: Path) -> None:
    manager = TaskManager()
    record = _record(tmp_path, "recording")

    task = manager.add_queue_full_terminal_task(record, source="recording")

    completed = manager.snapshot().completed
    assert completed == (task,)
    assert task.status is TaskStatus.CANCELLED
    assert task.stage is TaskStage.CANCELLED
    assert task.record_key == record.record_key
    assert task.message == "处理队列已满，需手动重试"


def test_retry_completed_task_respects_queue_capacity(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(manager_module, "MAX_QUEUE_SIZE", 0)
    manager = TaskManager()
    record = _record(tmp_path, "recording")
    manager.add_queue_full_terminal_task(record, source="recording")

    assert manager.retry_completed(record.record_key) is None
    assert len(manager.snapshot().completed) == 1
    assert manager.snapshot().queued == ()


def test_cancelled_task_keeps_restart_stage_when_requeued(tmp_path: Path) -> None:
    manager = TaskManager()
    task = manager.enqueue_process_record(_record(tmp_path, "summary"), source="import", auto_summarize=True)
    manager.start_next_if_idle()
    manager.mark_running(task.task_id, TaskStage.SUMMARIZING, "AI总结中")

    manager.cancel_running(task.task_id, "已取消")

    cancelled = manager.snapshot().completed[0]
    assert cancelled.restart_stage is TaskStage.SUMMARIZING

    retried = manager.retry_completed(cancelled.record_key)

    assert retried is cancelled
    assert retried.status is TaskStatus.QUEUED
    assert retried.stage is TaskStage.WAITING
    assert retried.restart_stage is TaskStage.SUMMARIZING
    assert retried.error_message == ""


def test_mark_running_clears_progress_when_message_omits_percent(tmp_path: Path) -> None:
    manager = TaskManager()
    task = manager.enqueue_process_record(_record(tmp_path, "progress"), source="import", auto_summarize=False)
    manager.start_next_if_idle()
    manager.mark_running(task.task_id, TaskStage.TRANSCRIBING, "转录中", 62)

    manager.mark_running(task.task_id, TaskStage.TRANSCRIBING, "正在取消")

    assert manager.snapshot().running[0].progress_percent is None


def test_systemic_failure_without_remaining_tasks_does_not_pause_queue(tmp_path: Path) -> None:
    manager = TaskManager()
    task = manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)
    manager.start_next_if_idle()

    manager.fail_running(task.task_id, "模型未下载", pause_queue=True)

    snapshot = manager.snapshot()
    assert snapshot.paused_reason == ""
    assert snapshot.completed[0].status is TaskStatus.FAILED
    assert snapshot.completed[0].error_message == "模型未下载"


def test_systemic_failure_pauses_queue_when_followup_task_is_waiting(tmp_path: Path) -> None:
    manager = TaskManager()
    first = manager.enqueue_process_record(_record(tmp_path, "first"), source="import", auto_summarize=False)
    manager.start_next_if_idle()
    second = manager.enqueue_process_record(_record(tmp_path, "second"), source="import", auto_summarize=False)

    manager.fail_running(first.task_id, "模型未下载", pause_queue=True)

    snapshot = manager.snapshot()
    assert snapshot.paused_reason == "模型未下载"
    assert [task.task_id for task in snapshot.queued] == [second.task_id]
    assert manager.start_next_if_idle() is None


def test_resume_clears_pause_reason(tmp_path: Path) -> None:
    manager = TaskManager()
    task = manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)
    manager.start_next_if_idle()
    manager.fail_running(task.task_id, "模型未下载", pause_queue=True)

    manager.resume()

    assert manager.snapshot().paused_reason == ""


def test_retry_completed_task_moves_existing_row_back_to_queue(tmp_path: Path) -> None:
    manager = TaskManager()
    record = _record(tmp_path, "a")
    task = manager.enqueue_process_record(record, source="import", auto_summarize=False)
    manager.start_next_if_idle()
    manager.fail_running(task.task_id, "未识别到有效语音内容")

    retried = manager.retry_completed(record.record_key)

    snapshot = manager.snapshot()
    assert retried is not None
    assert retried.task_id == task.task_id
    assert retried.status is TaskStatus.QUEUED
    assert retried.stage is TaskStage.WAITING
    assert retried.error_message == ""
    assert [item.task_id for item in snapshot.queued] == [task.task_id]
    assert snapshot.completed == ()

    restarted = manager.start_next_if_idle()

    assert restarted is retried
    assert restarted.message == ""


def test_enqueue_process_record_removes_old_terminal_row_for_same_record(tmp_path: Path) -> None:
    manager = TaskManager()
    record = _record(tmp_path, "a")
    task = manager.enqueue_process_record(record, source="import", auto_summarize=False)
    manager.start_next_if_idle()
    manager.cancel_running(task.task_id, "已取消转录")

    new_task = manager.enqueue_process_record(record, source="manual", auto_summarize=False, manual=True)

    snapshot = manager.snapshot()
    assert [item.task_id for item in snapshot.queued] == [new_task.task_id]
    assert snapshot.completed == ()


def test_recording_task_does_not_block_processing_lane(tmp_path: Path) -> None:
    manager = TaskManager()
    recording = manager.start_recording("录音")
    process = manager.enqueue_process_record(_record(tmp_path, "a"), source="import", auto_summarize=False)

    started = manager.start_next_if_idle()

    snapshot = manager.snapshot()
    assert started is not None
    assert started.task_id == process.task_id
    assert [item.kind for item in snapshot.running] == [TaskKind.RECORDING, TaskKind.PROCESS_RECORD]
    assert recording.message == "正在录音"


def test_recording_task_skips_duplicate_elapsed_updates() -> None:
    manager = TaskManager()
    recording = manager.start_recording("录音")
    changes = []
    manager.changed.connect(lambda snapshot: changes.append(snapshot))

    manager.update_recording(recording.task_id, "已录制 00:00:01")
    manager.update_recording(recording.task_id, "已录制 00:00:01")
    manager.update_recording(recording.task_id, "已录制 00:00:02")

    assert len(changes) == 2
    assert manager.snapshot().running[0].message == "已录制 00:00:02"
