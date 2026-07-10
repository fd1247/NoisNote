"""主窗口任务队列胶水逻辑。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout

from ..history.service import HistoryRecord
from ..tasks import AppTask, QueueFullError, TaskKind, TaskManager, TaskQueueStore, TaskSnapshot, TaskStage, TaskStatus
from ..ui.pages.workbench import TaskActionSpec, TaskItemWidget
from ..ui.widgets.dialogs import confirm_without_icon
from ..utils.logging import log_event, record_context


class TaskQueueHandlers:
    """连接任务队列、历史记录和现有处理 worker。"""

    _EXIT_INTERRUPTED_TASK_MESSAGE = "应用退出，任务中断"
    _EXIT_INTERRUPTED_HISTORY_MESSAGE = "应用退出，任务已中断"

    def _init_task_queue(self) -> None:
        self.task_manager = TaskManager(parent=self)
        self._cancelled_processing_task_ids: set[str] = set()
        self.current_processing_task: AppTask | None = None
        self.task_queue_store = TaskQueueStore(self._task_queue_path())
        self.task_manager.changed.connect(self._on_task_snapshot_changed)
        self.task_manager.persistence_checkpoint.connect(self._persist_queued_tasks)
        # 通过延迟查找实例方法，兼容测试中的 monkeypatch。
        self.task_manager.task_ready.connect(lambda task: self._execute_processing_task(task))
        restored = self.task_queue_store.load(self.history_service)
        if restored:
            self.task_manager.load_tasks(restored)
            unfinished_count = len(self.task_manager.snapshot().running) + len(self.task_manager.snapshot().queued)
            if unfinished_count:
                self.task_manager.interrupt_unfinished_process_tasks(self._EXIT_INTERRUPTED_TASK_MESSAGE)
                self._persist_queued_tasks()
                self._set_status(f"已将 {unfinished_count} 个未完成任务移至已处理")
        self._refresh_task_panel(self.task_manager.snapshot())

    def _task_queue_path(self) -> Path:
        from ..app import config as app_config

        return Path(app_config.CONFIG_DIR) / "task_queue.json"

    def enqueue_record_processing(
        self,
        record: HistoryRecord,
        *,
        source: str,
        overwrite_existing: bool = False,
        manual: bool = False,
        summary_only: bool = False,
        input_url: str = "",
    ) -> AppTask | None:
        try:
            task = self.task_manager.enqueue_process_record(
                record,
                source=source,
                auto_summarize=bool(self.config.get("audio", {}).get("auto_summarize", False)),
                overwrite_existing=overwrite_existing,
                manual=manual,
                summary_only=summary_only,
                input_url=input_url,
            )
        except QueueFullError as exc:
            self._show_error(str(exc))
            return None
        self._persist_queued_tasks()
        if not getattr(self, "_closing_for_exit", False):
            self._start_next_processing_task()
        return task

    def has_processing_queue_capacity(self) -> bool:
        """返回串行处理队列是否还能接纳一条新记录任务。"""
        task_manager = getattr(self, "task_manager", None)
        return bool(task_manager is not None and task_manager.has_queue_capacity())

    def add_queue_full_recording_task(self, record: HistoryRecord) -> AppTask:
        """把录音满队列结果放入终态列表，供用户手动重试。"""
        task = self.task_manager.add_queue_full_terminal_task(record, source="recording")
        self._persist_queued_tasks()
        return task

    def enqueue_remote_import_task(self, url: str) -> AppTask | None:
        try:
            task = self.task_manager.enqueue_remote_import(
                url,
                auto_summarize=bool(self.config.get("audio", {}).get("auto_summarize", False)),
            )
        except QueueFullError as exc:
            self._show_error(str(exc))
            return None
        self._persist_queued_tasks()
        if not getattr(self, "_closing_for_exit", False):
            self._start_next_processing_task()
        return task

    def _start_next_processing_task(self) -> None:
        if getattr(self, "_closing_for_exit", False):
            return
        if self.task_manager is None:
            return
        self.task_manager.start_next_if_idle()
        self._persist_queued_tasks()

    def _execute_processing_task(self, task: AppTask) -> None:
        self._cancelled_processing_task_ids.discard(task.task_id)
        remote_restart_stages = {
            None,
            TaskStage.PARSING_LINK,
            TaskStage.EXTRACTING_SUBTITLE,
            TaskStage.DOWNLOADING_AUDIO,
        }
        if (task.kind is TaskKind.REMOTE_IMPORT or task.source == "remote_import") and task.restart_stage in remote_restart_stages:
            if hasattr(self, "_execute_remote_import_task"):
                self._execute_remote_import_task(task)
            return
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
        if task.restart_stage is TaskStage.SUMMARIZING:
            text = self.history_service.read_transcript(record)
            if not text.strip():
                self._finish_queue_task_failed("当前记录没有可总结的转录文本")
                return
            self.start_summarization(text, record)
            return
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
        remote_stages = {TaskStage.PARSING_LINK, TaskStage.EXTRACTING_SUBTITLE, TaskStage.DOWNLOADING_AUDIO}
        if (running.kind is TaskKind.REMOTE_IMPORT or running.source == "remote_import") and running.stage in remote_stages and hasattr(self, "_cancel_running_remote_import"):
            self._cancel_running_remote_import(task_id, self._cancel_message_for_stage(running.stage))
            return
        worker = self._cancellable_worker_for_running_task(running)
        if worker is not None and hasattr(worker, "request_cancel"):
            self.task_manager.mark_running(task_id, running.stage, "正在取消", running.progress_percent)
            self._cancelled_processing_task_ids.add(task_id)
            worker.request_cancel()
            return
        if getattr(self, "processing_source", None) == "preprocess":
            self._cancelled_processing_task_ids.add(task_id)
        if running.stage is TaskStage.SUMMARIZING:
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
        message = self._cancel_message_for_stage(running.stage)
        self._set_status(message)
        self.task_manager.cancel_running(task_id, message)
        self._persist_queued_tasks()
        self._start_next_processing_task()

    def _cancellable_worker_for_running_task(self, task: AppTask) -> object | None:
        if task.stage is TaskStage.PREPROCESSING or getattr(self, "processing_source", None) == "preprocess":
            return getattr(self, "preprocess_worker", None)
        if task.stage is TaskStage.SUMMARIZING:
            return getattr(self, "summary_worker", None)
        return getattr(self, "transcription_worker", None)

    def _consume_cancelled_processing_task(self, task_id: str) -> bool:
        if not task_id:
            return False
        if task_id not in self._cancelled_processing_task_ids:
            return False
        self._cancelled_processing_task_ids.discard(task_id)
        return True

    def _finish_cancelled_queue_task_if_needed(self, task_id: str, message: str = "") -> bool:
        if not task_id or task_id not in self._cancelled_processing_task_ids:
            return False
        self._cancelled_processing_task_ids.discard(task_id)
        self.active_task_ids.pop("preprocess", None)
        self.active_task_ids.pop("summary", None)
        running = self.task_manager.running_process_task() if getattr(self, "task_manager", None) else None
        if running is not None and running.task_id == task_id:
            message = message or self._cancel_message_for_stage(running.stage)
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
            self._set_status(message)
            self.task_manager.cancel_running(task_id, message)
            self._persist_queued_tasks()
            self._start_next_processing_task()
        return True

    @staticmethod
    def _cancel_message_for_stage(stage: TaskStage) -> str:
        return {
            TaskStage.TRANSCRIBING: "已取消转录",
            TaskStage.SUMMARIZING: "已取消总结",
            TaskStage.DOWNLOADING_AUDIO: "已取消音频下载",
        }.get(stage, "已取消")

    def _cleanup_cancellable_worker(self, worker: object, queue_task_id: str = "") -> None:
        self._finish_cancelled_queue_task_if_needed(queue_task_id)
        self._cleanup_worker(worker)

    def _on_task_snapshot_changed(self, snapshot: object) -> None:
        if isinstance(snapshot, TaskSnapshot):
            self._refresh_task_panel(snapshot)

    def _refresh_task_panel(self, snapshot: TaskSnapshot) -> None:
        """根据任务快照刷新三段式任务面板。"""
        if not hasattr(self, "running_task_title"):
            return
        self.task_queue_resume_button.setVisible(bool(snapshot.paused_reason and snapshot.queued))
        self.running_task_section.set_count(len(snapshot.running))
        self.queued_task_section.set_count(len(snapshot.queued))
        self.completed_task_section.set_count(len(snapshot.completed))
        self._replace_task_list(self.running_task_list, snapshot.running, running=True)
        if not self._task_list_has_active_drag(self.queued_task_list):
            self._replace_task_list(self.queued_task_list, snapshot.queued, queued=True)
        self._replace_task_list(self.completed_task_list, snapshot.completed, completed=True)

    def resume_task_queue(self) -> None:
        if not self.task_manager.snapshot().paused_reason:
            return
        self.task_manager.resume()
        self._persist_queued_tasks()
        self._set_status("队列已恢复")
        self._start_next_processing_task()

    def _replace_task_list(
        self,
        layout: QVBoxLayout,
        tasks: tuple[AppTask, ...],
        *,
        running: bool = False,
        queued: bool = False,
        completed: bool = False,
    ) -> None:
        if self._update_task_list_in_place(layout, tasks, running=running, queued=queued, completed=completed):
            return

        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                if isinstance(widget, TaskItemWidget):
                    widget._clear_drag_preview()
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_nested_layout(child_layout)

        if not tasks:
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

    def _update_task_list_in_place(
        self,
        layout: QVBoxLayout,
        tasks: tuple[AppTask, ...],
        *,
        running: bool = False,
        queued: bool = False,
        completed: bool = False,
    ) -> bool:
        if not tasks:
            return False
        widgets: list[TaskItemWidget] = []
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if isinstance(widget, TaskItemWidget):
                widgets.append(widget)
        if len(widgets) != len(tasks):
            return False
        for widget, task in zip(widgets, tasks):
            actions = self._task_action_specs(task, running=running, queued=queued, completed=completed)
            message = self._task_item_message(task, queued=queued, completed=completed)
            status_icon_name = self._task_status_icon_name(task, completed=completed)
            progress_percent = self._task_progress_percent(task, running=running)
            if not widget.can_update_in_place(
                task,
                actions=actions,
                message=message,
                queued_drop_enabled=queued,
                reserve_message_space=running,
                status_icon_name=status_icon_name,
                progress_percent=progress_percent,
            ):
                return False
        for widget, task in zip(widgets, tasks):
            message = self._task_item_message(task, queued=queued, completed=completed)
            progress_percent = self._task_progress_percent(task, running=running)
            widget.update_content(
                task,
                message=message,
                progress_percent=progress_percent,
                view_callback=lambda task=task: self._view_task(task),
            )
        return True

    def _task_item_widget(
        self,
        task: AppTask,
        *,
        running: bool,
        queued: bool,
        completed: bool,
    ) -> TaskItemWidget:
        actions = self._task_action_specs(task, running=running, queued=queued, completed=completed)
        return TaskItemWidget(
            task,
            message=self._task_item_message(task, queued=queued, completed=completed),
            actions=actions,
            view_callback=lambda task=task: self._view_task(task),
            queued_drop_callback=self._drop_queued_task if queued else None,
            reserve_message_space=running,
            status_icon_name=self._task_status_icon_name(task, completed=completed),
            progress_percent=self._task_progress_percent(task, running=running),
        )

    def _task_item_message(self, task: AppTask, *, queued: bool, completed: bool) -> str:
        if queued:
            return ""
        if task.kind is TaskKind.RECORDING:
            return str(task.message or "").strip()
        if completed and task.status is TaskStatus.COMPLETED:
            return ""
        if task.status is TaskStatus.RUNNING and task.kind in {TaskKind.PROCESS_RECORD, TaskKind.REMOTE_IMPORT}:
            return self._task_stage_text(task)
        return self._task_message_text(task)

    def _task_stage_text(self, task: AppTask) -> str:
        if task.error_message:
            return task.error_message
        detail = str(task.message or "").strip()
        if detail == "正在取消":
            return detail
        if task.stage is TaskStage.WAITING:
            return ""
        if task.stage is TaskStage.TRANSCRIBING:
            return "正在加载ASR模型" if "加载" in detail and "模型" in detail else "转录中"
        if task.stage is TaskStage.SUMMARIZING:
            return "AI总结中"
        if task.stage is TaskStage.PREPROCESSING:
            return "音频预处理"
        if detail:
            return detail
        return {
            TaskStage.PARSING_LINK: "解析链接中",
            TaskStage.EXTRACTING_SUBTITLE: "提取字幕中",
            TaskStage.DOWNLOADING_AUDIO: "下载音频中",
            TaskStage.PREPROCESSING: "音频预处理",
            TaskStage.TRANSCRIBING: "转录中",
            TaskStage.SUMMARIZING: "AI总结中",
        }.get(task.stage, task.stage.value)

    def _task_progress_percent(self, task: AppTask, *, running: bool) -> int | None:
        if not running or task.kind is TaskKind.RECORDING:
            return None
        if task.kind is TaskKind.REMOTE_IMPORT or task.source == "remote_import":
            return _remote_overall_progress(task)
        if task.kind is TaskKind.PROCESS_RECORD:
            return _local_overall_progress(task)
        return None

    def _task_status_icon_name(self, task: AppTask, *, completed: bool) -> str:
        if completed and task.status is TaskStatus.COMPLETED:
            return "已完成.svg"
        return ""

    def _task_action_specs(
        self,
        task: AppTask,
        *,
        running: bool,
        queued: bool,
        completed: bool,
    ) -> tuple[TaskActionSpec, ...]:
        actions: list[TaskActionSpec] = []
        if running:
            if task.kind is TaskKind.RECORDING:
                is_paused = bool(getattr(getattr(self, "recorder", None), "is_paused", False))
                actions.append(
                    TaskActionSpec(
                        "继续录制" if is_paused else "暂停录制",
                        self.resume_recording if is_paused else self.pause_recording,
                        tooltip="继续录制" if is_paused else "暂停录制",
                        icon_name="继续录制.svg" if is_paused else "暂停录制.svg",
                        prominent=True,
                    )
                )
                actions.append(
                    TaskActionSpec(
                        "停止录制",
                        self.stop_recording,
                        tooltip="停止录制",
                        icon_name="停止录制.svg",
                        prominent=True,
                    )
                )
            else:
                actions.append(
                    TaskActionSpec(
                        "取消",
                        lambda task_id=task.task_id: self.cancel_processing_task(task_id),
                        tooltip="取消",
                        icon_name="取消.svg",
                    )
                )
        if queued:
            actions.extend(
                (
                    TaskActionSpec(
                        "移出队列",
                        lambda task_id=task.task_id: self._remove_queued_task(task_id),
                        tooltip="移出队列但保留记录",
                        icon_name="移出列表.svg",
                    ),
                    TaskActionSpec(
                        "删除",
                        lambda task_id=task.task_id: self._delete_queued_task_record(task_id),
                        tooltip="移出队列并删除记录文件",
                        icon_name="删除.svg",
                    ),
                )
            )
        if completed:
            if task.status in {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.INTERRUPTED}:
                actions.append(
                    TaskActionSpec(
                        "重试",
                        lambda record_key=task.record_key: self._retry_task_record(record_key),
                        tooltip="重试",
                        icon_name="重试.svg",
                        prominent=True,
                    )
                )

        return tuple(actions)

    def _task_list_has_active_drag(self, layout: QVBoxLayout) -> bool:
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if isinstance(widget, TaskItemWidget) and widget.is_dragging():
                return True
        return False

    def _task_message_text(self, task: AppTask) -> str:
        if task.error_message:
            return task.error_message
        if task.stage is TaskStage.WAITING:
            return ""

        stage_text = {
            TaskStage.WAITING: "等待中",
            TaskStage.PARSING_LINK: "解析链接中",
            TaskStage.EXTRACTING_SUBTITLE: "提取字幕中",
            TaskStage.DOWNLOADING_AUDIO: "下载音频中",
            TaskStage.PREPROCESSING: "预处理中",
            TaskStage.TRANSCRIBING: "转录中",
            TaskStage.SUMMARIZING: "总结中",
            TaskStage.COMPLETED: "已完成",
            TaskStage.FAILED: "失败",
            TaskStage.CANCELLED: "已取消",
            TaskStage.INTERRUPTED: "已中断",
        }.get(task.stage, task.stage.value)
        detail = str(task.message or "").strip()
        if task.stage is TaskStage.TRANSCRIBING:
            if task.progress_percent is not None:
                return f"{stage_text} {task.progress_percent}%"
            return detail or stage_text
        percent = "" if task.progress_percent is None else f" {task.progress_percent}%"
        if detail:
            return f"{detail}{percent}".strip()
        return f"{stage_text}{percent}".strip()

    def _drop_queued_task(self, task_id: str, target_task_id: str, insert_after: bool) -> None:
        queued = self.task_manager.queued_tasks()
        for index, task in enumerate(queued):
            if task.task_id != target_task_id:
                continue
            target_index = index + (1 if insert_after else 0)
            if self.task_manager.move_queued_to_index(task_id, target_index):
                self._persist_queued_tasks()
            return

    def _remove_queued_task(self, task_id: str) -> None:
        if self.task_manager.cancel_queued(task_id, "从排队列表中移出"):
            self._persist_queued_tasks()

    def _delete_queued_task_record(self, task_id: str) -> None:
        task = self._queued_task_by_id(task_id)
        if task is None:
            return
        record = self.history_service.get_record_by_key(task.record_key) if task.record_key else None
        if record is None:
            if self.task_manager.remove_queued(task_id):
                self._persist_queued_tasks()
            self._show_error("历史记录不存在，已移出队列")
            return
        confirmed = confirm_without_icon(
            self,
            "删除任务和记录",
            "删除该任务和对应历史记录？\n"
            "本地导入的原始文件不会被删除；录音或远程导入生成的应用内音频会随历史记录删除。",
            confirm_text="删除",
        )
        if not confirmed:
            self._set_status("已取消删除")
            return

        if record.record_key == getattr(self, "playback_record_id", ""):
            self.stop_playback()
            self.playback_record_id = ""
            QApplication.processEvents()
        log_event(
            "record.delete.started",
            module="history",
            message="从队列删除历史记录",
            record_id=record.record_id,
            context={"record": record_context(record), "task_id": task.task_id},
        )
        result = self.history_service.delete_record(record)
        if not result.success:
            log_event(
                "record.delete.failed",
                level="ERROR",
                module="history",
                message="从队列删除历史记录失败",
                record_id=record.record_id,
                context={"record": record_context(record), "task_id": task.task_id, "error": result.message},
                error_code="HIS-002",
            )
            self._show_error(result.message)
            return
        log_event(
            "record.delete.completed",
            module="history",
            message="从队列删除历史记录完成",
            record_id=record.record_id,
            context={
                "task_id": task.task_id,
                "deleted_count": len(result.deleted_paths),
                "skipped_count": len(result.skipped_paths),
            },
        )
        if self.task_manager.remove_queued(task_id):
            self._persist_queued_tasks()
        if self.current_record and self.current_record.record_key == record.record_key:
            self._clear_missing_current_record()
        self.load_recordings()
        self._set_status("已删除任务和记录")

    def _queued_task_by_id(self, task_id: str) -> AppTask | None:
        for task in self.task_manager.queued_tasks():
            if task.task_id == task_id:
                return task
        return None

    def _view_task(self, task: AppTask) -> None:
        if task.kind is TaskKind.RECORDING:
            self.show_recording_dialog()
            return
        if not task.record_key or not self._select_record_by_key(task.record_key):
            if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.INTERRUPTED}:
                if self.task_manager.remove_completed_for_record(task.record_key):
                    self._persist_queued_tasks()
                self._show_error("历史记录已删除或不存在，已从已处理列表移除")
                return
            self._show_error("历史记录已删除或不存在")

    def _retry_task_record(self, record_key: str) -> None:
        if not record_key:
            return
        record = self.history_service.get_record_by_key(record_key)
        if record is None:
            if self.task_manager.remove_completed_for_record(record_key):
                self._persist_queued_tasks()
            self._show_error("原始历史记录已删除，无法重试。请重新导入原文件或重新录音。")
            return
        retried = self.task_manager.retry_completed(record_key)
        if retried is not None:
            if retried.restart_stage is TaskStage.SUMMARIZING:
                retried.options.manual = True
            elif retried.source == "remote_import" and record.input_error:
                retried.options.manual = True
            else:
                retried.source = "manual"
                retried.options.manual = True
            self._persist_queued_tasks()
            if not getattr(self, "_closing_for_exit", False):
                self._start_next_processing_task()
            return
        self.enqueue_record_processing(record, source="manual", overwrite_existing=True, manual=True)

    def _record_has_running_task(self, record: HistoryRecord) -> bool:
        task_manager = getattr(self, "task_manager", None)
        if task_manager is None:
            return False
        return any(task.record_key == record.record_key for task in task_manager.snapshot().running)

    def _discard_tasks_for_deleted_record(self, record_key: str) -> None:
        if not record_key:
            return
        task_manager = getattr(self, "task_manager", None)
        if task_manager is None:
            return
        removed = False
        for task in list(task_manager.queued_tasks()):
            if task.record_key == record_key and task_manager.remove_queued(task.task_id):
                removed = True
        if task_manager.remove_completed_for_record(record_key):
            removed = True
        if removed:
            self._persist_queued_tasks()

    def _clear_nested_layout(self, layout: QVBoxLayout | QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_nested_layout(child_layout)

    def _persist_queued_tasks(self) -> None:
        task_manager = getattr(self, "task_manager", None)
        task_queue_store = getattr(self, "task_queue_store", None)
        if task_manager is None or task_queue_store is None:
            return
        task_queue_store.save(task_manager.all_persistable_tasks())

    def _sync_running_task_stage(
        self,
        stage: TaskStage,
        message: str,
        progress_percent: int | None = None,
    ) -> None:
        task = self._active_queue_task()
        task_manager = getattr(self, "task_manager", None)
        if task is None or task_manager is None:
            return
        task_manager.mark_running(task.task_id, stage, message, progress_percent)

    def _history_interruption_target(self, stage: TaskStage) -> tuple[str | None, bool]:
        """根据当前任务阶段选择最贴近的历史记录写入方式。"""
        if stage is TaskStage.SUMMARIZING:
            return "summary", False
        if stage in {
            TaskStage.PREPROCESSING,
            TaskStage.PARSING_LINK,
            TaskStage.EXTRACTING_SUBTITLE,
            TaskStage.DOWNLOADING_AUDIO,
        }:
            return None, True
        return "transcription", False

    def prepare_task_queue_for_close(self) -> None:
        running = self.task_manager.running_process_task()
        if running is not None:
            stage = running.stage
            if (running.kind is TaskKind.REMOTE_IMPORT or running.source == "remote_import") and hasattr(self, "_stop_running_remote_import"):
                self._stop_running_remote_import(running.task_id)
            worker = getattr(self, "transcription_worker", None)
            if worker is not None and hasattr(worker, "request_cancel"):
                worker.request_cancel()
            if stage is TaskStage.SUMMARIZING:
                self._cancelled_processing_task_ids.add(running.task_id)
            self.task_manager.interrupt_running(running.task_id, self._EXIT_INTERRUPTED_TASK_MESSAGE)
            if self.processing_record:
                step, use_input_error = self._history_interruption_target(stage)
                if use_input_error:
                    self.history_service.mark_input_error(self.processing_record, self._EXIT_INTERRUPTED_HISTORY_MESSAGE)
                elif step is not None:
                    self.history_service.mark_error(self.processing_record, self._EXIT_INTERRUPTED_HISTORY_MESSAGE, step=step)
        for task in list(self.task_manager.queued_tasks()):
            self.task_manager.interrupt_queued(task.task_id, self._EXIT_INTERRUPTED_TASK_MESSAGE)
        self.current_processing_task = None
        self.processing_record = None
        self.processing_source = None
        self.is_processing = False
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


def _local_overall_progress(task: AppTask) -> int:
    if task.stage is TaskStage.PREPROCESSING:
        return _weighted_percent(task.progress_percent, 0, 10)
    if task.stage is TaskStage.TRANSCRIBING:
        if "加载" in str(task.message or "") and task.progress_percent is None:
            return 10
        end = 90 if task.options.auto_summarize else 98
        return _weighted_percent(task.progress_percent, 15, end)
    if task.stage is TaskStage.SUMMARIZING:
        return _weighted_percent(task.progress_percent, 90, 98)
    if task.stage is TaskStage.COMPLETED:
        return 100
    return 0


def _remote_overall_progress(task: AppTask) -> int:
    if task.stage is TaskStage.PARSING_LINK:
        return _weighted_percent(task.progress_percent, 0, 10)
    if task.stage is TaskStage.EXTRACTING_SUBTITLE:
        if (task.progress_percent or 0) >= 100:
            return 70
        return _weighted_percent(task.progress_percent, 10, 70)
    if task.stage is TaskStage.DOWNLOADING_AUDIO:
        return _weighted_percent(task.progress_percent, 10, 55)
    if task.stage is TaskStage.TRANSCRIBING:
        if "加载" in str(task.message or "") and task.progress_percent is None:
            return 55
        return _weighted_percent(task.progress_percent, 60, 88)
    if task.stage is TaskStage.SUMMARIZING:
        return _weighted_percent(task.progress_percent, 88, 98)
    if task.stage is TaskStage.COMPLETED:
        return 100
    return 0


def _weighted_percent(percent: int | None, start: int, end: int) -> int:
    if percent is None:
        return start
    clamped = max(0, min(100, int(percent)))
    return max(0, min(100, int(round(start + (end - start) * clamped / 100))))
