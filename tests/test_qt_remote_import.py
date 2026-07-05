from __future__ import annotations

import copy
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.app.config import DEFAULT_MODEL_CATALOG, QWEN3_ASR_GGUF_06B_ID
from src.app.main_window import MainWindow
from src.history.service import HistoryService
from src.remote_import.types import RemoteMediaInfo


def make_config(root: Path) -> dict:
    return {
        "demo_audio_imported": True,
        "data_root": str(root),
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
            "auto_transcribe": False,
            "auto_summarize": False,
        },
        "models": {
            "root_dir": str(root / "models"),
            "catalog": copy.deepcopy(DEFAULT_MODEL_CATALOG),
            "downloaded": {},
        },
    }


def make_window(monkeypatch, tmp_path: Path) -> MainWindow:
    config = make_config(tmp_path)
    monkeypatch.setattr("src.app.main_window.get_config", lambda: config)
    monkeypatch.setattr("src.app.main_window.save_config", lambda _config: None)
    monkeypatch.setattr("src.handlers.settings.save_config", lambda _config: None)
    monkeypatch.setattr("src.app.main_window.ensure_dirs", lambda _config=None: None)
    monkeypatch.setattr("src.app.main_window.AudioRecorder", lambda output_dir: None)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    app.processEvents()
    return window


def wait_for_workers(window: MainWindow, timeout_ms: int = 1000) -> None:
    app = QApplication.instance() or QApplication([])
    elapsed = 0
    while window.active_workers and elapsed < timeout_ms:
        app.processEvents()
        QTest.qWait(10)
        elapsed += 10
    app.processEvents()


def test_remote_import_button_is_in_quick_toolbar(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)
    try:
        assert not hasattr(window, "remote_import_sidebar_button")
        assert window.remote_import_toolbar_button.toolTip() == "从链接导入"
    finally:
        window.close()


def test_remote_import_over_two_hours_cancel_does_not_create_record(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)

    class FakeRemoteImportService:
        def __init__(self, history_service, config=None):
            self.history_service = history_service

        def probe(self, url: str) -> RemoteMediaInfo:
            return RemoteMediaInfo(
                url=url,
                extractor="youtube",
                webpage_url=url,
                title="Long Video",
                duration_seconds=7201,
            )

    monkeypatch.setattr("src.handlers.remote_import.RemoteImportService", FakeRemoteImportService)
    monkeypatch.setattr("src.handlers.remote_import.confirm_without_icon", lambda *args, **kwargs: False)

    try:
        before = len(window.history_service.scan())
        window._start_remote_import("https://www.youtube.com/watch?v=demo")
        wait_for_workers(window)
        after = len(window.history_service.scan())

        assert after == before
        assert window.status_label.text() == "已取消链接导入"
    finally:
        window.close()


def test_remote_import_create_record_failure_is_handled(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)

    class FakeRemoteImportService:
        def __init__(self, history_service, config=None):
            self.history_service = history_service

        def probe(self, url: str) -> RemoteMediaInfo:
            return RemoteMediaInfo(
                url=url,
                extractor="youtube",
                webpage_url=url,
                title="Remote Video",
                duration_seconds=30,
            )

    errors: list[str] = []
    monkeypatch.setattr("src.handlers.remote_import.RemoteImportService", FakeRemoteImportService)
    monkeypatch.setattr(window.history_service, "create_remote_record", lambda _info: (_ for _ in ()).throw(OSError("bad record name")))
    monkeypatch.setattr(window, "_show_error", lambda message: errors.append(message))

    try:
        window._start_remote_import("https://www.youtube.com/shorts/qWFo8GKXHq8")
        wait_for_workers(window)

        assert not window.is_processing
        assert window.processing_record is None
        assert "remote_import" not in window.active_task_ids
        assert errors and "bad record name" in errors[-1]
    finally:
        window.close()


def test_remote_subtitle_record_disables_playback(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "recordings")
        info = RemoteMediaInfo(
            url="https://www.youtube.com/watch?v=demo",
            extractor="youtube",
            webpage_url="https://www.youtube.com/watch?v=demo",
            title="Subtitle Only",
            duration_seconds=60,
        )
        record = service.create_remote_record(info)
        service.save_transcript(record, "字幕文本")
        record = service.save_remote_metadata(record, {"source_kind": "remote_subtitle", "transcript_source": "external_subtitle"})
        window.history_service = service
        window.load_recordings()
        window.select_history_index(0)

        assert window.current_record is not None
        assert not window.current_record.audio_path.exists()
        assert window.current_record.has_transcript
        assert not window.playback_play_button.isEnabled()
        assert window.transcript_text.toPlainText() == "字幕文本"
    finally:
        window.close()
