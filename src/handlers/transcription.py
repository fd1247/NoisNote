"""主窗口转录任务处理逻辑。"""
from __future__ import annotations

import time
from pathlib import Path

from ..ui.widgets.dialogs import confirm_without_icon
from ..utils.logging import file_context, log_event, record_context
from ..history.service import HistoryRecord
from ..workers.transcription import TranscriptionWorker
from ..asr.engine import TranscriptionProgress


class TranscriptionHandlers:
    """转录生命周期、重新转录和 ASR 进度处理。"""

    def start_transcription(
        self,
        audio_file: Path,
        record: HistoryRecord | None = None,
        source: str = "manual",
    ) -> None:
        target_record = record or self.current_record
        if target_record is None:
            self._show_error("没有可转录的历史记录")
            return
        if self._needs_audio_preprocess(target_record):
            self._start_audio_preprocess(
                target_record,
                source=source,
                status_after_success="已提取视频音轨",
            )
            return
        self.processing_record = record or self.current_record
        if self.processing_record:
            self.processing_record = self.history_service.mark_processing_started(
                self.processing_record,
                "transcription",
                self._asr_processing_context(),
            )
        task_id = self._new_task_id("asr")
        self.active_task_ids["transcription"] = task_id
        self.processing_started_at["transcription"] = time.perf_counter()
        self.latest_processing_messages = {"transcription": "正在加载ASR模型"}
        self.latest_transcription_percent = None
        self.is_processing = True
        self.processing_source = source
        self.recording_hint_label.setText("正在转录录音")
        self._update_recording_entry()
        self._set_processing_ui(True)
        self._sync_detail_processing_view()
        self.summary_progress.hide()
        if self._is_current_record_processing():
            self.transcript_status.setText(self.latest_processing_messages["transcription"])
            self._set_transcript_text("")
            self._set_summary_text("")
            self.summary_status.setText("等待转录完成")
        self._set_action_buttons(False)
        self.retry_transcription_button.hide()
        log_event(
            "asr.transcribe.started",
            module="asr",
            message="开始转录音频",
            task_id=task_id,
            record_id=(self.processing_record.record_id if self.processing_record else None),
            context={
                "record": record_context(self.processing_record),
                "audio_file": file_context(audio_file),
                "asr": self._asr_processing_context(),
                "source": source,
            },
        )

        worker = TranscriptionWorker(str(audio_file), self)
        worker.progress.connect(self._on_transcription_progress)
        worker.completed.connect(self._on_transcription_completed)
        worker.failed.connect(self._on_transcription_failed)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self.active_workers.append(worker)
        worker.start()

    def _on_transcription_progress(self, progress: object) -> None:
        text = self._normalize_transcription_progress(progress)
        self.latest_processing_messages["transcription"] = text
        if self._is_current_record_processing():
            self.transcript_status.setText(text)
            self._sync_detail_processing_view()

    def _normalize_transcription_progress(self, progress: object) -> str:
        """隐藏具体 ASR 模型名，只保留用户需要感知的阶段。"""
        if isinstance(progress, TranscriptionProgress):
            self.latest_transcription_percent = progress.percent
            if progress.stage == "transcribing":
                return f"正在转录 {progress.percent}%"
            return progress.message or f"正在转录 {progress.percent}%"
        value = (progress or "").strip() if isinstance(progress, str) else str(progress or "").strip()
        if "加载" in value and "模型" in value:
            return "正在加载ASR模型"
        return value or "正在转录"

    def _on_transcription_completed(self, text: str, diagnostics: dict | None = None) -> None:
        record = self.processing_record
        if not text.strip():
            self._on_transcription_failed("未识别到有效语音内容", diagnostics)
            return
        task_id = self.active_task_ids.pop("transcription", "")
        self.transcript_progress.hide()
        if self._is_current_record_processing():
            self._set_transcript_text(text)
            self.transcript_status.setText("写入历史记录")
        self._save_transcript(text, record)
        record = self.processing_record or record
        if record and diagnostics:
            timeline_items = diagnostics.get("timeline")
            if isinstance(timeline_items, list) and timeline_items:
                self.history_service.save_timeline(record, timeline_items)
                record = self.history_service.refresh_metadata(record)
                self.processing_record = record
        if record:
            record = self.history_service.mark_processing_completed(
                record,
                "transcription",
                self._elapsed_seconds("transcription"),
                self._asr_processing_context(diagnostics),
            )
            if diagnostics:
                record = self.history_service.save_asr_metadata(record, diagnostics)
            self.processing_record = record
            if self.current_record and self.current_record.record_id == record.record_id:
                self.current_record = record
        log_event(
            "asr.transcribe.completed",
            module="asr",
            message="音频转录完成",
            task_id=task_id,
            record_id=(record.record_id if record else None),
            context={
                "record": record_context(record),
                "text_length": len(text),
                "asr": self._asr_processing_context(diagnostics),
            },
        )
        self.load_recordings()

        if text.strip() and self.config["audio"].get("auto_summarize", True):
            self.start_summarization(text, record)
        else:
            self._finish_processing(record, "转录完成")
            self.manual_summary_button.setVisible(bool(text.strip()))

    def _on_transcription_failed(self, error: str, diagnostics: dict | None = None) -> None:
        record = self.processing_record
        error = self._normalize_transcription_error(error)
        task_id = self.active_task_ids.pop("transcription", "")
        if error == "未识别到有效语音内容":
            error_code = "AUD-003"
            level = "WARNING"
        else:
            error_code = "ASR-002"
            level = "ERROR"
        log_event(
            "asr.transcribe.failed",
            level=level,
            module="asr",
            message="音频转录失败",
            task_id=task_id,
            record_id=(record.record_id if record else None),
            context={
                "record": record_context(record),
                "error": error,
                "asr": self._asr_processing_context(diagnostics),
            },
            error_code=error_code,
            error_type=((diagnostics or {}).get("error") or {}).get("error_type", ""),
        )
        self.is_processing = False
        self.processing_source = None
        self.processing_record = None
        self.latest_processing_messages = {}
        self.latest_transcription_percent = None
        self.transcript_progress.hide()
        self.transcript_status.setText(f"转录失败：{error}")
        self.record_button.setText("开始录音")
        self.recording_hint_label.setText("转录失败，可重新创建录音")
        self._set_processing_ui(False)
        self._update_recording_entry()
        if record:
            record = self.history_service.mark_error(
                record,
                error,
                step="transcription",
                elapsed_seconds=self._elapsed_seconds("transcription"),
            )
            if diagnostics:
                record = self.history_service.save_asr_metadata(record, diagnostics)
            self.load_recordings()
            self._select_record_by_id(record.record_id)
        self._set_status("转录失败")

    def _normalize_transcription_error(self, error: str) -> str:
        """把常见空语音错误归一为用户可理解文案。"""
        value = (error or "").strip()
        lowered = value.lower()
        empty_markers = ("empty", "no speech", "no valid speech", "无有效语音", "未识别")
        if not value or any(marker in lowered for marker in empty_markers):
            return "未识别到有效语音内容"
        return value

    def _update_retry_transcription_button(self, record: HistoryRecord | None) -> None:
        """根据历史记录状态更新转录入口文案。"""
        if not record or not record.audio_path.exists() or self.is_processing:
            self.retry_transcription_button.hide()
            return
        self.retry_transcription_button.setText("重新转录" if record.has_transcript else "开始转录")
        self.retry_transcription_button.show()

    def retry_transcription(self) -> None:
        """重新转录当前历史记录中的录音文件。"""
        if self.is_processing:
            self._set_status("正在处理中，请稍后重试")
            return
        if not self.current_record or not self.current_record.audio_path.exists():
            self._show_error("当前记录没有可转录的录音文件")
            return
        if self.current_record.has_transcript and not self._confirm_retranscription(self.current_record):
            self._set_status("已取消重新转录")
            return
        if self.current_record.has_transcript:
            try:
                self.current_record = self.history_service.clear_generated_results(self.current_record)
            except Exception as exc:
                self._show_error(f"清理旧结果失败：{exc}")
                return
            self.load_recordings()
            self._select_record_by_id(self.current_record.record_id)
        self.retry_transcription_button.hide()
        self.start_transcription(self.current_record.audio_path, self.current_record, source="manual")

    def _confirm_retranscription(self, record: HistoryRecord) -> bool:
        """确认重新转录会覆盖当前生成结果。"""
        return confirm_without_icon(
            self,
            "重新转录",
            "重新转录会覆盖当前音频的转录和总结。\n"
            "如需保留旧结果，请手动导出或复制。",
            confirm_text="确认",
            cancel_text="取消",
        )
