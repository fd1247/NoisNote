"""主窗口总结任务处理逻辑。"""
# pylint: disable=access-member-before-definition
from __future__ import annotations

import time

from ..utils.logging import log_event, record_context
from ..history.service import HistoryRecord
from ..llm.errors import summary_failure_code, summary_failure_message
from ..tasks import TaskStage
from ..ui.widgets.dialogs import confirm_without_icon
from ..workers.summary import SummaryWorker


class SummaryHandlers:
    """LLM 总结生命周期和进度处理。"""

    def start_summarization(self, text: str, record: HistoryRecord | None = None) -> None:
        if not text.strip():
            self._show_error("没有可总结的转录文本")
            return

        self.processing_record = record or self.current_record
        if self.processing_record:
            self.processing_record = self.history_service.mark_processing_started(
                self.processing_record,
                "summary",
            )
        task_id = self._new_task_id("summary")
        self.active_task_ids["summary"] = task_id
        queue_task = self._queue_task_for_record(self.processing_record) if hasattr(self, "_queue_task_for_record") else None
        queue_task_id = queue_task.task_id if queue_task is not None else ""
        record_key = self.processing_record.record_key if self.processing_record is not None else ""
        record_for_callback = self.processing_record
        if queue_task is not None:
            self.task_manager.mark_running(queue_task.task_id, TaskStage.SUMMARIZING, "AI总结中")
        self.processing_started_at["summary"] = time.perf_counter()
        self.is_processing = True
        if not self.processing_source:
            self.processing_source = "manual"
        self.recording_hint_label.setText("正在总结内容")
        self._update_recording_entry()
        self._set_processing_ui(True)
        self._sync_detail_processing_view()
        self._refresh_history_status_indicators()
        if self._is_current_record_processing():
            self._set_summary_text("")
        log_event(
            "summary.started",
            module="summary",
            message="开始调用 LLM 总结",
            task_id=task_id,
            record_id=(self.processing_record.record_id if self.processing_record else None),
            context={
                "record": record_context(self.processing_record),
                "transcript_length": len(text),
                "llm": self._summary_processing_context(),
            },
        )

        worker = SummaryWorker(text, self.config, self)
        self.summary_worker = worker
        if hasattr(worker, "progress"):
            worker.progress.connect(
                lambda message, task_id=queue_task_id: self._on_summary_progress(message, task_id)
            )
        worker.completed.connect(
            lambda summary, summary_task_id=task_id, task_id=queue_task_id, key=record_key, record=record_for_callback: self._on_summary_completed(
                summary,
                summary_task_id,
                task_id,
                key,
                record,
            )
        )
        worker.failed.connect(
            lambda error, summary_task_id=task_id, task_id=queue_task_id, key=record_key, record=record_for_callback: self._on_summary_failed(
                error,
                summary_task_id,
                task_id,
                key,
                record,
            )
        )
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self.active_workers.append(worker)
        worker.start()

    def _on_summary_progress(self, message: str, queue_task_id: str = "") -> None:
        if queue_task_id and getattr(self, "task_manager", None):
            running = self.task_manager.running_process_task()
            if running is None or running.task_id != queue_task_id:
                return
        if hasattr(self, "_sync_running_task_stage"):
            self._sync_running_task_stage(TaskStage.SUMMARIZING, message.strip() or "AI总结中")

    def _summary_error_code(self, error: str) -> str:
        """把常见 LLM 错误映射到稳定错误码。"""
        return summary_failure_code(error)

    def _on_summary_completed(
        self,
        summary: str,
        summary_task_id: str = "",
        queue_task_id: str = "",
        record_key: str = "",
        callback_record: HistoryRecord | None = None,
    ) -> None:
        if not self._summary_callback_is_current(summary_task_id, queue_task_id, record_key):
            return
        record = callback_record or self.processing_record
        task_id = self._pop_summary_task_id(summary_task_id)
        if self._is_current_record_processing():
            self._set_summary_text(summary)
            self.summary_status.setText("总结完成")
        self._save_summary(summary, record)
        record = self.processing_record or record
        if record:
            record = self.history_service.mark_processing_completed(
                record,
                "summary",
                self._elapsed_seconds("summary"),
                self._summary_processing_context(),
            )
            self.processing_record = record
            current_record = self.current_record
            if current_record and current_record.record_key == record.record_key:
                self.current_record = record
        log_event(
            "summary.completed",
            module="summary",
            message="LLM 总结完成",
            task_id=task_id,
            record_id=(record.record_id if record else None),
            context={
                "record": record_context(record),
                "summary_length": len(summary),
                "llm": self._summary_processing_context(),
            },
        )
        self._finish_processing(record, "总结完成")
        if getattr(self, "current_processing_task", None):
            self._finish_queue_task_success("总结完成")

    def _on_summary_failed(
        self,
        error: str,
        summary_task_id: str = "",
        queue_task_id: str = "",
        record_key: str = "",
        callback_record: HistoryRecord | None = None,
    ) -> None:
        if not self._summary_callback_is_current(summary_task_id, queue_task_id, record_key):
            return
        record = callback_record or self.processing_record
        task_id = self._pop_summary_task_id(summary_task_id)
        log_event(
            "summary.failed",
            level="ERROR",
            module="summary",
            message="LLM 总结失败",
            task_id=task_id,
            record_id=(record.record_id if record else None),
            context={
                "record": record_context(record),
                "error": error,
                "llm": self._summary_processing_context(),
            },
            error_code=self._summary_error_code(error),
            error_type=type(error).__name__,
        )
        self.is_processing = False
        self.processing_source = None
        was_selected = bool(record and self.current_record and self.current_record.record_key == record.record_key)
        self._add_history_notice_if_unselected(record, "出现异常，点击查看详情")
        self.processing_record = None
        display_message = summary_failure_message(error)
        if was_selected:
            self.summary_status.setText(display_message)
        self.record_button.setText("开始录音")
        self.recording_hint_label.setText("总结失败，可稍后手动总结")
        self._set_processing_ui(False)
        self._update_recording_entry()
        if record:
            record = self.history_service.mark_error(
                record,
                display_message,
                step="summary",
                elapsed_seconds=self._elapsed_seconds("summary"),
            )
            self.load_recordings()
            if was_selected:
                self._select_record_by_key(record.record_key)
                self.summary_status.setText(display_message)
        if self._active_queue_task() is not None:
            self._set_status(display_message)
            self._finish_queue_task_failed(display_message)
        else:
            self._show_error(display_message)

    def _summary_callback_is_current(self, summary_task_id: str, queue_task_id: str, record_key: str) -> bool:
        if queue_task_id and self._consume_cancelled_processing_task(queue_task_id):
            if summary_task_id and self.active_task_ids.get("summary", "") == summary_task_id:
                self.active_task_ids.pop("summary", None)
            return False
        active_summary_task_id = self.active_task_ids.get("summary", "")
        if summary_task_id and active_summary_task_id and active_summary_task_id != summary_task_id:
            return False
        if queue_task_id:
            running = self.task_manager.running_process_task() if getattr(self, "task_manager", None) else None
            if running is None or running.task_id != queue_task_id:
                return False
        if record_key:
            record = self.processing_record
            if record is None or record.record_key != record_key:
                return False
        return True

    def _pop_summary_task_id(self, summary_task_id: str) -> str:
        active_summary_task_id = self.active_task_ids.get("summary", "")
        if summary_task_id and active_summary_task_id != summary_task_id:
            return summary_task_id
        return self.active_task_ids.pop("summary", "")

    def manual_summarize(self) -> None:
        if self.is_processing:
            if not self.current_record:
                self._show_error("请先选择一条历史记录")
                return
            text = str(getattr(self, "transcript_plain_text", "") or "")
            if not text.strip() and self.current_record:
                text = self.history_service.read_transcript(self.current_record)
                self.transcript_plain_text = text
                self.transcript_loaded_record_id = self.current_record.record_key
                if hasattr(self, "_sync_legacy_transcript_widgets"):
                    self._sync_legacy_transcript_widgets(text)
            if not text.strip():
                self._show_error("当前记录没有可总结的转录文本")
                return
            if self.current_record.has_summary:
                accepted = confirm_without_icon(
                    self,
                    "生成总结",
                    "当前记录已有总结内容，是否覆盖",
                    confirm_text="覆盖",
                    cancel_text="取消",
                )
                if not accepted:
                    self._set_status("已取消生成总结")
                    return
            self.enqueue_record_processing(
                self.current_record,
                source="manual",
                overwrite_existing=False,
                manual=True,
                summary_only=True,
            )
            self._set_status("已加入处理队列")
            return
        if not self.current_record:
            self._show_error("请先选择一条历史记录")
            return
        text = str(getattr(self, "transcript_plain_text", "") or "")
        if not text.strip() and self.current_record:
            text = self.history_service.read_transcript(self.current_record)
            self.transcript_plain_text = text
            self.transcript_loaded_record_id = self.current_record.record_key
            if hasattr(self, "_sync_legacy_transcript_widgets"):
                self._sync_legacy_transcript_widgets(text)
        if not text.strip():
            self._show_error("当前记录没有可总结的转录文本")
            return
        if self.current_record.has_summary:
            accepted = confirm_without_icon(
                self,
                "生成总结",
                "当前记录已有总结内容，是否覆盖",
                confirm_text="覆盖",
                cancel_text="取消",
            )
            if not accepted:
                self._set_status("已取消生成总结")
                return
        self.start_summarization(text, self.current_record)
