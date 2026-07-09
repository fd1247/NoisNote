"""主窗口导入和音视频预处理处理逻辑。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from ..audio.preprocess import (
    AudioInputError,
    AudioPreprocessRequest,
    AudioPreprocessResult,
    is_supported_media,
    media_filter_string,
    probe_media,
    source_kind_for_path,
)
from ..utils.logging import file_context, log_event, record_context
from ..history.service import HistoryRecord
from ..tasks import TaskStage
from ..workers.preprocess import AudioPreprocessWorker


class ImportHandlers:
    """本地音视频导入、拖拽导入和视频音轨预处理。"""

    def import_audio_recording(self) -> None:
        """导入本地音视频文件并创建历史记录。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入本地音视频",
            "",
            media_filter_string(self.config),
        )
        if not file_path:
            return
        self._import_media_path(Path(file_path))

    def _import_media_path(self, file_path: Path) -> None:
        """导入单个本地音视频文件，供按钮和拖拽复用。"""
        path = file_path.expanduser()
        if not path.exists() or not path.is_file():
            log_event(
                "record.import.failed",
                level="ERROR",
                module="history",
                message="导入文件不存在",
                context={"source_file": file_context(path)},
                error_code="IMP-001",
                error_type="file_not_found",
            )
            self._show_error("拖入的文件不存在，无法导入")
            return
        if not is_supported_media(path, self.config):
            log_event(
                "record.import.failed",
                level="WARNING",
                module="history",
                message="导入文件格式不支持",
                context={"source_file": file_context(path), "source_kind": source_kind_for_path(path, self.config)},
                error_code="IMP-001",
                error_type="unsupported_format",
            )
            self._show_error("暂不支持该文件格式，请导入支持的音视频文件")
            return
        task_id = self._new_task_id("import")
        log_event(
            "record.import.started",
            module="history",
            message="开始导入本地音视频",
            task_id=task_id,
            context={"source_file": file_context(path), "source_kind": source_kind_for_path(path, self.config)},
        )
        source_kind = source_kind_for_path(path, self.config)
        try:
            probe = probe_media(path, self.config)
        except AudioInputError as exc:
            log_event(
                "record.import.failed",
                level="ERROR",
                module="history",
                message="导入文件媒体信息探测失败",
                task_id=task_id,
                context={"source_file": file_context(path), "error": exc.to_metadata()},
                error_code="IMP-001",
                error_type=exc.kind,
            )
            self._show_error(exc.message)
            return

        audio_format: dict[str, object] = {
            "sample_rate": probe.audio_sample_rate,
            "channels": probe.audio_channels,
            "format": path.suffix.lower().lstrip("."),
            "source_format": probe.source_format,
        }

        try:
            record = self.history_service.import_audio_file(
                path,
                duration_seconds=probe.duration_seconds,
                audio_format=audio_format,
                source_kind=source_kind,
            )
        except Exception as exc:
            log_event(
                "record.import.failed",
                level="ERROR",
                module="history",
                message="导入本地音视频失败",
                task_id=task_id,
                context={"source_file": file_context(path), "error": str(exc)},
                error_code="IMP-001",
                error_type=type(exc).__name__,
            )
            self._show_error(f"导入录音失败：{exc}")
            return

        self.current_record = record
        log_event(
            "record.import.completed",
            module="history",
            message="本地音视频已导入历史记录",
            task_id=task_id,
            record_id=record.record_id,
            context={
                "record": record_context(record),
                "source_file": file_context(path),
                "duration_seconds": probe.duration_seconds,
            },
        )
        status = "已导入视频" if record.source_kind == "local_video" else "已导入音频"
        self._handle_audio_record_ready(record, status, source="import")

    def dragEnterEvent(self, event) -> None:
        """接受拖入的本地音视频文件。"""
        if self._supported_drop_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._supported_drop_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        paths = self._supported_drop_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        if len(paths) > 1:
            self._set_status("已拖入多个文件，本次只导入第一个支持的音视频文件")
        self._import_media_path(paths[0])

    def _supported_drop_paths(self, mime_data) -> list[Path]:
        if not mime_data or not mime_data.hasUrls():
            return []
        paths: list[Path] = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if is_supported_media(path, self.config):
                paths.append(path)
        return paths

    def _needs_audio_preprocess(self, record: HistoryRecord | None) -> bool:
        """非目标 WAV 的本地媒体需要先标准化后再转录。"""
        if not record:
            return False
        normalized = record.normalized_audio_path
        if normalized and normalized.exists():
            return False
        if record.source_kind == "local_video":
            return True
        if record.source_kind != "local_audio":
            return False

        preprocessing = self.config.get("audio", {}).get("preprocessing", {})
        target_sample_rate = int(preprocessing.get("target_sample_rate") or 16000)
        target_channels = int(preprocessing.get("target_channels") or 1)
        audio_format = record.audio_format or {}
        source_format = str(
            audio_format.get("format")
            or record.audio_path.suffix.lower().lstrip(".")
        ).lower()
        if source_format != "wav":
            return True
        sample_rate = audio_format.get("sample_rate")
        channels = audio_format.get("channels")
        return sample_rate != target_sample_rate or channels != target_channels

    def _preprocess_success_status(self, record: HistoryRecord | None) -> str:
        """生成预处理完成后的状态文案。"""
        if record and record.source_kind == "local_video":
            return "已提取视频音轨"
        return "已标准化音频"

    def _start_audio_preprocess(
        self,
        record: HistoryRecord,
        source: str,
        status_after_success: str,
    ) -> None:
        """后台标准化音频，然后进入转录或手动等待。"""
        self.current_record = record
        self.processing_record = record
        self.processing_source = "preprocess"
        self.is_processing = True
        task_id = self._new_task_id("preprocess")
        self.active_task_ids["preprocess"] = task_id
        queue_task = self._queue_task_for_record(record)
        queue_task_id = queue_task.task_id if queue_task else ""
        if queue_task is not None:
            self.task_manager.mark_running(queue_task.task_id, TaskStage.PREPROCESSING, "正在处理音频")
        self.recording_hint_label.setText("处理音频")
        self._set_processing_ui(True)
        self.load_recordings()
        self._select_record_by_key(record.record_key)

        preprocessing = self.config.get("audio", {}).get("preprocessing", {})
        source_path = record.audio_path
        request = AudioPreprocessRequest(
            source_path=source_path,
            record_dir=record.record_dir,
            source_kind=record.source_kind or source_kind_for_path(source_path, self.config),
            target_sample_rate=int(preprocessing.get("target_sample_rate") or 16000),
            target_channels=int(preprocessing.get("target_channels") or 1),
        )
        log_event(
            "preprocess.started",
            module="preprocess",
            message="开始音视频预处理",
            task_id=task_id,
            record_id=record.record_id,
            context={
                "record": record_context(record),
                "source_file": file_context(source_path),
                "source_kind": request.source_kind,
                "target_sample_rate": request.target_sample_rate,
                "target_channels": request.target_channels,
            },
        )
        worker = AudioPreprocessWorker(request, self, config=self.config)
        worker.progress.connect(self._on_audio_preprocess_progress)
        worker.completed.connect(
            lambda result, r=record, s=source, label=status_after_success, qid=queue_task_id: self._on_audio_preprocess_completed(
                r, result, s, label, qid
            )
        )
        worker.failed.connect(lambda error, r=record, qid=queue_task_id: self._on_audio_preprocess_failed(r, error, qid))
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self.active_workers.append(worker)
        worker.start()

    def _on_audio_preprocess_progress(self, text: str, percent: int | None = None) -> None:
        message = (text or "处理音频").strip()
        if hasattr(self, "_sync_running_task_stage"):
            self._sync_running_task_stage(TaskStage.PREPROCESSING, message, percent)
        self._set_status(message)
        self._refresh_history_status_indicators()
        self._sync_detail_processing_view()

    def _on_audio_preprocess_completed(
        self,
        record: HistoryRecord,
        result: AudioPreprocessResult,
        source: str,
        status_after_success: str,
        queue_task_id: str = "",
    ) -> None:
        if self._consume_cancelled_processing_task(queue_task_id):
            return
        record = self.history_service.save_preprocess_result(record, result)
        task_id = self.active_task_ids.pop("preprocess", "")
        log_event(
            "preprocess.completed",
            module="preprocess",
            message="音视频预处理完成",
            task_id=task_id,
            record_id=record.record_id,
            context={
                "record": record_context(record),
                "normalized_audio_file": file_context(result.normalized_audio_path),
                "duration_seconds": result.duration_seconds,
                "sample_rate": result.sample_rate,
                "channels": result.channels,
                "source_format": result.source_format,
            },
        )
        self.processing_source = None
        self.is_processing = False
        self.processing_record = None
        self._set_processing_ui(False)
        self.current_record = record
        if source == "manual" or self._queue_task_for_record(record):
            self.start_transcription(record.audio_path, record, source=source)
            return
        self._handle_audio_record_ready(record, status_after_success, source=source)

    def _on_audio_preprocess_failed(
        self,
        record: HistoryRecord,
        error: AudioInputError,
        queue_task_id: str = "",
    ) -> None:
        if self._consume_cancelled_processing_task(queue_task_id):
            return
        was_selected = bool(self.current_record and self.current_record.record_key == record.record_key)
        record = self.history_service.mark_input_error(record, error)
        task_id = self.active_task_ids.pop("preprocess", "")
        error_code = {
            "unsupported_format": "IMP-001",
            "no_audio_stream": "IMP-002",
            "transcode_failed": "IMP-003",
        }.get(error.kind, "IMP-003")
        log_event(
            "preprocess.failed",
            level="ERROR",
            module="preprocess",
            message="音视频预处理失败",
            task_id=task_id,
            record_id=record.record_id,
            context={"record": record_context(record), "error": error.to_metadata()},
            error_code=error_code,
            error_type=error.kind,
        )
        self.is_processing = False
        self.processing_record = None
        self.processing_source = None
        self.latest_transcription_percent = None
        self._add_history_notice_if_unselected(record, "出现异常，点击查看详情")
        self.record_button.setText("开始录音")
        self.recording_hint_label.setText("音频处理失败")
        self._set_processing_ui(False)
        self.load_recordings()
        if was_selected:
            self._select_record_by_key(record.record_key)
            self._show_error(self._audio_preprocess_failure_message(record, error))
        else:
            self._set_status(error.message)
        if self._queue_task_for_record(record):
            self._finish_queue_task_failed(error.message)

    def _audio_preprocess_failure_message(self, record: HistoryRecord, error: AudioInputError) -> str:
        """把音视频预处理错误转为用户当下可操作的提示。"""
        reason = (error.message or "处理失败").rstrip("。")
        if error.kind == "transcode_failed":
            if record.source_kind == "local_video":
                return f"视频音轨提取失败：{reason}。请换一个视频文件或检查 ffmpeg。"
            return f"音频处理失败：{reason}。请检查文件是否可播放，或确认 ffmpeg 可用。"
        if error.kind == "no_audio_stream":
            return "音频处理失败：文件中没有可转录的音轨。"
        return f"音频处理失败：{reason}。请换一个文件，或检查 ffmpeg/ffprobe 是否可用。"

    def _handle_audio_record_ready(self, record: HistoryRecord, status: str, source: str = "manual") -> None:
        """音频进入历史记录后，按配置决定是否自动转录。"""
        self.current_record = record
        self.load_recordings()
        self._select_record_by_key(record.record_key)

        if self.config["audio"].get("auto_transcribe", True):
            task = self.enqueue_record_processing(record, source=source)
            if task is not None:
                self._set_status(f"{status}，已加入处理队列")
            return

        self.record_button.setText("开始录音")
        self.record_button.setObjectName("RecordButton")
        self.record_button.style().unpolish(self.record_button)
        self.record_button.style().polish(self.record_button)
        self.recording_hint_label.setText("音频已保存，可手动转录")
        self._set_processing_ui(False)
        self._update_recording_entry()
        self._set_status(f"{status}，等待手动转录")
