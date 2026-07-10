"""任务队列状态管理。"""
from __future__ import annotations

import uuid
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from ..history.service import HistoryRecord
from .types import AppTask, TaskKind, TaskOptions, TaskSnapshot, TaskStage, TaskStatus


class QueueFullError(RuntimeError):
    """处理队列已满。"""


MAX_QUEUE_SIZE = 20
COMPLETED_KEEP_LIMIT = 50


class TaskManager(QObject):
    """维护应用任务队列，不直接操作 UI 控件。"""

    changed = Signal(object)
    task_ready = Signal(object)
    paused = Signal(str)
    persistence_checkpoint = Signal()

    def __init__(
        self,
        *,
        parent=None,
    ):
        super().__init__(parent)
        self.max_queue_size = MAX_QUEUE_SIZE
        self.completed_keep_limit = COMPLETED_KEEP_LIMIT
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
        input_url: str = "",
    ) -> AppTask:
        existing = self._active_process_task_for_record(record.record_key)
        if existing is not None:
            if existing.status is TaskStatus.QUEUED:
                self._merge_queued_process_task(
                    existing,
                    auto_summarize=auto_summarize,
                    overwrite_existing=overwrite_existing,
                    manual=manual,
                    summary_only=summary_only,
                )
                self._emit_changed()
            return existing
        if len(self._queued) >= self.max_queue_size:
            raise QueueFullError(f"队列已满，最多可排队 {self.max_queue_size} 个任务")
        now = _now_text()
        self._remove_completed_for_record(record.record_key)
        task = AppTask(
            task_id=_new_task_id("task"),
            kind=TaskKind.PROCESS_RECORD,
            status=TaskStatus.QUEUED,
            stage=TaskStage.WAITING,
            record_key=record.record_key,
            notebook_id=record.notebook_id,
            record_id=record.record_id,
            source=source,
            input_url=input_url,
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

    def enqueue_remote_import(self, url: str, *, auto_summarize: bool = False) -> AppTask:
        if len(self._queued) >= self.max_queue_size:
            raise QueueFullError(f"队列已满，最多可排队 {self.max_queue_size} 个任务")
        now = _now_text()
        title = str(url or "").strip() or "链接导入"
        task = AppTask(
            task_id=_new_task_id("remote"),
            kind=TaskKind.REMOTE_IMPORT,
            status=TaskStatus.QUEUED,
            stage=TaskStage.WAITING,
            source="remote_import",
            input_url=title,
            title=title,
            message="等待处理",
            created_at=now,
            queued_at=now,
            options=TaskOptions(auto_summarize=auto_summarize),
        )
        self._queued.append(task)
        self._emit_changed()
        return task

    def has_queue_capacity(self) -> bool:
        """返回处理队列是否还能接纳一条新任务。"""
        return len(self._queued) < self.max_queue_size

    def add_queue_full_terminal_task(self, record: HistoryRecord, *, source: str) -> AppTask:
        """为已保存但无法入队的录音保留手动重试入口。"""
        now = _now_text()
        task = AppTask(
            task_id=_new_task_id("task"),
            kind=TaskKind.PROCESS_RECORD,
            status=TaskStatus.CANCELLED,
            stage=TaskStage.CANCELLED,
            record_key=record.record_key,
            notebook_id=record.notebook_id,
            record_id=record.record_id,
            source=source,
            title=record.display_name,
            message="处理队列已满，需手动重试",
            created_at=now,
            queued_at=now,
            finished_at=now,
            options=TaskOptions(manual=True),
        )
        self._push_completed(task)
        self._emit_changed()
        return task

    def load_queued(self, tasks: list[AppTask]) -> None:
        self._queued = [task for task in tasks if task.status is TaskStatus.QUEUED]
        self._emit_changed()

    def load_tasks(self, tasks: list[AppTask]) -> None:
        """恢复可展示的任务状态。运行中任务不能跨启动恢复。"""
        self._running = [
            task
            for task in tasks
            if task.status is TaskStatus.RUNNING and task.kind in {TaskKind.PROCESS_RECORD, TaskKind.REMOTE_IMPORT}
        ]
        self._queued = [task for task in tasks if task.status is TaskStatus.QUEUED]
        queued_record_keys = {task.record_key for task in self._queued if task.record_key}
        terminal_statuses = {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.INTERRUPTED,
        }
        completed: list[AppTask] = []
        completed_record_keys: set[str] = set()
        for task in tasks:
            if task.status not in terminal_statuses:
                continue
            if task.record_key and task.record_key in queued_record_keys:
                continue
            if task.record_key and task.record_key in completed_record_keys:
                continue
            completed.append(task)
            if task.record_key:
                completed_record_keys.add(task.record_key)
        self._completed = completed
        del self._completed[self.completed_keep_limit :]
        self._emit_changed()

    def start_next_if_idle(self) -> AppTask | None:
        if self._paused_reason or self.running_process_task() is not None or not self._queued:
            return None
        task = self._queued.pop(0)
        task.status = TaskStatus.RUNNING
        task.stage = TaskStage.WAITING
        task.message = ""
        task.error_message = ""
        task.progress_percent = None
        task.started_at = _now_text()
        self._running.append(task)
        self._emit_changed()
        self.task_ready.emit(task)
        return task

    def start_recording(self, title: str = "录音") -> AppTask:
        now = _now_text()
        task = AppTask(
            task_id=_new_task_id("record"),
            kind=TaskKind.RECORDING,
            status=TaskStatus.RUNNING,
            stage=TaskStage.WAITING,
            source="recording",
            title=title,
            message="正在录音",
            created_at=now,
            queued_at=now,
            started_at=now,
        )
        self._running.append(task)
        self._emit_changed()
        return task

    def update_recording(self, task_id: str, message: str) -> None:
        task = self._find_running(task_id)
        if task is None or task.kind is not TaskKind.RECORDING:
            return
        if task.message == message:
            return
        task.message = message
        self._emit_changed()

    def finish_recording(self, task_id: str) -> None:
        for index, task in enumerate(self._running):
            if task.task_id == task_id and task.kind is TaskKind.RECORDING:
                del self._running[index]
                self._emit_changed()
                return

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
        stage_changed = task.stage is not stage
        task.stage = stage
        task.message = message
        task.progress_percent = progress_percent
        self._emit_changed()
        if stage_changed:
            self.persistence_checkpoint.emit()

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
        task.restart_stage = task.stage
        task.status = TaskStatus.FAILED
        task.stage = TaskStage.FAILED
        task.message = error_message
        task.error_message = error_message
        task.finished_at = _now_text()
        self._push_completed(task)
        if pause_queue and self._queued:
            self._paused_reason = error_message
            self.paused.emit(error_message)
        self._emit_changed()

    def cancel_running(self, task_id: str, message: str = "已取消") -> None:
        task = self._pop_running(task_id)
        if task is None:
            return
        task.restart_stage = task.stage
        task.status = TaskStatus.CANCELLED
        task.stage = TaskStage.CANCELLED
        task.message = message
        task.progress_percent = None
        task.finished_at = _now_text()
        self._push_completed(task)
        self._emit_changed()

    def retry_completed(self, record_key: str) -> AppTask | None:
        """把同一条记录的终态任务移回队列，避免面板出现重复行。"""
        if not record_key:
            return None
        if not self.has_queue_capacity():
            return None
        for index, task in enumerate(self._completed):
            if task.record_key != record_key:
                continue
            retried = self._completed.pop(index)
            retried.status = TaskStatus.QUEUED
            retried.stage = TaskStage.WAITING
            retried.message = "等待处理"
            retried.progress_percent = None
            retried.error_message = ""
            retried.finished_at = None
            retried.started_at = None
            retried.queued_at = _now_text()
            self._queued.append(retried)
            self._emit_changed()
            return retried
        return None

    def interrupt_running(self, task_id: str, message: str = "已中断") -> None:
        task = self._pop_running(task_id)
        if task is None:
            return
        task.restart_stage = task.stage
        task.status = TaskStatus.INTERRUPTED
        task.stage = TaskStage.INTERRUPTED
        task.message = message
        task.error_message = message
        task.progress_percent = None
        task.finished_at = _now_text()
        self._push_completed(task)
        self._emit_changed()

    def interrupt_queued(self, task_id: str, message: str = "已中断") -> bool:
        for index, task in enumerate(self._queued):
            if task.task_id != task_id:
                continue
            interrupted = self._queued.pop(index)
            interrupted.status = TaskStatus.INTERRUPTED
            interrupted.stage = TaskStage.INTERRUPTED
            interrupted.message = message
            interrupted.error_message = message
            interrupted.progress_percent = None
            interrupted.finished_at = _now_text()
            self._push_completed(interrupted)
            self._emit_changed()
            return True
        return False

    def interrupt_unfinished_process_tasks(self, message: str) -> None:
        """将处理通道中的运行和排队任务统一转为可手动重试的中断任务。"""
        for task in list(self._running):
            if task.kind in {TaskKind.PROCESS_RECORD, TaskKind.REMOTE_IMPORT}:
                self.interrupt_running(task.task_id, message)
        for task in list(self._queued):
            if task.kind in {TaskKind.PROCESS_RECORD, TaskKind.REMOTE_IMPORT}:
                self.interrupt_queued(task.task_id, message)

    def remove_queued(self, task_id: str) -> bool:
        for index, task in enumerate(self._queued):
            if task.task_id == task_id:
                del self._queued[index]
                self._clear_pause_if_queue_empty()
                self._emit_changed()
                return True
        return False

    def cancel_queued(self, task_id: str, message: str = "已取消") -> bool:
        for index, task in enumerate(self._queued):
            if task.task_id != task_id:
                continue
            cancelled = self._queued.pop(index)
            cancelled.status = TaskStatus.CANCELLED
            cancelled.stage = TaskStage.CANCELLED
            cancelled.message = message
            cancelled.error_message = ""
            cancelled.progress_percent = None
            cancelled.finished_at = _now_text()
            self._push_completed(cancelled)
            self._clear_pause_if_queue_empty()
            self._emit_changed()
            return True
        return False

    def remove_completed_for_record(self, record_key: str) -> bool:
        before = len(self._completed)
        self._remove_completed_for_record(record_key)
        removed = len(self._completed) != before
        if removed:
            self._emit_changed()
        return removed

    def move_queued_to_index(self, task_id: str, target_index: int) -> bool:
        for index, task in enumerate(self._queued):
            if task.task_id != task_id:
                continue
            target_index = max(0, min(len(self._queued), int(target_index)))
            if target_index > index:
                target_index -= 1
            if target_index == index:
                return False
            self._queued.pop(index)
            self._queued.insert(target_index, task)
            self._emit_changed()
            return True
        return False

    def clear_queued(self) -> int:
        count = len(self._queued)
        self._queued.clear()
        self._clear_pause_if_queue_empty()
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
            if task.kind in {TaskKind.PROCESS_RECORD, TaskKind.REMOTE_IMPORT}:
                return task
        return None

    def queued_tasks(self) -> list[AppTask]:
        return list(self._queued)

    def all_persistable_tasks(self) -> list[AppTask]:
        return list(self._running) + list(self._queued) + list(self._completed)

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

    def _active_process_task_for_record(self, record_key: str) -> AppTask | None:
        if not record_key:
            return None
        for task in self._running + self._queued:
            if task.kind is TaskKind.PROCESS_RECORD and task.record_key == record_key:
                return task
        return None

    @staticmethod
    def _merge_queued_process_task(
        task: AppTask,
        *,
        auto_summarize: bool,
        overwrite_existing: bool,
        manual: bool,
        summary_only: bool,
    ) -> None:
        task.options.auto_summarize = task.options.auto_summarize or auto_summarize
        task.options.overwrite_existing = task.options.overwrite_existing or overwrite_existing
        task.options.manual = task.options.manual or manual
        task.options.summary_only = task.options.summary_only and summary_only

    def _pop_running(self, task_id: str) -> AppTask | None:
        for index, task in enumerate(self._running):
            if task.task_id == task_id:
                return self._running.pop(index)
        return None

    def _push_completed(self, task: AppTask) -> None:
        if task.record_key:
            self._remove_completed_for_record(task.record_key)
        elif task.kind is TaskKind.REMOTE_IMPORT and task.input_url:
            self._remove_completed_for_remote_url(task.input_url)
        self._completed.insert(0, task)
        del self._completed[self.completed_keep_limit :]

    def _clear_pause_if_queue_empty(self) -> None:
        if not self._queued:
            self._paused_reason = ""

    def _emit_changed(self) -> None:
        self.changed.emit(self.snapshot())

    def _remove_completed_for_record(self, record_key: str) -> None:
        self._completed = [task for task in self._completed if task.record_key != record_key]

    def _remove_completed_for_remote_url(self, input_url: str) -> None:
        self._completed = [
            task
            for task in self._completed
            if not (task.kind is TaskKind.REMOTE_IMPORT and task.input_url == input_url)
        ]


def _new_task_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")
