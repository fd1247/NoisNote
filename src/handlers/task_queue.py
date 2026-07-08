"""主窗口任务队列胶水逻辑。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..history.service import HistoryRecord
from ..tasks import AppTask, QueueFullError, TaskManager, TaskQueueStore, TaskSnapshot, TaskStage, TaskStatus


class TaskQueueHandlers:
    """连接任务队列、历史记录和现有处理 worker。"""

    def _init_task_queue(self) -> None:
        tasks_config = self.config.get("tasks", {})
        self.task_manager = TaskManager(
            max_queue_size=int(tasks_config.get("max_queue_size") or 20),
            completed_keep_limit=int(tasks_config.get("completed_keep_limit") or 50),
            parent=self,
        )
        self._cancelled_processing_task_ids: set[str] = set()
        self.current_processing_task: AppTask | None = None
        self.task_queue_store = TaskQueueStore(self._task_queue_path())
        self.task_manager.changed.connect(self._on_task_snapshot_changed)
        # 通过延迟查找实例方法，兼容测试中的 monkeypatch。
        self.task_manager.task_ready.connect(lambda task: self._execute_processing_task(task))
        restored = self.task_queue_store.load(self.history_service)
        if restored:
            self.task_manager.load_queued(restored)
            self._set_status(f"已恢复 {len(restored)} 个待处理任务")
        self._refresh_task_panel(self.task_manager.snapshot())
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
        self._cancelled_processing_task_ids.discard(task.task_id)
        record = self.history_service.get_record_by_key(task.record_key)
        if record is None:
            self.task_manager.fail_running(task.task_id, "历史记录不存在")
            self._start_next_processing_task()
            return
        if not task.options.summary_only and task.options.overwrite_existing:
            try:
                record = self.history_service.clear_generated_results(record)
            except Exception as exc:
                self.task_manager.fail_running(task.task_id, f"清理旧结果失败：{exc}")
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
        if getattr(self, "processing_source", None) == "preprocess":
            self._cancelled_processing_task_ids.add(task_id)
        self.current_processing_task = None
        self.processing_record = None
        self.processing_source = None
        self.is_processing = False
        self.latest_transcription_percent = None
        self.record_button.setText("开始录音")
        self.record_button.setObjectName("RecordButton")
        self.record_button.style().unpolish(self.record_button)
        self.record_button.style().polish(self.record_button)
        self.recording_hint_label.setText("准备捕获系统声音")
        self._set_processing_ui(False)
        self._refresh_history_status_indicators()
        self._sync_detail_processing_view()
        self.load_recordings()
        self._set_status("已取消")
        self.task_manager.cancel_running(task_id, "已取消")
        self._persist_queued_tasks()
        self._start_next_processing_task()

    def _consume_cancelled_processing_task(self, task_id: str) -> bool:
        if not task_id:
            return False
        if task_id not in self._cancelled_processing_task_ids:
            return False
        self._cancelled_processing_task_ids.discard(task_id)
        return True

    def _on_task_snapshot_changed(self, snapshot: object) -> None:
        if isinstance(snapshot, TaskSnapshot):
            self._refresh_task_panel(snapshot)

    def _refresh_task_panel(self, snapshot: TaskSnapshot) -> None:
        """根据任务快照刷新三段式任务面板。"""
        if not hasattr(self, "running_task_title"):
            return
        self.running_task_title.setText(f"处理中（{len(snapshot.running)}）")
        self.queued_task_title.setText(f"排队中（{len(snapshot.queued)}）")
        self.completed_task_title.setText(f"已处理（{len(snapshot.completed)}）")
        self._replace_task_list(self.running_task_list, snapshot.running, running=True)
        self._replace_task_list(self.queued_task_list, snapshot.queued, queued=True)
        self._replace_task_list(self.completed_task_list, snapshot.completed, completed=True)

    def _replace_task_list(
        self,
        layout: QVBoxLayout,
        tasks: tuple[AppTask, ...],
        *,
        running: bool = False,
        queued: bool = False,
        completed: bool = False,
    ) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_nested_layout(child_layout)

        if not tasks:
            empty = QLabel("暂无任务")
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            layout.addWidget(empty)
            layout.addStretch(1)
            return

        for task in tasks:
            layout.addWidget(
                self._task_item_widget(
                    task,
                    running=running,
                    queued=queued,
                    completed=completed,
                )
            )
        layout.addStretch(1)

    def _task_item_widget(
        self,
        task: AppTask,
        *,
        running: bool,
        queued: bool,
        completed: bool,
    ) -> QFrame:
        frame = QFrame()
        frame.setObjectName("TaskItem")

        box = QVBoxLayout(frame)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(4)

        title = QLabel(task.title or task.record_id or task.record_key or "任务")
        title.setObjectName("TaskItemTitle")
        title.setWordWrap(True)
        box.addWidget(title)

        message = QLabel(self._task_message_text(task))
        message.setObjectName("Muted")
        message.setWordWrap(True)
        message.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(message)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(4)

        if running:
            actions.addWidget(self._task_action_button("取消", lambda: self.cancel_processing_task(task.task_id)))
        if queued:
            actions.addWidget(self._task_action_button("上移", lambda: self._move_queued_task(task.task_id, -1)))
            actions.addWidget(self._task_action_button("下移", lambda: self._move_queued_task(task.task_id, 1)))
            actions.addWidget(self._task_action_button("删除", lambda: self._remove_queued_task(task.task_id)))
        if completed:
            actions.addWidget(self._task_action_button("查看", lambda: self._select_record_by_key(task.record_key)))
            if task.status in {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.INTERRUPTED}:
                actions.addWidget(self._task_action_button("重试", lambda: self._retry_task_record(task.record_key)))

        actions.addStretch(1)
        box.addLayout(actions)
        return frame

    def _task_action_button(self, text: str, callback) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("TaskMiniButton")
        button.clicked.connect(callback)
        return button

    def _task_message_text(self, task: AppTask) -> str:
        if task.error_message:
            return task.error_message

        percent = "" if task.progress_percent is None else f" {task.progress_percent}%"
        stage_text = {
            TaskStage.WAITING: "等待中",
            TaskStage.PREPROCESSING: "预处理中",
            TaskStage.TRANSCRIBING: "转录中",
            TaskStage.SUMMARIZING: "总结中",
            TaskStage.COMPLETED: "已完成",
            TaskStage.FAILED: "失败",
            TaskStage.CANCELLED: "已取消",
            TaskStage.INTERRUPTED: "已中断",
        }.get(task.stage, task.stage.value)
        detail = str(task.message or "").strip()
        if detail:
            return f"{detail}{percent}".strip()
        return f"{stage_text}{percent}".strip()

    def _move_queued_task(self, task_id: str, offset: int) -> None:
        if self.task_manager.move_queued(task_id, offset):
            self._persist_queued_tasks()

    def _remove_queued_task(self, task_id: str) -> None:
        if self.task_manager.remove_queued(task_id):
            self._persist_queued_tasks()

    def _retry_task_record(self, record_key: str) -> None:
        if not record_key:
            return
        record = self.history_service.get_record_by_key(record_key)
        if record is not None:
            self.enqueue_record_processing(record, source="manual", overwrite_existing=True, manual=True)

    def _clear_nested_layout(self, layout: QVBoxLayout | QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_nested_layout(child_layout)

    def _persist_queued_tasks(self) -> None:
        task_manager = getattr(self, "task_manager", None)
        task_queue_store = getattr(self, "task_queue_store", None)
        if task_manager is None or task_queue_store is None:
            return
        task_queue_store.save(task_manager.queued_tasks())

    def _history_interruption_target(self, stage: TaskStage) -> tuple[str | None, bool]:
        """根据当前任务阶段选择最贴近的历史记录写入方式。"""
        if stage is TaskStage.SUMMARIZING:
            return "summary", False
        if stage is TaskStage.PREPROCESSING:
            return None, True
        return "transcription", False

    def prepare_task_queue_for_close(self) -> None:
        running = self.task_manager.running_process_task()
        if running is not None:
            stage = running.stage
            worker = getattr(self, "transcription_worker", None)
            if worker is not None and hasattr(worker, "request_cancel"):
                worker.request_cancel()
            self.task_manager.interrupt_running(running.task_id, "应用退出，任务已中断")
            if self.processing_record:
                step, use_input_error = self._history_interruption_target(stage)
                if use_input_error:
                    self.history_service.mark_input_error(self.processing_record, "应用退出，任务已中断")
                elif step is not None:
                    self.history_service.mark_error(self.processing_record, "应用退出，任务已中断", step=step)
        self._persist_queued_tasks()

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
