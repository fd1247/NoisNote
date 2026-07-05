"""主窗口共享处理状态辅助逻辑。"""
from __future__ import annotations

from html import escape
import time
from typing import Any

from ..app.config import DEFAULT_MODEL_CATALOG_BY_NAME
from ..history.service import HistoryRecord
from ..history.types import HistoryStatus


class ProcessingHandlers:
    """共享处理界面状态、结果保存和 worker 清理逻辑。"""

    def _is_current_record_processing(self) -> bool:
        return bool(
            self.current_record
            and self.processing_record
            and self.current_record.record_key == self.processing_record.record_key
        )

    def _sync_detail_processing_view(self) -> None:
        """让详情区顶部任务状态只跟随当前选中的处理记录。"""
        html = self._detail_processing_status_html()
        self.detail_processing_status_label.setText(html)
        self.detail_processing_status_label.setVisible(bool(html))
        if self.is_processing and self._is_current_record_processing():
            self.manual_summary_button.setVisible(False)

    def _detail_processing_status_html(self) -> str:
        if not (self.is_processing and self._is_current_record_processing()):
            return ""
        if self.processing_started_at.get("summary") is not None:
            return (
                '<span style="color:#15803d;">转录完成</span>'
                '<span style="color:#9ca3af;"> → </span>'
                '<span style="color:#374151;">正在总结</span>'
            )
        percent = self.latest_transcription_percent if self.latest_transcription_percent is not None else 0
        text = f"正在转录: {percent}%"
        if self.config.get("audio", {}).get("auto_summarize", True):
            return (
                f'<span style="color:#374151;">{escape(text)}</span>'
                '<span style="color:#9ca3af;"> → </span>'
                '<span style="color:#6b7280;">等待总结</span>'
            )
        return f'<span style="color:#374151;">{escape(text)}</span>'

    def _history_subtitle_for_record(self, record: HistoryRecord) -> str:
        if self.is_processing and self.processing_record and record.record_key == self.processing_record.record_key:
            if self.processing_started_at.get("summary") is not None:
                return "AI总结中"
            percent = self.latest_transcription_percent if self.latest_transcription_percent is not None else 0
            return f"正在转录: {percent}%"
        if self.current_record and self.current_record.record_key == record.record_key:
            return ""
        if record.record_key in self.history_record_notices:
            return self.history_record_notices[record.record_key]
        if record.status == HistoryStatus.ERROR and record.record_key not in self.dismissed_history_notice_ids:
            return "出现异常，点击查看详情"
        return ""

    def _refresh_history_status_indicators(self) -> None:
        if hasattr(self, "history_tree"):
            self.history_tree.update_subtitles(self._history_subtitle_for_record)

    def _dismiss_history_notice(self, record: HistoryRecord) -> None:
        self.history_record_notices.pop(record.record_key, None)
        if record.status == HistoryStatus.ERROR:
            self.dismissed_history_notice_ids.add(record.record_key)

    def _add_history_notice_if_unselected(self, record: HistoryRecord | None, text: str) -> None:
        if not record:
            return
        if self.current_record and self.current_record.record_key == record.record_key:
            return
        self.history_record_notices[record.record_key] = text

    def _save_transcript(self, text: str, record: HistoryRecord | None = None) -> None:
        target = record or self.current_record
        if not target:
            return
        self.history_service.save_transcript(target, text)
        refreshed = self.history_service.refresh_metadata(target)
        if self.current_record and self.current_record.record_key == refreshed.record_key:
            self.current_record = refreshed
        if self.processing_record and self.processing_record.record_key == refreshed.record_key:
            self.processing_record = refreshed

    def _save_summary(self, summary: str, record: HistoryRecord | None = None) -> None:
        target = record or self.current_record
        if not target:
            return
        self.history_service.save_summary(target, summary)
        refreshed = self.history_service.refresh_metadata(target)
        if self.current_record and self.current_record.record_key == refreshed.record_key:
            self.current_record = refreshed
        if self.processing_record and self.processing_record.record_key == refreshed.record_key:
            self.processing_record = refreshed

    def _asr_processing_context(self, diagnostics: dict | None = None) -> dict:
        """生成转录步骤元数据上下文。"""
        asr_config = self.config.get("selected_asr", {})
        model_name = asr_config.get("model", "")
        context = {
            "model": model_name,
            "model_path": asr_config.get("model_path", ""),
            "device": asr_config.get("device", "cpu"),
            "adapter": "qwen3_asr_gguf",
            "engine": "qwen3-asr-gguf",
        }
        catalog_item = DEFAULT_MODEL_CATALOG_BY_NAME.get(model_name)
        if catalog_item:
            context["adapter"] = catalog_item.get("adapter", "")
            context["model_size"] = catalog_item.get("model_size", "")

        # 添加热词表信息
        try:
            from ..hotwords.service import HotwordService
            hotword_service = HotwordService(self.config)
            active_sets = hotword_service.get_active_hotword_sets()
            context["hotword_sets"] = [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "word_count": len(s.get("words", [])),
                }
                for s in active_sets
            ]
        except Exception:
            context["hotword_sets"] = []

        if diagnostics:
            context["timings"] = diagnostics.get("timings", {})
            context["performance"] = diagnostics.get("performance", {})
            context["resolved_device"] = diagnostics.get("resolved_device", "")
            if isinstance(diagnostics.get("timestamps"), dict):
                context["timestamps"] = diagnostics.get("timestamps")
            if diagnostics.get("error"):
                context["error"] = diagnostics.get("error")
        return context

    def _summary_processing_context(self) -> dict:
        """生成总结步骤元数据上下文，不包含 API Key。"""
        llm_config = self.config.get("llm", {})
        return {
            "provider": llm_config.get("provider", "openai"),
            "model": llm_config.get("model", ""),
            "base_url": llm_config.get("base_url", ""),
        }

    def _elapsed_seconds(self, step: str) -> float | None:
        """计算处理步骤耗时。"""
        started_at = self.processing_started_at.pop(step, None)
        if started_at is None:
            return None
        return time.perf_counter() - started_at

    def _set_processing_ui(self, processing: bool) -> None:
        self.record_button.setEnabled(not processing and bool(self.recorder))
        self._sync_sidebar_actions()

    def _set_action_buttons(self, visible: bool) -> None:
        self.manual_summary_button.setVisible(visible)

    def _finish_processing(self, record: HistoryRecord | None, status: str) -> None:
        was_selected = bool(record and self.current_record and self.current_record.record_key == record.record_key)
        self._add_history_notice_if_unselected(record, "处理完成，点击查看详情")
        self.is_processing = False
        self.processing_record = None
        self.processing_source = None
        self.record_button.setText("开始录音")
        self.record_button.setObjectName("RecordButton")
        self.record_button.style().unpolish(self.record_button)
        self.record_button.style().polish(self.record_button)
        self.recording_hint_label.setText("准备捕获系统声音")
        self._set_processing_ui(False)
        self._update_recording_entry()
        self.load_recordings()
        if record and was_selected:
            self._select_record_by_key(record.record_key)
        self._set_status(status)

    def _cleanup_worker(self, worker: Any) -> None:
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        worker.deleteLater()
