"""主窗口任务队列胶水逻辑。"""
from __future__ import annotations

from pathlib import Path

from ..history.service import HistoryRecord
from ..tasks import AppTask, QueueFullError, TaskManager, TaskQueueStore, TaskStage


class TaskQueueHandlers:
    """连接任务队列、历史记录和现有处理 worker。"""

    def _init_task_queue(self) -> None:
        tasks_config = self.config.get("tasks", {})
        self.task_manager = TaskManager(
            max_queue_size=int(tasks_config.get("max_queue_size") or 20),
            completed_keep_limit=int(tasks_config.get("completed_keep_limit") or 50),
            parent=self,
        )
        self.current_processing_task: AppTask | None = None
        self.task_queue_store = TaskQueueStore(self._task_queue_path())
        self.task_manager.changed.connect(self._on_task_snapshot_changed)
        # 通过延迟查找实例方法，兼容测试中的 monkeypatch。
        self.task_manager.task_ready.connect(lambda task: self._execute_processing_task(task))
        restored = self.task_queue_store.load(self.history_service)
        if restored:
            self.task_manager.load_queued(restored)
            self._set_status(f"已恢复 {len(restored)} 个待处理任务")
        self._start_next_processing_task()

    def _task_queue_path(self) -> Path:
        from ..app.config import APP_CONFIG_DIR

        return Path(APP_CONFIG_DIR) / "task_queue.json"

    def enqueue_record_processing(
        self,
        record: HistoryRecord,
        *,
        source: str,
        overwrite_existing: bool = False,
        manual: bool = False,
        summary_only: bool = False,
    ) -> AppTask | None:
        try:
            task = self.task_manager.enqueue_process_record(
                record,
                source=source,
                auto_summarize=bool(self.config.get("audio", {}).get("auto_summarize", False)),
                overwrite_existing=overwrite_existing,
                manual=manual,
                summary_only=summary_only,
            )
        except QueueFullError as exc:
            self._show_error(str(exc))
            return None
        self._persist_queued_tasks()
        self._start_next_processing_task()
        return task

    def _start_next_processing_task(self) -> None:
        if self.task_manager is None:
            return
        self.task_manager.start_next_if_idle()
        self._persist_queued_tasks()

    def _execute_processing_task(self, task: AppTask) -> None:
        record = self.history_service.get_record_by_key(task.record_key)
        if record is None:
            self.task_manager.fail_running(task.task_id, "历史记录不存在")
            self._start_next_processing_task()
            return
        self.current_processing_task = task
        self.processing_record = record
        self.processing_source = task.source
        self.task_manager.mark_running(task.task_id, TaskStage.WAITING, "准备处理")
        if task.options.summary_only:
            text = self.history_service.read_transcript(record)
            if not text.strip():
                self._finish_queue_task_failed("当前记录没有可总结的转录文本")
                return
            self.start_summarization(text, record)
            return
        self.start_transcription(record.audio_path, record, source=task.source)

    def _finish_queue_task_success(self, message: str) -> None:
        task = self._active_queue_task()
        self.current_processing_task = None
        if task and self.task_manager is not None:
            self.task_manager.complete_running(task.task_id, message)
        self._persist_queued_tasks()
        self._start_next_processing_task()

    def _finish_queue_task_failed(self, message: str, *, pause_queue: bool = False) -> None:
        task = self._active_queue_task()
        self.current_processing_task = None
        if task and self.task_manager is not None:
            self.task_manager.fail_running(task.task_id, message, pause_queue=pause_queue)
        self._persist_queued_tasks()
        self._start_next_processing_task()

    def cancel_processing_task(self, task_id: str) -> None:
        running = self.task_manager.running_process_task()
        if running is None or running.task_id != task_id:
            return
        worker = getattr(self, "transcription_worker", None)
        if worker is not None and hasattr(worker, "request_cancel"):
            self.task_manager.mark_running(task_id, running.stage, "正在取消")
            worker.request_cancel()
            return
        self.task_manager.cancel_running(task_id, "已取消")
        self.current_processing_task = None
        self._persist_queued_tasks()
        self._start_next_processing_task()

    def _on_task_snapshot_changed(self, snapshot: object) -> None:
        refresh = getattr(self, "_refresh_task_panel", None)
        if callable(refresh):
            refresh(snapshot)

    def _persist_queued_tasks(self) -> None:
        task_manager = getattr(self, "task_manager", None)
        task_queue_store = getattr(self, "task_queue_store", None)
        if task_manager is None or task_queue_store is None:
            return
        task_queue_store.save(task_manager.queued_tasks())

    def _active_queue_task(self) -> AppTask | None:
        if self.current_processing_task is not None:
            return self.current_processing_task
        task_manager = getattr(self, "task_manager", None)
        if task_manager is None:
            return None
        return task_manager.running_process_task()

    def _queue_task_for_record(self, record: HistoryRecord | None) -> AppTask | None:
        task = self._active_queue_task()
        if task is None or record is None:
            return None
        if task.record_key != record.record_key:
            return None
        return task

    def _current_task_auto_summarize_enabled(self) -> bool:
        task = self._active_queue_task()
        if task is not None:
            return bool(task.options.auto_summarize)
        return bool(self.config.get("audio", {}).get("auto_summarize", True))
