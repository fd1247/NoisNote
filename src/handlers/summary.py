"""主窗口总结任务处理逻辑。"""
# pylint: disable=access-member-before-definition
from __future__ import annotations

import time

from ..utils.logging import log_event, record_context
from ..history.service import HistoryRecord
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
                self._summary_processing_context(),
            )
        task_id = self._new_task_id("summary")
        self.active_task_ids["summary"] = task_id
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
        self.manual_summary_button.setVisible(False)
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
        worker.completed.connect(self._on_summary_completed)
        worker.failed.connect(self._on_summary_failed)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self.active_workers.append(worker)
        worker.start()

    def _summary_error_code(self, error: str) -> str:
        """把常见 LLM 错误映射到稳定错误码。"""
        value = (error or "").lower()
        if "api key" in value or "key" in value:
            return "LLM-001"
        if "timeout" in value or "超时" in value:
            return "LLM-002"
        if "status" in value or "http" in value or "api" in value:
            return "LLM-003"
        return "LLM-004"

    def _on_summary_completed(self, summary: str) -> None:
        record = self.processing_record
        task_id = self.active_task_ids.pop("summary", "")
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

    def _on_summary_failed(self, error: str) -> None:
        record = self.processing_record
        task_id = self.active_task_ids.pop("summary", "")
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
        if was_selected:
            self.summary_status.setText(f"总结失败：{error}")
        self.record_button.setText("开始录音")
        self.recording_hint_label.setText("总结失败，可稍后手动总结")
        self._set_processing_ui(False)
        if was_selected:
            self.manual_summary_button.setVisible(bool(self.transcript_text.toPlainText().strip()))
        self._update_recording_entry()
        if record:
            record = self.history_service.mark_error(
                record,
                error,
                step="summary",
                elapsed_seconds=self._elapsed_seconds("summary"),
            )
            self.load_recordings()
            if was_selected:
                self._select_record_by_key(record.record_key)
        self._show_error(f"总结失败：{error}")

    def manual_summarize(self) -> None:
        self.start_summarization(self.transcript_text.toPlainText(), self.current_record)
