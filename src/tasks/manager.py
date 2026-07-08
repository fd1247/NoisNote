"""任务队列状态管理。"""
from __future__ import annotations

import uuid
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from ..history.service import HistoryRecord
from .types import AppTask, TaskKind, TaskOptions, TaskSnapshot, TaskStage, TaskStatus


class QueueFullError(RuntimeError):
    """处理队列已满。"""


class TaskManager(QObject):
    """维护应用任务队列，不直接操作 UI 控件。"""

    changed = Signal(object)
    task_ready = Signal(object)
    paused = Signal(str)

    def __init__(
        self,
        *,
        max_queue_size: int = 20,
        completed_keep_limit: int = 50,
        parent=None,
    ):
        super().__init__(parent)
        self.max_queue_size = max(1, int(max_queue_size))
        self.completed_keep_limit = max(1, int(completed_keep_limit))
        self._running: list[AppTask] = []
        self._queued: list[AppTask] = []
        self._completed: list[AppTask] = []
        self._paused_reason = ""

    def enqueue_process_record(
        self,
        record: HistoryRecord,
        *,
        source: str,
        auto_summarize: bool,
        overwrite_existing: bool = False,
        manual: bool = False,
        summary_only: bool = False,
    ) -> AppTask:
        if len(self._queued) >= self.max_queue_size:
            raise QueueFullError(f"队列已满，最多可排队 {self.max_queue_size} 个任务")
        now = _now_text()
        task = AppTask(
            task_id=_new_task_id("task"),
            kind=TaskKind.PROCESS_RECORD,
            status=TaskStatus.QUEUED,
            stage=TaskStage.WAITING,
            record_key=record.record_key,
            notebook_id=record.notebook_id,
            record_id=record.record_id,
            source=source,
            title=record.display_name,
            message="等待处理",
            created_at=now,
            queued_at=now,
            options=TaskOptions(
                auto_summarize=auto_summarize,
                overwrite_existing=overwrite_existing,
                manual=manual,
                summary_only=summary_only,
            ),
        )
        self._queued.append(task)
        self._emit_changed()
        return task

    def load_queued(self, tasks: list[AppTask]) -> None:
        self._queued = [task for task in tasks if task.status is TaskStatus.QUEUED]
        self._emit_changed()

    def start_next_if_idle(self) -> AppTask | None:
        if self._paused_reason or self._running or not self._queued:
            return None
        task = self._queued.pop(0)
        task.status = TaskStatus.RUNNING
        task.stage = TaskStage.WAITING
        task.message = "准备处理"
        task.started_at = _now_text()
        self._running.append(task)
        self._emit_changed()
        self.task_ready.emit(task)
        return task

    def mark_running(
        self,
        task_id: str,
        stage: TaskStage,
        message: str = "",
        progress_percent: int | None = None,
    ) -> None:
        task = self._find_running(task_id)
        if task is None:
            return
        task.stage = stage
        task.message = message
        task.progress_percent = progress_percent
        self._emit_changed()

    def complete_running(self, task_id: str, message: str = "处理完成") -> None:
        task = self._pop_running(task_id)
        if task is None:
            return
        task.status = TaskStatus.COMPLETED
        task.stage = TaskStage.COMPLETED
        task.message = message
        task.progress_percent = 100
        task.finished_at = _now_text()
        self._push_completed(task)
        self._emit_changed()

    def fail_running(self, task_id: str, error_message: str, *, pause_queue: bool = False) -> None:
        task = self._pop_running(task_id)
        if task is None:
            return
        task.status = TaskStatus.FAILED
        task.stage = TaskStage.FAILED
        task.message = error_message
        task.error_message = error_message
        task.finished_at = _now_text()
        self._push_completed(task)
        if pause_queue:
            self._paused_reason = error_message
            self.paused.emit(error_message)
        self._emit_changed()

    def cancel_running(self, task_id: str, message: str = "已取消") -> None:
        task = self._pop_running(task_id)
        if task is None:
            return
        task.status = TaskStatus.CANCELLED
        task.stage = TaskStage.CANCELLED
        task.message = message
        task.finished_at = _now_text()
        self._push_completed(task)
        self._emit_changed()

    def interrupt_running(self, task_id: str, message: str = "已中断") -> None:
        task = self._pop_running(task_id)
        if task is None:
            return
        task.status = TaskStatus.INTERRUPTED
        task.stage = TaskStage.INTERRUPTED
        task.message = message
        task.error_message = message
        task.finished_at = _now_text()
        self._push_completed(task)
        self._emit_changed()

    def remove_queued(self, task_id: str) -> bool:
        for index, task in enumerate(self._queued):
            if task.task_id == task_id:
                del self._queued[index]
                self._emit_changed()
                return True
        return False

    def move_queued(self, task_id: str, offset: int) -> bool:
        for index, task in enumerate(self._queued):
            if task.task_id != task_id:
                continue
            new_index = max(0, min(len(self._queued) - 1, index + offset))
            if new_index == index:
                return False
            self._queued.pop(index)
            self._queued.insert(new_index, task)
            self._emit_changed()
            return True
        return False

    def clear_queued(self) -> int:
        count = len(self._queued)
        self._queued.clear()
        if count:
            self._emit_changed()
        return count

    def resume(self) -> None:
        self._paused_reason = ""
        self._emit_changed()

    def has_unfinished_tasks(self) -> bool:
        return bool(self._running or self._queued)

    def running_process_task(self) -> AppTask | None:
        for task in self._running:
            if task.kind is TaskKind.PROCESS_RECORD:
                return task
        return None

    def queued_tasks(self) -> list[AppTask]:
        return list(self._queued)

    def snapshot(self) -> TaskSnapshot:
        return TaskSnapshot(
            running=tuple(self._running),
            queued=tuple(self._queued),
            completed=tuple(self._completed),
            paused_reason=self._paused_reason,
        )

    def _find_running(self, task_id: str) -> AppTask | None:
        for task in self._running:
            if task.task_id == task_id:
                return task
        return None

    def _pop_running(self, task_id: str) -> AppTask | None:
        for index, task in enumerate(self._running):
            if task.task_id == task_id:
                return self._running.pop(index)
        return None

    def _push_completed(self, task: AppTask) -> None:
        self._completed.insert(0, task)
        del self._completed[self.completed_keep_limit :]

    def _emit_changed(self) -> None:
        self.changed.emit(self.snapshot())


def _new_task_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")
