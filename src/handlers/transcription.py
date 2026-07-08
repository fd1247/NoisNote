"""主窗口转录任务处理逻辑。"""
from __future__ import annotations

import time
from pathlib import Path

from ..audio.preprocess import SilenceDetectionResult, detect_silence
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
                status_after_success=self._preprocess_success_status(target_record),
            )
            return
        self.processing_record = record or self.current_record

        # 静音检测：避免模型在静音时输出热词导致幻觉
        silence_result = detect_silence(audio_file)
        if silence_result.is_silent:
            log_event(
                "asr.silence.detected",
                level="WARNING",
                module="asr",
                message="检测到音频为静音，跳过转录",
                context={
                    "audio_file": file_context(audio_file),
                    "max_amplitude": silence_result.max_amplitude,
                    "rms_level": silence_result.rms_level,
                    "threshold": silence_result.threshold,
                },
            )
            self._on_transcription_failed("未识别到有效语音内容（音频为静音）", {})
            return

        if self.processing_record:
            self.processing_record = self.history_service.mark_processing_started(
                self.processing_record,
                "transcription",
                self._asr_processing_context(),
            )
        task_id = self._new_task_id("asr")
        self.active_task_ids["transcription"] = task_id
        self.processing_started_at["transcription"] = time.perf_counter()
        self.latest_transcription_percent = None
        self.is_processing = True
        self.processing_source = source
        self.recording_hint_label.setText("正在转录录音")
        self._update_recording_entry()
        self._set_processing_ui(True)
        self._sync_detail_processing_view()
        self._refresh_history_status_indicators()
        if self._is_current_record_processing():
            self._set_transcript_text("")
            self._set_summary_text("")
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
        self.transcription_worker = worker
        worker.progress.connect(self._on_transcription_progress)
        worker.completed.connect(self._on_transcription_completed)
        worker.failed.connect(self._on_transcription_failed)
        worker.cancelled.connect(self._on_transcription_cancelled)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self.active_workers.append(worker)
        worker.start()

    def _on_transcription_progress(self, progress: object) -> None:
        if isinstance(progress, TranscriptionProgress):
            self.latest_transcription_percent = progress.percent
        if self._is_current_record_processing():
            self._sync_detail_processing_view()
        self._refresh_history_status_indicators()

    def _on_transcription_completed(self, text: str, diagnostics: dict | None = None) -> None:
        self.transcription_worker = None
        record = self.processing_record
        if not text.strip():
            self._on_transcription_failed("未识别到有效语音内容", diagnostics)
            return
        task_id = self.active_task_ids.pop("transcription", "")
        if self._is_current_record_processing():
            self._set_transcript_text(text)
            self.transcript_status.setText("已加载转录")
        self._save_transcript(text, record)
        record = self.processing_record or record
        if record and diagnostics:
            timeline_items = diagnostics.get("timeline")
            if isinstance(timeline_items, list) and timeline_items:
                self.history_service.save_timeline(record, timeline_items)
                record = self.history_service.refresh_metadata(record)
                self.processing_record = record
                if self.current_record and self.current_record.record_key == record.record_key:
                    self._set_timeline_items(timeline_items)
                    self.timeline_loaded_record_id = record.record_key
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
            if self.current_record and self.current_record.record_key == record.record_key:
                self.current_record = record
                if hasattr(self, "_refresh_detail_payload"):
                    self._refresh_detail_payload()
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
        if text.strip() and self._current_task_auto_summarize_enabled():
            self.start_summarization(text, record)
        else:
            self._finish_processing(record, "转录完成")
            if getattr(self, "current_processing_task", None):
                self._finish_queue_task_success("转录完成")

    def _on_transcription_failed(self, error: str, diagnostics: dict | None = None) -> None:
        self.transcription_worker = None
        record = self.processing_record
        was_selected = bool(record and self.current_record and self.current_record.record_key == record.record_key)
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
        self._add_history_notice_if_unselected(record, "出现异常，点击查看详情")
        self.processing_record = None
        self.latest_transcription_percent = None
        if was_selected:
            self.transcript_status.setText(f"转录失败：{error}")
            if hasattr(self, "_refresh_detail_payload"):
                self._refresh_detail_payload()
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
            if was_selected:
                self._select_record_by_key(record.record_key)
        is_queue_task = self._active_queue_task() is not None
        if not is_queue_task:
            dialog_message = self._transcription_failure_dialog_message(error, diagnostics)
            if dialog_message:
                self._show_error(dialog_message)
            elif error == "未识别到有效语音内容":
                self._set_status("未识别到有效语音内容，请换一段有声音的音频后重试。")
            else:
                self._show_error("转录失败，请查看日志或尝试更换设备。")
        else:
            self._set_status(f"任务失败：{error}")
        if is_queue_task:
            pause_queue = self._is_systemic_transcription_error(error, diagnostics)
            self._finish_queue_task_failed(error, pause_queue=pause_queue)

    def _on_transcription_cancelled(self, message: str, diagnostics: dict | None = None) -> None:
        self.transcription_worker = None
        record = self.processing_record
        was_selected = bool(record and self.current_record and self.current_record.record_key == record.record_key)
        task_id = self.active_task_ids.pop("transcription", "")
        log_event(
            "asr.transcribe.cancelled",
            level="WARNING",
            module="asr",
            message="音频转录已取消",
            task_id=task_id,
            record_id=(record.record_id if record else None),
            context={
                "record": record_context(record),
                "diagnostics": diagnostics or {},
            },
        )
        self.is_processing = False
        self.processing_source = None
        self.processing_record = None
        self.latest_transcription_percent = None
        if was_selected:
            self.transcript_status.setText(message or "已取消转录")
            if hasattr(self, "_refresh_detail_payload"):
                self._refresh_detail_payload()
        self.record_button.setText("开始录音")
        self.recording_hint_label.setText("转录已取消，可重新创建录音")
        self._set_processing_ui(False)
        self._update_recording_entry()
        if record:
            record = self.history_service.mark_error(
                record,
                message or "已取消转录",
                step="transcription",
                elapsed_seconds=self._elapsed_seconds("transcription"),
            )
            if diagnostics:
                record = self.history_service.save_asr_metadata(record, diagnostics)
            self.load_recordings()
            if was_selected:
                self._select_record_by_key(record.record_key)
        if getattr(self, "current_processing_task", None):
            task = self.current_processing_task
            self.current_processing_task = None
            self.task_manager.cancel_running(task.task_id, message or "已取消转录")
            self._persist_queued_tasks()
            self._start_next_processing_task()
            return
        self._set_status(message or "已取消转录")

    def _transcription_failure_dialog_message(self, error: str, diagnostics: dict | None = None) -> str:
        error_type = str(((diagnostics or {}).get("error") or {}).get("error_type") or "")
        if error == "未识别到有效语音内容":
            return ""
        if error_type == "MissingModelDirectory" or "模型未下载" in error:
            return "转录失败：模型未下载，请先在设置 > 模型中下载 ASR 模型。"
        if error_type == "MissingModelFile" or "模型文件不完整" in error:
            return "转录失败：模型文件不完整，请在设置 > 模型中删除后重新下载。"
        if error_type in {"MissingGgufToolDir", "MissingRuntimeDependency"} or "运行时依赖" in error:
            return "转录失败：缺少 ASR 运行环境，请重新安装应用或修复运行环境。"
        if error_type == "ImportFailed" or "推理组件加载失败" in error:
            return "转录失败：ASR 推理组件加载失败，请重新安装应用或检查运行环境。"
        if error_type in {"ProcessExited", "WorkerExited"} or "异常退出" in error:
            return "转录失败：转录进程异常退出，请重试；如果持续失败，请查看日志。"
        if error_type in {"InvalidModelName", "InvalidAsrModel"} or ("ASR 模型" in error and "不可用" in error):
            return "转录失败：当前 ASR 模型不可用，请在设置中重新选择模型。"
        if "音频文件不存在" in error:
            return "转录失败：音频文件不存在，无法转录。"
        return ""

    def _normalize_transcription_error(self, error: str) -> str:
        """把常见空语音错误归一为用户可理解文案。"""
        value = (error or "").strip()
        lowered = value.lower()
        empty_markers = ("empty", "no speech", "no valid speech", "无有效语音", "未识别", "静音", "音频为静音")
        if not value or any(marker in lowered for marker in empty_markers):
            return "未识别到有效语音内容"
        return value

    def _is_systemic_transcription_error(self, error: str, diagnostics: dict | None = None) -> bool:
        error_type = str(((diagnostics or {}).get("error") or {}).get("error_type") or "")
        return error_type in {
            "MissingModelDirectory",
            "MissingModelFile",
            "MissingGgufToolDir",
            "MissingRuntimeDependency",
            "InvalidModelName",
            "InvalidAsrModel",
        } or "模型未下载" in error or "运行时依赖" in error

    def retry_transcription(self) -> None:
        """重新转录当前历史记录中的录音文件。"""
        if self.is_processing:
            if not self.current_record:
                self._show_error("请先选择一条历史记录")
                return
            if not self.current_record.audio_path.exists():
                self._show_error("当前记录没有可转录的音频文件")
                return
            if self.current_record.has_transcript and not self._confirm_retranscription(self.current_record):
                self._set_status("已取消重新转录")
                return
            self.enqueue_record_processing(
                self.current_record,
                source="manual",
                overwrite_existing=True,
                manual=True,
            )
            self._set_status("已加入处理队列")
            return
        if not self.current_record:
            self._show_error("请先选择一条历史记录")
            return
        if not self.current_record.audio_path.exists():
            self._show_error("当前记录没有可转录的音频文件")
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
            self._select_record_by_key(self.current_record.record_key)
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
