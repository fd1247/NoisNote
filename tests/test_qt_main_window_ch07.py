from __future__ import annotations

import copy
import os
import wave
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QProgressBar, QToolButton
from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtTest import QTest

from src.audio.preprocess import AudioInputError, AudioPreprocessResult
from src.app.config import DEFAULT_MODEL_CATALOG, QWEN3_ASR_GGUF_06B_ID
from src.history.service import HistoryService
from src.app.main_window import MainWindow
from src.asr.engine import TranscriptionProgress
from src.tasks import manager as task_manager_module
from src.tasks.persistence import TaskQueueStore
from src.tasks.types import AppTask, TaskKind, TaskOptions, TaskSnapshot, TaskStage, TaskStatus


def write_wav(path: Path, frames: int = 16000, rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\0\0" * frames)


def make_config(root: Path) -> dict:
    return {
        "data_root": str(root),
        "demo_audio_imported": True,
        "selected_asr": {"model": QWEN3_ASR_GGUF_06B_ID, "model_path": "", "device": "auto"},
        "qwen3_asr_gguf": {
            "tool_dir": str(root / "vendor" / "qwen3-asr-gguf"),
            "chunk_size": 40.0,
            "memory_num": 1,
            "n_ctx": 2048,
            "context": "",
        },
        "llm": {"api_key": "", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
        "audio": {
            "output_dir": str(root / "recordings"),
            "auto_transcribe": True,
            "auto_summarize": True,
            "capture": {
                "mode": "system",
                "sample_rate": 16000,
                "channels": 1,
                "chunk_size": 1024,
                "silence_threshold": 2,
                "silence_hint_seconds": 5,
            },
            "preprocessing": {
                "supported_audio_formats": ["wav", "mp3"],
                "supported_video_formats": ["mp4"],
                "target_sample_rate": 16000,
                "target_channels": 1,
            },
        },
        "notebooks": [
            {"id": "default", "name": "默认笔记本", "path": str(root / "recordings"), "is_default": True}
        ],
        "active_notebook_id": "default",
        "models": {
            "root_dir": str(root / "models"),
            "catalog": copy.deepcopy(DEFAULT_MODEL_CATALOG),
            "downloaded": {},
        },
    }


class FakeRecorder:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.settings = None

    def configure(self, settings):
        self.settings = settings

    def get_device_name(self):
        return "测试设备"

    def capture_source_label(self):
        labels = {
            "system": "系统声音",
            "microphone": "麦克风",
        }
        return labels.get(self.settings.mode.value, "系统声音") if self.settings else "系统声音"

    def get_duration(self):
        return 0

    def get_rms_level(self):
        return 0

    def cleanup(self):
        pass


def make_window(monkeypatch, tmp_path: Path, config: dict | None = None) -> MainWindow:
    config = config or make_config(tmp_path)
    app_config_dir = tmp_path / "app-config"
    monkeypatch.setattr("src.app.config.APP_CONFIG_DIR", app_config_dir, raising=False)
    monkeypatch.setattr("src.app.config.CONFIG_DIR", app_config_dir, raising=False)
    monkeypatch.setattr("src.app.main_window.get_config", lambda: config)
    monkeypatch.setattr("src.app.main_window.save_config", lambda _config: None)
    monkeypatch.setattr("src.app.main_window.confirm_without_icon", lambda *args, **kwargs: True)
    monkeypatch.setattr("src.handlers.settings.save_config", lambda _config: None)
    monkeypatch.setattr("src.app.main_window.ensure_dirs", lambda _config=None: None)
    monkeypatch.setattr("src.app.main_window.AudioRecorder", FakeRecorder)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    app.processEvents()
    return window


def test_capture_mode_defaults_to_system(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.capture_mode_combo.currentData() == "system"
        assert window.recorder.settings.mode.value == "system"
    finally:
        window.close()
        app.processEvents()


def test_capture_mode_ignores_previous_microphone_config_on_startup(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    config = make_config(tmp_path)
    config["audio"]["capture"]["mode"] = "microphone"
    window = make_window(monkeypatch, tmp_path, config)
    try:
        assert window.capture_mode_combo.currentData() == "system"
        assert window.recorder.settings.mode.value == "system"
        assert config["audio"]["capture"]["mode"] == "system"
    finally:
        window.close()
        app.processEvents()


def test_capture_mode_combo_updates_recorder(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        index = window.capture_mode_combo.findData("microphone")
        window.capture_mode_combo.setCurrentIndex(index)

        assert window.recorder.settings.mode.value == "microphone"
        assert "麦克风" in window.recording_hint_label.text()
        assert window.capture_mode_combo.findData("mixed") < 0
    finally:
        window.close()
        app.processEvents()


def test_record_button_does_not_accept_space_focus(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.record_button.focusPolicy() == Qt.NoFocus
        assert not window.record_button.autoDefault()
        assert not window.record_button.isDefault()
    finally:
        window.close()
        app.processEvents()


def test_structured_transcription_progress_does_not_show_detail_status(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "long" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window.current_record = record
        window.processing_record = record
        window.is_processing = True
        window.processing_started_at["transcription"] = 1.0

        window._on_transcription_progress(
            TranscriptionProgress("transcribing", 37, 3996, 10800, "正在转录音频")
        )

        assert window.detail_processing_status_label.text() == ""
        assert not window.detail_processing_status_label.isVisible()
        assert window.latest_transcription_percent == 37
    finally:
        window.close()
        app.processEvents()


def test_input_error_is_visible_in_history_detail(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        source = tmp_path / "bad.mp3"
        source.write_bytes(b"bad")
        record = service.import_audio_file(source)
        error = type(
            "FakeError",
            (),
            {"to_metadata": lambda self: {"kind": "transcode_failed", "message": "转码失败。", "details": "stderr"}},
        )()
        record = service.mark_input_error(record, error)
        window.history_service = service

        window._load_history_record(record)

        assert record.last_error == {"stage": "input", "message": "转码失败。", "details": "stderr"}
        assert "音频处理失败：stderr" == window.transcript_status.text()
    finally:
        window.close()
        app.processEvents()


def test_audio_preprocess_failure_shows_blocking_dialog(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    messages: list[str] = []
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window.current_record = record
        monkeypatch.setattr(window, "_show_error", lambda message: messages.append(message))

        window._on_audio_preprocess_failed(record, AudioInputError("transcode_failed", "转码失败。", "stderr"))

        assert messages == ["音频处理失败：转码失败。请检查文件是否可播放，或确认 ffmpeg 可用。"]
        assert service.scan()[0].last_error == {"stage": "input", "message": "转码失败。", "details": "stderr"}
    finally:
        window.close()
        app.processEvents()


def test_audio_import_bypasses_preprocess_and_uses_original_file(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "meeting.mp3"
        source.write_bytes(b"fake mp3")
        service = HistoryService(tmp_path / "records")
        record = service.import_audio_file(source)
        window.history_service = service
        started: list[Path] = []
        monkeypatch.setattr(window, "start_transcription", lambda audio_file, record=None, source="manual": started.append(audio_file))

        window._handle_audio_record_ready(record, "已导入音频", source="import")

        assert started == [record.audio_path]
        assert record.audio_path == source
        assert not (record.record_dir / "audio.normalized.wav").exists()
    finally:
        window.close()
        app.processEvents()


def test_mp3_import_displays_probed_duration(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    config = make_config(tmp_path)
    config["audio"]["auto_transcribe"] = False
    window = make_window(monkeypatch, tmp_path, config)
    try:
        source = tmp_path / "meeting.mp3"
        source.write_bytes(b"fake mp3")
        monkeypatch.setattr(
            "src.handlers.media_import.probe_media",
            lambda path, config=None: SimpleNamespace(
                duration_seconds=49.2,
                audio_sample_rate=44100,
                audio_channels=2,
                source_format="mp3",
            ),
        )

        window._import_media_path(source)

        assert window.current_record is not None
        assert window.current_record.duration_seconds == 49.2
        assert window.detail_duration_label.text() == "00:49"
        metadata = window.current_record.metadata_path.read_text(encoding="utf-8")
        assert '"duration_seconds": 49.2' in metadata
    finally:
        window.close()
        app.processEvents()


def test_import_media_path_rejects_probe_failure(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "broken.mp3"
        source.write_bytes(b"broken mp3")
        monkeypatch.setattr(
            "src.handlers.media_import.probe_media",
            lambda path, config=None: (_ for _ in ()).throw(
                AudioInputError("file_unreadable", "文件损坏或无法读取。", "bad file")
            ),
        )
        errors: list[str] = []
        monkeypatch.setattr(window, "_show_error", lambda message: errors.append(message))

        window._import_media_path(source)

        assert errors == ["文件损坏或无法读取。"]
        assert window.current_record is None
        assert not (Path(window.config["audio"]["output_dir"]) / "broken").exists()
    finally:
        window.close()
        app.processEvents()


def test_import_media_path_rejects_full_queue_before_creating_record(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(task_manager_module, "MAX_QUEUE_SIZE", 0)
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "meeting.mp3"
        source.write_bytes(b"fake mp3")
        errors: list[str] = []
        probe_calls: list[Path] = []
        monkeypatch.setattr(window, "_show_error", lambda message: errors.append(message))
        monkeypatch.setattr(
            "src.handlers.media_import.probe_media",
            lambda path, config=None: probe_calls.append(path),
        )

        window._import_media_path(source)

        assert errors == ["队列已满，请先移除任务或等待任务完成"]
        assert probe_calls == []
        assert window.history_service.scan() == []
    finally:
        window.close()
        app.processEvents()


def test_video_import_preprocesses_to_normalized_audio(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "screen.mp4"
        source.write_bytes(b"fake mp4")
        service = HistoryService(tmp_path / "records")
        record = service.import_audio_file(source)
        window.history_service = service
        result = AudioPreprocessResult(
            normalized_audio_path=record.record_dir / "audio.normalized.wav",
            original_path=record.audio_path,
            duration_seconds=12.0,
            sample_rate=16000,
            channels=1,
            source_format="mp4",
        )
        result.normalized_audio_path.write_bytes(b"wav")

        refreshed = service.save_preprocess_result(record, result)

        assert refreshed.source_kind == "local_video"
        assert refreshed.audio_path.name == "audio.normalized.wav"
        assert refreshed.normalized_audio_path == result.normalized_audio_path
    finally:
        window.close()
        app.processEvents()


def test_video_import_with_auto_transcribe_off_does_not_preprocess(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.config["audio"]["auto_transcribe"] = False
        source = tmp_path / "screen.mp4"
        source.write_bytes(b"fake mp4")
        service = HistoryService(tmp_path / "records")
        record = service.import_audio_file(source)
        window.history_service = service
        preprocess_calls: list[str] = []
        monkeypatch.setattr(
            window,
            "_start_audio_preprocess",
            lambda *args, **kwargs: preprocess_calls.append("preprocess"),
        )

        window._handle_audio_record_ready(record, "已导入视频", source="import")

        assert preprocess_calls == []
        assert not hasattr(window, "retry_transcription_button")
        assert window.status_label.text() == "已导入视频，等待手动转录"
        assert not (record.record_dir / "audio.normalized.wav").exists()
    finally:
        window.close()
        app.processEvents()


def test_window_filters_supported_drop_paths(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        audio = tmp_path / "meeting.mp3"
        unsupported = tmp_path / "notes.txt"
        audio.write_bytes(b"mp3")
        unsupported.write_text("notes", encoding="utf-8")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(unsupported)), QUrl.fromLocalFile(str(audio))])

        paths = window._supported_drop_paths(mime)

        assert window.acceptDrops() is True
        assert paths == [audio]
    finally:
        window.close()
        app.processEvents()


def test_drop_event_imports_all_supported_files_and_skips_unsupported(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        first = tmp_path / "first.mp3"
        second = tmp_path / "second.wav"
        unsupported = tmp_path / "notes.txt"
        first.write_bytes(b"mp3")
        second.write_bytes(b"wav")
        unsupported.write_text("notes", encoding="utf-8")

        mime = QMimeData()
        mime.setUrls(
            [
                QUrl.fromLocalFile(str(first)),
                QUrl.fromLocalFile(str(unsupported)),
                QUrl.fromLocalFile(str(second)),
            ]
        )

        class FakeDropEvent:
            def __init__(self, mime_data):
                self._mime_data = mime_data
                self.accepted = False
                self.ignored = False

            def mimeData(self):
                return self._mime_data

            def acceptProposedAction(self):
                self.accepted = True

            def ignore(self):
                self.ignored = True

        imported: list[Path] = []
        monkeypatch.setattr(window, "_import_media_path", lambda path: imported.append(path))

        event = FakeDropEvent(mime)
        window.dropEvent(event)

        assert event.accepted is True
        assert event.ignored is False
        assert imported == [first, second]
        assert "已导入 2 个文件，跳过 1 个不支持的文件" in window.status_label.text()
    finally:
        window.close()
        app.processEvents()


def test_import_media_path_from_drop_uses_history_flow(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "meeting.mp3"
        source.write_bytes(b"mp3")
        monkeypatch.setattr(
            "src.handlers.media_import.probe_media",
            lambda path, config=None: SimpleNamespace(
                duration_seconds=49.2,
                audio_sample_rate=44100,
                audio_channels=2,
                source_format="mp3",
            ),
        )
        handled: list[str] = []
        monkeypatch.setattr(
            window,
            "_handle_audio_record_ready",
            lambda record, status, source="manual": handled.append(record.record_id),
        )

        window._import_media_path(source)

        assert handled == [window.current_record.record_id]
        assert window.current_record.audio_path.exists()
        assert window.current_record.source_kind == "local_audio"
    finally:
        window.close()
        app.processEvents()


def test_start_transcription_preprocesses_video_when_needed(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "screen.mp4"
        source.write_bytes(b"fake mp4")
        service = HistoryService(tmp_path / "records")
        record = service.import_audio_file(source)
        window.history_service = service
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            window,
            "_start_audio_preprocess",
            lambda record, source, status_after_success: calls.append((record.record_id, source)),
        )

        window.start_transcription(record.audio_path, record, source="manual")

        assert calls == [(record.record_id, "manual")]
    finally:
        window.close()
        app.processEvents()


def test_start_transcription_preprocesses_imported_mp3(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "meeting.mp3"
        source.write_bytes(b"fake mp3")
        service = HistoryService(tmp_path / "records")
        record = service.import_audio_file(
            source,
            duration_seconds=49.2,
            audio_format={"sample_rate": 44100, "channels": 2, "format": "mp3", "source_format": "mp3"},
            source_kind="local_audio",
        )
        window.history_service = service
        calls: list[tuple[str, str, str]] = []
        monkeypatch.setattr(
            window,
            "_start_audio_preprocess",
            lambda record, source, status_after_success: calls.append(
                (record.record_id, source, status_after_success)
            ),
        )

        window.start_transcription(record.audio_path, record, source="manual")

        assert calls == [(record.record_id, "manual", "已标准化音频")]
    finally:
        window.close()
        app.processEvents()


def test_manual_video_preprocess_completion_continues_transcription(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.config["audio"]["auto_transcribe"] = False
        source = tmp_path / "screen.mp4"
        source.write_bytes(b"fake mp4")
        service = HistoryService(tmp_path / "records")
        record = service.import_audio_file(source)
        window.history_service = service
        result = AudioPreprocessResult(
            normalized_audio_path=record.record_dir / "audio.normalized.wav",
            original_path=record.audio_path,
            duration_seconds=12.0,
            sample_rate=16000,
            channels=1,
            source_format="mp4",
        )
        result.normalized_audio_path.write_bytes(b"wav")
        started: list[Path] = []

        def fake_start(audio_file, record=None, source="manual"):
            started.append(audio_file)

        monkeypatch.setattr(window, "start_transcription", fake_start)

        window._on_audio_preprocess_completed(record, result, "manual", "已提取视频音轨")

        assert started == [result.normalized_audio_path]
    finally:
        window.close()
        app.processEvents()


def test_ready_record_enqueues_processing_when_auto_transcribe_enabled(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "ready.wav"
        write_wav(source)
        record = window.history_service.adopt_audio_file(source)
        window.config["audio"]["auto_transcribe"] = True
        started: list[str] = []
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: started.append(task.record_key))

        window._handle_audio_record_ready(record, "已导入音频", source="import")

        assert started == [record.record_key]
        assert window.task_manager.snapshot().running[0].record_key == record.record_key
    finally:
        window.close()
        app.processEvents()


def test_second_ready_record_waits_in_queue(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        first_source = tmp_path / "first.wav"
        second_source = tmp_path / "second.wav"
        write_wav(first_source)
        write_wav(second_source)
        first = window.history_service.adopt_audio_file(first_source)
        second = window.history_service.adopt_audio_file(second_source)
        window.config["audio"]["auto_transcribe"] = True
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: None)

        window._handle_audio_record_ready(first, "已保存录音", source="recording")
        window._handle_audio_record_ready(second, "已导入音频", source="import")

        snapshot = window.task_manager.snapshot()
        assert [task.record_key for task in snapshot.running] == [first.record_key]
        assert [task.record_key for task in snapshot.queued] == [second.record_key]
    finally:
        window.close()
        app.processEvents()


def test_finish_queue_task_starts_next(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        first_source = tmp_path / "first.wav"
        second_source = tmp_path / "second.wav"
        write_wav(first_source)
        write_wav(second_source)
        first = window.history_service.adopt_audio_file(first_source)
        second = window.history_service.adopt_audio_file(second_source)
        window.config["audio"]["auto_transcribe"] = True
        started: list[str] = []
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: started.append(task.record_key))

        window.enqueue_record_processing(first, source="recording")
        window.enqueue_record_processing(second, source="import")

        window._finish_queue_task_success("转录完成")

        assert started[-1] == second.record_key
        assert window.task_manager.snapshot().running[0].record_key == second.record_key
    finally:
        window.close()
        app.processEvents()


def test_queued_preprocess_completion_continues_same_task(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "screen.mp4"
        source.write_bytes(b"fake mp4")
        service = HistoryService(tmp_path / "records")
        record = service.import_audio_file(source)
        window.history_service = service
        preprocess_calls: list[str] = []
        monkeypatch.setattr(
            window,
            "_start_audio_preprocess",
            lambda record, source, status_after_success: preprocess_calls.append(record.record_key),
        )

        window.enqueue_record_processing(record, source="import")

        running_before = window.task_manager.snapshot().running[0]
        result = AudioPreprocessResult(
            normalized_audio_path=record.record_dir / "audio.normalized.wav",
            original_path=record.audio_path,
            duration_seconds=12.0,
            sample_rate=16000,
            channels=1,
            source_format="mp4",
        )
        result.normalized_audio_path.write_bytes(b"wav")
        continued: list[tuple[Path, str]] = []
        monkeypatch.setattr(
            window,
            "start_transcription",
            lambda audio_file, record=None, source="manual": continued.append((audio_file, source)),
        )

        window._on_audio_preprocess_completed(record, result, "import", "已提取视频音轨")

        snapshot = window.task_manager.snapshot()
        assert preprocess_calls == [record.record_key]
        assert continued == [(result.normalized_audio_path, "import")]
        assert [task.task_id for task in snapshot.running] == [running_before.task_id]
        assert snapshot.queued == ()
    finally:
        window.close()
        app.processEvents()


def test_queued_preprocess_failure_marks_failed_and_advances_queue(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "meeting.mp3"
        source.write_bytes(b"fake mp3")
        next_source = tmp_path / "next.wav"
        write_wav(next_source)
        service = HistoryService(tmp_path / "records")
        record = service.import_audio_file(
            source,
            duration_seconds=49.2,
            audio_format={"sample_rate": 44100, "channels": 2, "format": "mp3", "source_format": "mp3"},
            source_kind="local_audio",
        )
        next_record = service.adopt_audio_file(next_source)
        window.history_service = service
        monkeypatch.setattr(window, "_start_audio_preprocess", lambda *args, **kwargs: None)

        window.enqueue_record_processing(record, source="import")

        started: list[str] = []
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: started.append(task.record_key))
        window.enqueue_record_processing(next_record, source="import")

        window._on_audio_preprocess_failed(record, AudioInputError("transcode_failed", "转码失败。", "stderr"))

        snapshot = window.task_manager.snapshot()
        assert started == [next_record.record_key]
        assert [task.record_key for task in snapshot.running] == [next_record.record_key]
        assert snapshot.completed[0].record_key == record.record_key
        assert snapshot.completed[0].status is TaskStatus.FAILED
    finally:
        window.close()
        app.processEvents()


def test_cancelled_preprocess_completion_does_not_continue_transcription(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "screen.mp4"
        source.write_bytes(b"fake mp4")
        next_source = tmp_path / "next.wav"
        write_wav(next_source)
        service = HistoryService(tmp_path / "records")
        record = service.import_audio_file(source)
        next_record = service.adopt_audio_file(next_source)
        window.history_service = service
        preprocess_calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            window,
            "_start_audio_preprocess",
            lambda record, source, status_after_success: preprocess_calls.append((record.record_key, source)),
        )

        task = window.enqueue_record_processing(record, source="manual")
        assert task is not None
        window.processing_source = "preprocess"
        window.processing_record = record
        window.is_processing = True

        started_next: list[str] = []
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: started_next.append(task.record_key))
        queued_task = window.enqueue_record_processing(next_record, source="import")
        assert queued_task is not None

        class FakePreprocessWorker:
            def __init__(self) -> None:
                self.cancelled = False

            def request_cancel(self) -> None:
                self.cancelled = True

        worker = FakePreprocessWorker()
        window.preprocess_worker = worker

        window.cancel_processing_task(task.task_id)

        snapshot = window.task_manager.snapshot()
        assert worker.cancelled is True
        assert [item.task_id for item in snapshot.running] == [task.task_id]
        assert snapshot.running[0].message == "正在取消"
        assert started_next == []
        app.processEvents()
        running_item = window.running_task_list.itemAt(0).widget()
        assert any(label.text() == "正在取消" for label in running_item.findChildren(QLabel))

        result = AudioPreprocessResult(
            normalized_audio_path=record.record_dir / "audio.normalized.wav",
            original_path=record.audio_path,
            duration_seconds=12.0,
            sample_rate=16000,
            channels=1,
            source_format="mp4",
        )
        result.normalized_audio_path.write_bytes(b"wav")
        continued: list[tuple[Path, str]] = []
        monkeypatch.setattr(
            window,
            "start_transcription",
            lambda audio_file, record=None, source="manual": continued.append((audio_file, source)),
        )

        window._on_audio_preprocess_completed(record, result, "manual", "已提取视频音轨", task.task_id)

        snapshot = window.task_manager.snapshot()
        assert preprocess_calls == [(record.record_key, "manual")]
        assert started_next == [next_record.record_key]
        assert continued == []
        assert [task.record_key for task in snapshot.running] == [next_record.record_key]
        assert snapshot.completed[0].record_key == record.record_key
        assert snapshot.completed[0].status is TaskStatus.CANCELLED
    finally:
        window.close()
        app.processEvents()


def test_cancelled_preprocess_without_next_task_clears_processing_state_on_late_completion(
    monkeypatch, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "screen.mp4"
        source.write_bytes(b"fake mp4")
        service = HistoryService(tmp_path / "records")
        record = service.import_audio_file(source)
        window.history_service = service
        start_transcription_calls: list[tuple[Path, str]] = []
        monkeypatch.setattr(
            window,
            "start_transcription",
            lambda audio_file, record=None, source="manual": start_transcription_calls.append((audio_file, source)),
        )

        task = window.enqueue_record_processing(record, source="manual")
        assert task is not None
        window.processing_source = "preprocess"
        window.processing_record = record
        window.is_processing = True
        start_transcription_calls.clear()

        window.cancel_processing_task(task.task_id)

        assert window.task_manager.snapshot().running == ()
        assert window.is_processing is False
        assert window.processing_source is None
        assert window.processing_record is None

        result = AudioPreprocessResult(
            normalized_audio_path=record.record_dir / "audio.normalized.wav",
            original_path=record.audio_path,
            duration_seconds=12.0,
            sample_rate=16000,
            channels=1,
            source_format="mp4",
        )
        result.normalized_audio_path.write_bytes(b"wav")

        window._on_audio_preprocess_completed(
            record,
            result,
            "manual",
            "mock-preprocess-status",
            task.task_id,
        )

        assert start_transcription_calls == []
    finally:
        window.close()
        app.processEvents()


def test_cancelled_preprocess_without_next_task_clears_processing_state_on_late_failure(
    monkeypatch, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "screen.mp4"
        source.write_bytes(b"fake mp4")
        service = HistoryService(tmp_path / "records")
        record = service.import_audio_file(source)
        window.history_service = service
        start_transcription_calls: list[tuple[Path, str]] = []
        monkeypatch.setattr(
            window,
            "start_transcription",
            lambda audio_file, record=None, source="manual": start_transcription_calls.append((audio_file, source)),
        )

        task = window.enqueue_record_processing(record, source="manual")
        assert task is not None
        window.processing_source = "preprocess"
        window.processing_record = record
        window.is_processing = True
        start_transcription_calls.clear()

        window.cancel_processing_task(task.task_id)

        assert window.task_manager.snapshot().running == ()
        assert window.is_processing is False
        assert window.processing_source is None
        assert window.processing_record is None

        window._on_audio_preprocess_failed(
            record,
            AudioInputError("transcode_failed", "error", "stderr"),
            task.task_id,
        )

        assert start_transcription_calls == []
        snapshot = window.task_manager.snapshot()
        assert snapshot.running == ()
    finally:
        window.close()
        app.processEvents()


def test_queued_transcription_completion_uses_task_auto_summarize_false(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "ready.wav"
        write_wav(source)
        record = window.history_service.adopt_audio_file(source)
        window.config["audio"]["auto_summarize"] = False
        monkeypatch.setattr(window, "start_transcription", lambda audio_file, record=None, source="manual": None)

        window.enqueue_record_processing(record, source="import")

        window.config["audio"]["auto_summarize"] = True
        summaries: list[str] = []
        monkeypatch.setattr(window, "start_summarization", lambda text, record=None: summaries.append(text))

        window._on_transcription_completed("Generated transcript.")

        assert summaries == []
    finally:
        window.close()
        app.processEvents()


def test_queued_transcription_completion_uses_task_auto_summarize_true(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "ready.wav"
        write_wav(source)
        record = window.history_service.adopt_audio_file(source)
        window.config["audio"]["auto_summarize"] = True
        monkeypatch.setattr(window, "start_transcription", lambda audio_file, record=None, source="manual": None)

        window.enqueue_record_processing(record, source="import")

        window.config["audio"]["auto_summarize"] = False
        summaries: list[tuple[str, str]] = []
        monkeypatch.setattr(
            window,
            "start_summarization",
            lambda text, record=None: summaries.append((text, record.record_key if record else "")),
        )

        window._on_transcription_completed("Generated transcript.")

        assert summaries == [("Generated transcript.", record.record_key)]
    finally:
        window.close()
        app.processEvents()


def test_running_task_updates_transcription_progress(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "ready.wav"
        write_wav(source)
        record = window.history_service.adopt_audio_file(source)
        monkeypatch.setattr(window, "start_transcription", lambda audio_file, record=None, source="manual": None)

        window.enqueue_record_processing(record, source="import")
        window._on_transcription_progress(
            TranscriptionProgress(
                stage="chunk",
                message="正在转录第 1 段",
                percent=37,
                processed_seconds=12.0,
                total_seconds=30.0,
            )
        )

        running = window.task_manager.snapshot().running[0]
        assert running.stage is TaskStage.TRANSCRIBING
        assert running.message == "转录中"
        assert running.progress_percent == 37
    finally:
        window.close()
        app.processEvents()


def test_task_panel_transcription_progress_hides_chunk_count_and_loading_percent(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "ready.wav"
        write_wav(source)
        record = window.history_service.adopt_audio_file(source)
        monkeypatch.setattr(window, "start_transcription", lambda audio_file, record=None, source="manual": None)

        window.enqueue_record_processing(record, source="import")
        window._on_transcription_progress(
            TranscriptionProgress(
                stage="loading_asr_model",
                percent=5,
                processed_seconds=None,
                total_seconds=None,
                message="正在加载ASR模型",
            )
        )
        app.processEvents()
        running_item = window.running_task_list.itemAt(0).widget()
        labels = [label.text() for label in running_item.findChildren(QLabel)]
        assert "正在加载ASR模型" in labels
        assert not any("5%" in text for text in labels)

        window._on_transcription_progress(
            TranscriptionProgress(
                stage="chunk",
                message="正在转录第 1/8 段",
                percent=37,
                processed_seconds=12.0,
                total_seconds=30.0,
            )
        )
        app.processEvents()
        running_item = window.running_task_list.itemAt(0).widget()
        labels = [label.text() for label in running_item.findChildren(QLabel)]
        assert "转录中" in labels
        assert "转录中 37%" not in labels
        assert running_item.findChild(QProgressBar, "TaskProgressBar").value() == 43
        assert "43%" in labels
        assert not any("1/8" in text for text in labels)
    finally:
        window.close()
        app.processEvents()


def test_task_panel_shows_resume_action_for_paused_queue_and_resumes_next_task(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        first_source = tmp_path / "first.wav"
        second_source = tmp_path / "second.wav"
        write_wav(first_source)
        write_wav(second_source)
        first = window.history_service.adopt_audio_file(first_source)
        second = window.history_service.adopt_audio_file(second_source)
        started: list[str] = []
        messages: list[str] = []
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: started.append(task.task_id))
        monkeypatch.setattr(window, "_show_error", lambda message: messages.append(message))

        first_task = window.enqueue_record_processing(first, source="import")
        second_task = window.enqueue_record_processing(second, source="import")
        assert first_task is not None
        assert second_task is not None
        window.processing_record = first
        window.is_processing = True
        window._on_transcription_failed("模型未下载", {"error": {"error_type": "MissingModelDirectory"}})
        app.processEvents()

        assert messages == [
            "转录失败：模型未下载，请先在设置 > 模型中下载 ASR 模型。\n\n修复后可手动恢复排队任务。"
        ]
        assert window.task_manager.snapshot().paused_reason == "模型未下载"
        assert not window.task_queue_resume_button.isHidden()
        assert window.task_queue_resume_button.toolTip() == "恢复队列"
        assert window.queued_task_section.title_button.text() == "排队中（1）"
        assert not hasattr(window, "task_queue_pause_banner")

        window.task_queue_resume_button.click()
        app.processEvents()

        assert window.task_manager.snapshot().paused_reason == ""
        assert window.task_queue_resume_button.isHidden()
        assert started == [first_task.task_id, second_task.task_id]
    finally:
        window.close()
        app.processEvents()


def test_running_task_updates_summary_stage(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "ready.wav"
        write_wav(source)
        record = window.history_service.adopt_audio_file(source)
        monkeypatch.setattr(window, "start_transcription", lambda audio_file, record=None, source="manual": None)
        window.enqueue_record_processing(record, source="import")

        class FakeSummaryWorker:
            def __init__(self, *_args, **_kwargs):
                self.completed = SimpleNamespace(connect=lambda *_: None)
                self.failed = SimpleNamespace(connect=lambda *_: None)
                self.finished = SimpleNamespace(connect=lambda *_: None)

            def start(self):
                return None

            def deleteLater(self):
                return None

        monkeypatch.setattr("src.handlers.summary.SummaryWorker", FakeSummaryWorker)
        window.start_summarization("transcript", record)

        running = window.task_manager.snapshot().running[0]
        assert running.stage is TaskStage.SUMMARIZING
        assert running.message == "AI总结中"
    finally:
        window.close()
        app.processEvents()


def test_summary_progress_keeps_task_message_as_ai_summary(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "ready.wav"
        write_wav(source)
        record = window.history_service.adopt_audio_file(source)
        monkeypatch.setattr(window, "start_transcription", lambda audio_file, record=None, source="manual": None)
        window.enqueue_record_processing(record, source="import")
        window.task_manager.mark_running(
            window.task_manager.snapshot().running[0].task_id,
            TaskStage.SUMMARIZING,
            "AI总结中",
        )

        window._on_summary_progress("正在调用 LLM 总结", window.task_manager.snapshot().running[0].task_id)

        running = window.task_manager.snapshot().running[0]
        assert running.stage is TaskStage.SUMMARIZING
        assert running.message == "AI总结中"
    finally:
        window.close()
        app.processEvents()


def test_recording_task_updates_elapsed_and_queues_saved_record(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "busy.wav"
        write_wav(source)
        busy_record = window.history_service.adopt_audio_file(source)
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: None)
        window.enqueue_record_processing(busy_record, source="import")

        output = tmp_path / "new-recording.wav"
        write_wav(output)

        class FakeRecorder:
            def __init__(self):
                self.is_recording = False
                self.duration = 65.0

            def configure(self, *_args, **_kwargs):
                return None

            def start_recording(self):
                self.is_recording = True

            def stop_recording(self):
                self.is_recording = False
                return str(output)

            def get_device_name(self):
                return "fake"

            def capture_source_label(self):
                return "系统声音"

            def get_recording_error(self):
                return None

            def get_duration(self):
                return self.duration

            def get_rms_level(self):
                return 0

            def cleanup(self):
                return None

        window.recorder = FakeRecorder()
        window.config["audio"]["auto_transcribe"] = True

        window.start_recording()
        window._refresh_recording_state()

        running = window.task_manager.snapshot().running
        assert [task.kind for task in running] == [TaskKind.PROCESS_RECORD, TaskKind.RECORDING]
        assert running[1].message == "已录制 00:01:05"

        window.stop_recording()

        snapshot = window.task_manager.snapshot()
        assert [task.kind for task in snapshot.running] == [TaskKind.PROCESS_RECORD]
        assert len(snapshot.queued) == 1
        assert snapshot.queued[0].source == "recording"
        assert snapshot.queued[0].title.startswith("录音_")
    finally:
        window.close()
        app.processEvents()


def test_recording_task_actions_pause_resume_and_stop_recording(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        snapshot = TaskSnapshot(
            running=(
                AppTask(
                    task_id="recording-1",
                    kind=TaskKind.RECORDING,
                    status=TaskStatus.RUNNING,
                    stage=TaskStage.WAITING,
                    title="录音",
                    message="已录制 00:00:03",
                ),
            ),
            queued=(),
            completed=(),
        )

        class FakeRecorder:
            is_paused = False

            def cleanup(self):
                return None

        window.recorder = FakeRecorder()
        paused: list[bool] = []
        resumed: list[bool] = []
        stopped: list[bool] = []
        monkeypatch.setattr(window, "pause_recording", lambda: paused.append(True))
        monkeypatch.setattr(window, "resume_recording", lambda: resumed.append(True))
        monkeypatch.setattr(window, "stop_recording", lambda: stopped.append(True))

        window._refresh_task_panel(snapshot)
        window.show()
        app.processEvents()

        running_item = window.running_task_list.itemAt(0).widget()
        buttons = {button.toolTip(): button for button in running_item.findChildren(QToolButton)}
        assert set(buttons) == {"暂停录制", "停止录制"}
        for button in buttons.values():
            assert button.size().width() >= 30
            assert button.iconSize().width() >= 18
            assert abs(button.geometry().center().y() - running_item.rect().center().y()) <= 3
        buttons["暂停录制"].click()
        buttons["停止录制"].click()
        assert paused == [True]
        assert stopped == [True]

        window.recorder.is_paused = True
        window._refresh_task_panel(snapshot)
        app.processEvents()

        running_item = window.running_task_list.itemAt(0).widget()
        buttons = {button.toolTip(): button for button in running_item.findChildren(QToolButton)}
        assert set(buttons) == {"继续录制", "停止录制"}
        buttons["继续录制"].click()
        assert resumed == [True]
    finally:
        window.close()
        app.processEvents()


def test_pausing_recording_keeps_elapsed_message_without_paused_flash(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        class FakeRecorder:
            is_paused = False

            def pause_recording(self):
                self.is_paused = True

            def stop_recording(self):
                return ""

            def get_device_name(self):
                return "fake"

            def get_duration(self):
                return 3.0

            def cleanup(self):
                return None

        window.recorder = FakeRecorder()
        window.is_recording = True
        task = window.task_manager.start_recording("录音")
        window.active_task_ids["recording"] = task.task_id

        window.pause_recording()
        app.processEvents()

        running = window.task_manager.snapshot().running
        assert running[0].message == "已录制 00:00:03"
        assert "已暂停" not in running[0].message
    finally:
        window.close()
        app.processEvents()


def test_running_recording_task_shows_elapsed_time_in_task_panel(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        snapshot = TaskSnapshot(
            running=(
                AppTask(
                    task_id="recording-1",
                    kind=TaskKind.RECORDING,
                    status=TaskStatus.RUNNING,
                    stage=TaskStage.WAITING,
                    title="录音",
                    message="已录制 00:00:03",
                ),
            ),
            queued=(),
            completed=(),
        )

        window._refresh_task_panel(snapshot)
        app.processEvents()

        running_item = window.running_task_list.itemAt(0).widget()
        labels = running_item.findChildren(QLabel)
        assert any(label.text() == "已录制 00:00:03" for label in labels)
    finally:
        window.close()
        app.processEvents()


def test_running_recording_task_view_opens_recording_dialog(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        snapshot = TaskSnapshot(
            running=(
                AppTask(
                    task_id="recording-1",
                    kind=TaskKind.RECORDING,
                    status=TaskStatus.RUNNING,
                    stage=TaskStage.WAITING,
                    title="录音",
                    message="已录制 00:00:03",
                ),
            ),
            queued=(),
            completed=(),
        )
        shown: list[bool] = []
        monkeypatch.setattr(window, "show_recording_dialog", lambda: shown.append(True))

        window._refresh_task_panel(snapshot)
        app.processEvents()

        running_item = window.running_task_list.itemAt(0).widget()
        QTest.mouseClick(running_item, Qt.LeftButton, pos=running_item.rect().center())
        app.processEvents()

        assert shown == [True]
    finally:
        window.close()
        app.processEvents()


def test_running_processing_task_view_selects_record(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        snapshot = TaskSnapshot(
            running=(
                AppTask(
                    task_id="process-1",
                    kind=TaskKind.PROCESS_RECORD,
                    status=TaskStatus.RUNNING,
                    stage=TaskStage.TRANSCRIBING,
                    record_key="default:record-1",
                    title="会议录音",
                    message="正在转录",
                ),
            ),
            queued=(),
            completed=(),
        )
        selected: list[str] = []
        monkeypatch.setattr(window, "_select_record_by_key", lambda key: selected.append(key) or True)

        window._refresh_task_panel(snapshot)
        app.processEvents()

        running_item = window.running_task_list.itemAt(0).widget()
        assert running_item.findChildren(QPushButton) == []
        assert [button.toolTip() for button in running_item.findChildren(QToolButton)] == ["取消"]
        QTest.mouseClick(running_item, Qt.LeftButton, pos=running_item.rect().center())
        app.processEvents()

        assert selected == ["default:record-1"]
    finally:
        window.close()
        app.processEvents()


def test_completed_task_view_reports_deleted_record_and_removes_stale_row(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        task = AppTask(
            task_id="completed-missing",
            kind=TaskKind.PROCESS_RECORD,
            status=TaskStatus.COMPLETED,
            stage=TaskStage.COMPLETED,
            record_key="default:missing",
            notebook_id="default",
            record_id="missing",
            title="已删除记录",
            message="处理完成",
        )
        errors: list[str] = []
        saved: list[list[str]] = []
        monkeypatch.setattr(window, "_show_error", lambda message: errors.append(message))
        monkeypatch.setattr(window.task_queue_store, "save", lambda tasks: saved.append([item.task_id for item in tasks]))
        window.task_manager.load_tasks([task])
        app.processEvents()

        completed_item = window.completed_task_list.itemAt(0).widget()
        QTest.mouseClick(completed_item, Qt.LeftButton, pos=completed_item.rect().center())
        app.processEvents()

        assert errors == ["历史记录已删除或不存在，已从已处理列表移除"]
        assert window.task_manager.snapshot().completed == ()
        assert saved[-1] == []
    finally:
        window.close()
        app.processEvents()


def test_retry_completed_task_reports_deleted_record_and_removes_stale_row(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        task = AppTask(
            task_id="failed-1",
            kind=TaskKind.PROCESS_RECORD,
            status=TaskStatus.FAILED,
            stage=TaskStage.FAILED,
            record_key="default:deleted",
            title="已删除记录",
            message="转录失败",
            error_message="转录失败",
        )
        window.task_manager.load_tasks([task])
        errors: list[str] = []
        monkeypatch.setattr(window, "_show_error", lambda message: errors.append(message))

        window._retry_task_record("default:deleted")

        assert errors == ["原始历史记录已删除，无法重试。请重新导入原文件或重新录音。"]
        assert window.task_manager.snapshot().completed == ()
    finally:
        window.close()
        app.processEvents()


def test_retry_remote_input_failure_keeps_remote_workflow_source(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        record = window.history_service.create_remote_record(
            SimpleNamespace(
                url="https://example.com/video",
                webpage_url="https://example.com/video",
                extractor="example",
                title="remote",
                duration_seconds=30,
            )
        )
        record = window.history_service.mark_input_error(record, "下载失败")
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: None)
        task = window.task_manager.enqueue_process_record(
            record,
            source="remote_import",
            auto_summarize=False,
            input_url="https://example.com/video",
        )
        window.task_manager.start_next_if_idle()
        window.task_manager.fail_running(task.task_id, "下载失败")

        window._retry_task_record(record.record_key)

        retried = window.task_manager.snapshot().running[0]
        assert retried.source == "remote_import"
        assert retried.input_url == "https://example.com/video"
    finally:
        window.close()
        app.processEvents()


def test_retry_summary_stage_starts_summary_without_retranscribing(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "summary.wav"
        write_wav(source)
        record = window.history_service.adopt_audio_file(source)
        window.history_service.save_transcript(record, "已有转录")
        task = window.task_manager.enqueue_process_record(record, source="import", auto_summarize=True)
        task.restart_stage = TaskStage.SUMMARIZING
        execute_task = window._execute_processing_task
        monkeypatch.setattr(window, "_execute_processing_task", lambda _task: None)
        window.task_manager.start_next_if_idle()
        started: list[str] = []
        monkeypatch.setattr(window, "start_summarization", lambda text, record=None: started.append(text))
        monkeypatch.setattr(window, "start_transcription", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应重新转录")))

        execute_task(task)

        assert started == ["已有转录"]
    finally:
        window.close()
        app.processEvents()


def test_retry_cancelled_summary_keeps_transcript_file(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "summary-retry.wav"
        write_wav(source)
        record = window.history_service.adopt_audio_file(source)
        window.history_service.save_transcript(record, "保留的转录")
        task = window.task_manager.enqueue_process_record(
            record,
            source="import",
            auto_summarize=True,
            overwrite_existing=True,
            summary_only=True,
        )
        monkeypatch.setattr(window, "_execute_processing_task", lambda _task: None)
        window.task_manager.start_next_if_idle()
        window.task_manager.mark_running(task.task_id, TaskStage.SUMMARIZING, "AI总结中")
        window.task_manager.cancel_running(task.task_id, "已取消")

        window._retry_task_record(record.record_key)

        retried = window.task_manager.snapshot().running[0]
        assert retried.options.summary_only is True
        assert retried.options.overwrite_existing is True
        assert record.transcript_path.read_text(encoding="utf-8") == "保留的转录"
    finally:
        window.close()
        app.processEvents()


def test_restored_queue_moves_to_completed_on_startup(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "restored.wav"
    write_wav(source)
    record = HistoryService(tmp_path / "records").adopt_audio_file(source)
    restored_task = AppTask(
        task_id="task-restored",
        kind=TaskKind.PROCESS_RECORD,
        status=TaskStatus.QUEUED,
        stage=TaskStage.WAITING,
        record_key=record.record_key,
        notebook_id=record.notebook_id,
        record_id=record.record_id,
        source="import",
        title=record.display_name,
        message="等待处理",
        created_at="2026-07-08T12:00:00",
        queued_at="2026-07-08T12:00:00",
        options=TaskOptions(auto_summarize=False),
    )
    monkeypatch.setattr("src.handlers.task_queue.TaskQueueStore.load", lambda self, history_service: [restored_task])
    monkeypatch.setattr("src.handlers.task_queue.TaskQueueHandlers._start_next_processing_task", lambda self: None)

    window = make_window(monkeypatch, tmp_path)
    try:
        snapshot = window.task_manager.snapshot()

        assert window.status_label.text() == "已将 1 个未完成任务移至已处理"
        assert snapshot.running == ()
        assert snapshot.queued == ()
        assert snapshot.completed[0].task_id == restored_task.task_id
        assert snapshot.completed[0].message == "应用退出，任务中断"
    finally:
        window.close()
        app.processEvents()


def test_ready_record_does_not_claim_queued_when_queue_is_full(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(task_manager_module, "MAX_QUEUE_SIZE", 1)
    config = make_config(tmp_path)
    window = make_window(monkeypatch, tmp_path, config)
    try:
        first_source = tmp_path / "first.wav"
        second_source = tmp_path / "second.wav"
        third_source = tmp_path / "third.wav"
        write_wav(first_source)
        write_wav(second_source)
        write_wav(third_source)
        first = window.history_service.adopt_audio_file(first_source)
        second = window.history_service.adopt_audio_file(second_source)
        third = window.history_service.adopt_audio_file(third_source)
        window.config["audio"]["auto_transcribe"] = True
        errors: list[str] = []
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: None)
        monkeypatch.setattr(window, "_show_error", lambda message: errors.append(message) or window._set_status(message))

        window.enqueue_record_processing(first, source="recording")
        window.enqueue_record_processing(second, source="import")
        window._handle_audio_record_ready(third, "已导入音频", source="import")

        assert errors == ["队列已满，最多可排队 1 个任务"]
        assert window.status_label.text() == "队列已满，最多可排队 1 个任务"
    finally:
        window.close()
        app.processEvents()


def test_startup_moves_restored_running_and_queued_tasks_to_completed(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source_running = tmp_path / "running.wav"
    source_queued = tmp_path / "queued.wav"
    write_wav(source_running)
    write_wav(source_queued)
    history = HistoryService(tmp_path / "recordings")
    running_record = history.import_audio_file(source_running)
    queued_record = history.import_audio_file(source_queued)
    running_task = AppTask(
        task_id="task-running",
        kind=TaskKind.PROCESS_RECORD,
        status=TaskStatus.RUNNING,
        stage=TaskStage.TRANSCRIBING,
        record_key=running_record.record_key,
        notebook_id=running_record.notebook_id,
        record_id=running_record.record_id,
        source="import",
        title=running_record.display_name,
        progress_percent=17,
        options=TaskOptions(auto_summarize=True),
    )
    queued_task = AppTask(
        task_id="task-queued",
        kind=TaskKind.PROCESS_RECORD,
        status=TaskStatus.QUEUED,
        stage=TaskStage.WAITING,
        record_key=queued_record.record_key,
        notebook_id=queued_record.notebook_id,
        record_id=queued_record.record_id,
        source="import",
        title=queued_record.display_name,
        options=TaskOptions(auto_summarize=True),
    )
    monkeypatch.setattr(TaskQueueStore, "load", lambda self, history_service: [running_task, queued_task])

    window = make_window(monkeypatch, tmp_path)
    try:
        snapshot = window.task_manager.snapshot()

        assert snapshot.running == ()
        assert snapshot.queued == ()
        assert [(task.task_id, task.status, task.message) for task in snapshot.completed] == [
            (queued_task.task_id, TaskStatus.INTERRUPTED, "应用退出，任务中断"),
            (running_task.task_id, TaskStatus.INTERRUPTED, "应用退出，任务中断"),
        ]
        assert snapshot.completed[0].restart_stage is None
        assert snapshot.completed[1].restart_stage is TaskStage.TRANSCRIBING
        assert all(task.progress_percent is None for task in snapshot.completed)
    finally:
        window.close()
        app.processEvents()


def test_close_preparation_interrupts_queued_task_without_starting_it(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        first_source = tmp_path / "running.wav"
        second_source = tmp_path / "queued.wav"
        write_wav(first_source)
        write_wav(second_source)
        first = window.history_service.import_audio_file(first_source)
        second = window.history_service.import_audio_file(second_source)
        started: list[str] = []
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: started.append(task.task_id))

        window.enqueue_record_processing(first, source="import")
        window.enqueue_record_processing(second, source="import")
        running = window.task_manager.snapshot().running[0]
        window.current_processing_task = running
        window.processing_record = first
        window.processing_source = "import"
        window._closing_for_exit = True

        window.prepare_task_queue_for_close()
        window._start_next_processing_task()

        snapshot = window.task_manager.snapshot()
        assert started == [running.task_id]
        assert snapshot.running == ()
        assert snapshot.queued == ()
        assert [(task.record_key, task.message) for task in snapshot.completed] == [
            (second.record_key, "应用退出，任务中断"),
            (first.record_key, "应用退出，任务中断"),
        ]
    finally:
        window.close()
        app.processEvents()


def test_recording_ready_adds_manual_retry_task_when_queue_is_full(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(task_manager_module, "MAX_QUEUE_SIZE", 0)
    window = make_window(monkeypatch, tmp_path)
    try:
        source = tmp_path / "recording.wav"
        write_wav(source)
        record = window.history_service.adopt_audio_file(source)
        window.config["audio"]["auto_transcribe"] = True
        errors: list[str] = []
        monkeypatch.setattr(window, "_show_error", lambda message: errors.append(message))

        window._handle_audio_record_ready(record, "已保存录音", source="recording")

        assert errors == []
        assert window.history_service.get_record_by_key(record.record_key) is not None
        assert window.task_manager.snapshot().queued == ()
        completed = window.task_manager.snapshot().completed
        assert len(completed) == 1
        assert completed[0].record_key == record.record_key
        assert completed[0].status is TaskStatus.CANCELLED
        assert completed[0].message == "处理队列已满，需手动重试"
    finally:
        window.close()
        app.processEvents()
