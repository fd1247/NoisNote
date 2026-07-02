from __future__ import annotations

import copy
import os
import wave
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QMimeData, Qt, QUrl

from src.audio.preprocess import AudioInputError, AudioPreprocessResult
from src.app.config import DEFAULT_MODEL_CATALOG, QWEN3_ASR_GGUF_06B_ID
from src.history.service import HistoryService, HistoryStatus
from src.app.main_window import MainWindow
from src.asr.engine import TranscriptionProgress


def write_wav(path: Path, frames: int = 16000, rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\0\0" * frames)


def make_config(root: Path) -> dict:
    return {
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
    monkeypatch.setattr("src.app.main_window.get_config", lambda: config)
    monkeypatch.setattr("src.app.main_window.save_config", lambda _config: None)
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


def test_structured_transcription_progress_shows_percent(monkeypatch, tmp_path: Path) -> None:
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

        assert "正在转录: 37%" in window.detail_processing_status_label.text()
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

        assert record.status == HistoryStatus.ERROR
        assert "音频处理失败：转码失败。" == window.transcript_status.text()
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
        assert window.retry_transcription_button.text() == "开始转录"
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
