"""主窗口共享处理状态辅助逻辑。"""
from __future__ import annotations

import time
from typing import Any

from ..app.config import DEFAULT_MODEL_CATALOG_BY_NAME
from ..history.service import HistoryRecord


class ProcessingHandlers:
    """共享处理界面状态、结果保存和 worker 清理逻辑。"""

    def _is_current_record_processing(self) -> bool:
        return bool(
            self.current_record
            and self.processing_record
            and self.current_record.record_id == self.processing_record.record_id
        )

    def _sync_detail_processing_view(self) -> None:
        """让详情区动态条只跟随当前选中的处理记录。"""
        show_processing = self.is_processing and self._is_current_record_processing()
        if not show_processing:
            self.transcript_progress.hide()
            self.summary_progress.hide()
            return
        if self.processing_started_at.get("summary") is not None:
            self.transcript_progress.hide()
            self.summary_progress.show()
            self.summary_status.setText(self.latest_processing_messages.get("summary") or "总结中")
            self.manual_summary_button.setVisible(False)
        else:
            self.transcript_progress.show()
            if self.latest_transcription_percent is None:
                self.transcript_progress.setRange(0, 0)
            else:
                self.transcript_progress.setRange(0, 100)
                self.transcript_progress.setValue(self.latest_transcription_percent)
            self.summary_progress.hide()
            self.manual_summary_button.setVisible(False)
            self.transcript_status.setText(
                self.latest_processing_messages.get("transcription") or "正在转录"
            )

    def _save_transcript(self, text: str, record: HistoryRecord | None = None) -> None:
        target = record or self.current_record
        if not target:
            return
        self.history_service.save_transcript(target, text)
        refreshed = self.history_service.refresh_metadata(target)
        if self.current_record and self.current_record.record_id == refreshed.record_id:
            self.current_record = refreshed
        if self.processing_record and self.processing_record.record_id == refreshed.record_id:
            self.processing_record = refreshed

    def _save_summary(self, summary: str, record: HistoryRecord | None = None) -> None:
        target = record or self.current_record
        if not target:
            return
        self.history_service.save_summary(target, summary)
        refreshed = self.history_service.refresh_metadata(target)
        if self.current_record and self.current_record.record_id == refreshed.record_id:
            self.current_record = refreshed
        if self.processing_record and self.processing_record.record_id == refreshed.record_id:
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
        self.is_processing = False
        self.processing_record = None
        self.processing_source = None
        self.latest_processing_messages = {}
        self.record_button.setText("开始录音")
        self.record_button.setObjectName("RecordButton")
        self.record_button.style().unpolish(self.record_button)
        self.record_button.style().polish(self.record_button)
        self.recording_hint_label.setText("准备捕获系统声音")
        self._set_processing_ui(False)
        self._update_recording_entry()
        self.load_recordings()
        if record:
            self._select_record_by_id(record.record_id)
        self._set_status(status)

    def _cleanup_worker(self, worker: Any) -> None:
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        worker.deleteLater()

