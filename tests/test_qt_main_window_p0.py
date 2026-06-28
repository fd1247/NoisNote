from __future__ import annotations

import copy
import os
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app.config import DEFAULT_MODEL_CATALOG, QWEN3_ASR_GGUF_06B_ID
from src.history.service import HistoryService, HistoryStatus
from src.app.main_window import MainWindow


def write_wav(path: Path, frames: int = 16000, rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\0\0" * frames)


def make_config(root: Path) -> dict:
    return {
        "selected_asr": {"model": QWEN3_ASR_GGUF_06B_ID, "model_path": "", "device": "auto"},
        "qwen3_asr_gguf": {
            "tool_dir": str(root / "vendor" / "qwen3-asr-gguf"),
            "chunk_size": 40.0,
            "memory_num": 1,
            "n_ctx": 2048,
            "context": "",
            "hotwords": [],
        },
        "llm": {"api_key": "", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
        "audio": {
            "output_dir": str(root / "recordings"),
            "auto_transcribe": True,
            "auto_summarize": True,
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
    monkeypatch.setattr("src.app.main_window.ensure_dirs", lambda _config=None: None)
    monkeypatch.setattr("src.app.main_window.AudioRecorder", lambda output_dir: None)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    app.processEvents()
    return window


def test_sidebar_actions_replace_extra_recording_entry(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.is_recording = True
        window._sync_sidebar_actions()

        assert window.active_recording_button.isHidden()
        assert window.new_recording_sidebar_button.text() == "正在录音中"
        assert window.new_recording_sidebar_button.isEnabled()
        assert window.new_recording_sidebar_button.objectName() == "SidebarRecordingTaskButton"
        assert not window.import_audio_sidebar_button.isEnabled()

        window.is_recording = False
        window.is_processing = True
        window.processing_source = "import"
        window._sync_sidebar_actions()

        assert window.new_recording_sidebar_button.text() == "创建新录音"
        assert not window.new_recording_sidebar_button.isEnabled()
        assert window.import_audio_sidebar_button.text() == "导入本地音视频"
        assert not window.import_audio_sidebar_button.isEnabled()
        assert window.active_recording_button.text() == "正在转录音频"
        assert window.active_recording_button.isEnabled()
        assert not window.active_recording_button.isHidden()
        assert window.active_recording_button.objectName() == "SidebarProcessingTaskButton"

        window.is_processing = False
        window.processing_source = None
        window._sync_sidebar_actions()

        assert window.new_recording_sidebar_button.text() == "创建新录音"
        assert window.import_audio_sidebar_button.text() == "导入本地音视频"
        assert window.new_recording_sidebar_button.isEnabled()
        assert window.import_audio_sidebar_button.isEnabled()
        assert window.active_recording_button.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_recording_task_button_returns_to_recording_page(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.content_stack.setCurrentWidget(window.history_page)
        window.is_recording = True

        window.new_recording()

        assert window.content_stack.currentWidget() == window.recording_page
    finally:
        window.close()
        app.processEvents()


def test_processing_task_button_returns_to_processing_record_silently(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "imported" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window.current_items = [record]
        window.processing_record = record
        window.is_processing = True
        window.processing_source = "import"
        window._sync_sidebar_actions()
        window.content_stack.setCurrentWidget(window.recording_page)
        window._set_status("原状态")

        window.active_recording_button.click()

        assert window.current_record.record_id == record.record_id
        assert window.content_stack.currentWidget() == window.history_page
        assert window.status_label.text() == ""
    finally:
        window.close()
        app.processEvents()


def test_detail_progress_follows_selected_processing_record(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "a" / "audio.wav")
        write_wav(tmp_path / "records" / "b" / "audio.wav")
        records = {record.record_id: record for record in service.scan()}
        window.history_service = service
        window.current_items = [records["a"], records["b"]]
        window.current_record = records["a"]
        window.processing_record = records["a"]
        window.is_processing = True
        window.processing_started_at["transcription"] = 1.0

        window._sync_detail_processing_view()
        assert not window.transcript_progress.isHidden()

        window._load_history_record(records["b"])
        assert window.transcript_progress.isHidden()

        window._load_history_record(records["a"])
        assert not window.transcript_progress.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_summary_progress_status_restores_after_switching_records(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "a" / "audio.wav")
        write_wav(tmp_path / "records" / "b" / "audio.wav")
        records = {record.record_id: record for record in service.scan()}
        service.save_transcript(records["a"], "转录内容")
        records = {record.record_id: record for record in service.scan()}
        window.history_service = service
        window.current_items = [records["a"], records["b"]]
        window.current_record = records["a"]
        window.processing_record = records["a"]
        window.is_processing = True
        window.processing_started_at["summary"] = 1.0
        window.latest_processing_messages["summary"] = "大模型总结中"

        window._load_history_record(records["b"])
        assert window.summary_progress.isHidden()

        window._load_history_record(records["a"])
        assert not window.summary_progress.isHidden()
        assert window.summary_status.text() == "大模型总结中"
        assert window.manual_summary_button.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_transcription_loading_progress_hides_specific_model_name(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window.current_record = record
        window.processing_record = record
        window.is_processing = True
        window.processing_started_at["transcription"] = 1.0

        window._on_transcription_progress("正在加载 Qwen3-ASR GGUF 模型")

        assert window.transcript_status.text() == "正在加载ASR模型"
        assert window.latest_processing_messages["transcription"] == "正在加载ASR模型"
    finally:
        window.close()
        app.processEvents()


def test_summary_progress_removes_ellipsis(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        service.save_transcript(record, "转录内容")
        record = service.scan()[0]
        window.history_service = service
        window.current_record = record
        window.processing_record = record
        window.is_processing = True
        window.processing_started_at["summary"] = 1.0

        window._on_summary_progress("正在调用 LLM 总结...")

        assert window.summary_status.text() == "正在调用 LLM 总结"
        assert window.latest_processing_messages["summary"] == "正在调用 LLM 总结"
    finally:
        window.close()
        app.processEvents()


def test_retry_transcription_cancel_keeps_generated_files(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        service.save_transcript(record, "旧转录")
        service.save_summary(record, "旧总结")
        service.save_markdown(record, "旧导出")
        record = service.scan()[0]
        window.history_service = service
        window.current_record = record
        started: list[Path] = []
        monkeypatch.setattr(
            "src.handlers.transcription.confirm_without_icon",
            lambda *args, **kwargs: False,
        )
        monkeypatch.setattr(window, "start_transcription", lambda audio_file, record=None, source="manual": started.append(audio_file))

        window.retry_transcription()

        assert started == []
        assert record.transcript_path.read_text(encoding="utf-8") == "旧转录"
        assert record.summary_path.read_text(encoding="utf-8") == "旧总结"
        assert record.markdown_path.read_text(encoding="utf-8") == "旧导出"
    finally:
        window.close()
        app.processEvents()


def test_retry_transcription_confirm_text_is_user_friendly(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        captured: dict[str, str] = {}

        def fake_confirm(parent, title, text, confirm_text="OK", cancel_text="取消"):
            captured["title"] = title
            captured["text"] = text
            captured["confirm_text"] = confirm_text
            captured["cancel_text"] = cancel_text
            return False

        monkeypatch.setattr("src.handlers.transcription.confirm_without_icon", fake_confirm)

        assert not window._confirm_retranscription(record)
        assert captured["title"] == "重新转录"
        assert captured["text"] == (
            "重新转录会覆盖当前音频的转录和总结。\n"
            "如需保留旧结果，请手动导出或复制。"
        )
        assert captured["confirm_text"] == "OK"
        assert captured["cancel_text"] == "取消"
    finally:
        window.close()
        app.processEvents()


def test_retry_transcription_confirmation_clears_generated_files(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        service.save_transcript(record, "旧转录")
        service.save_summary(record, "旧总结")
        service.save_markdown(record, "旧导出")
        record = service.scan()[0]
        window.history_service = service
        window.current_record = record
        window.current_items = [record]
        started: list[tuple[Path, str]] = []
        monkeypatch.setattr(
            "src.handlers.transcription.confirm_without_icon",
            lambda *args, **kwargs: True,
        )
        monkeypatch.setattr(
            window,
            "start_transcription",
            lambda audio_file, record=None, source="manual": started.append((audio_file, source)),
        )

        window.retry_transcription()

        assert started == [(record.audio_path, "manual")]
        assert not record.transcript_path.exists()
        assert not record.summary_path.exists()
        assert not record.markdown_path.exists()
    finally:
        window.close()
        app.processEvents()


def test_transcription_empty_result_becomes_no_valid_speech_error(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window.current_record = record
        window.processing_record = record
        window.is_processing = True
        window.processing_started_at["transcription"] = 1.0

        window._on_transcription_completed("")

        scanned = service.scan()[0]
        assert scanned.status == HistoryStatus.ERROR
        assert scanned.error_message == "未识别到有效语音内容"
        assert "未识别到有效语音内容" in window.transcript_status.text()
    finally:
        window.close()
        app.processEvents()





def test_delete_history_record_uses_unified_confirm_dialog(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window.current_record = record
        captured: dict[str, str] = {}

        def fake_confirm(parent, title, text, confirm_text="\u786e\u8ba4", cancel_text="\u53d6\u6d88"):
            captured["title"] = title
            captured["text"] = text
            captured["confirm_text"] = confirm_text
            captured["cancel_text"] = cancel_text
            return False

        monkeypatch.setattr("src.app.main_window.confirm_without_icon", fake_confirm)

        window.delete_current_record()

        assert captured == {
            "title": "\u5220\u9664\u5386\u53f2\u8bb0\u5f55",
            "text": "\u786e\u5b9a\u5220\u9664\u8fd9\u6761\u5386\u53f2\u8bb0\u5f55\u5417?\n\u97f3\u9891\u6587\u4ef6\u3001\u8f6c\u5f55\u7ed3\u679c\u7b49\u90fd\u4f1a\u88ab\u6e05\u7406\u3002",
            "confirm_text": "\u786e\u8ba4",
            "cancel_text": "\u53d6\u6d88",
        }
        assert record.record_dir.exists()
    finally:
        window.close()
        app.processEvents()


def test_result_tabs_keep_current_selection_when_switching_records(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "a" / "audio.wav")
        write_wav(tmp_path / "records" / "b" / "audio.wav")
        records = {record.record_id: record for record in service.scan()}
        service.save_transcript(records["a"], "转录 A")
        service.save_summary(records["a"], "# 总结 A\n\n- 要点")
        service.save_transcript(records["b"], "转录 B")
        records = {record.record_id: record for record in service.scan()}
        window.history_service = service

        window._load_history_record(records["a"])
        window.summary_tab_button.click()
        window._load_history_record(records["b"])

        assert window.active_result_tab == "summary"
        assert window.result_stack.currentIndex() == 1
        assert window.summary_tab_button.isChecked()
        assert not window.transcript_tab_button.isChecked()
    finally:
        window.close()
        app.processEvents()


def test_summary_page_renders_markdown_but_copies_source(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        markdown = "# 会议总结\n\n- 第一项\n- **第二项**"
        service.save_transcript(record, "转录内容")
        service.save_summary(record, markdown)
        record = service.scan()[0]
        window.history_service = service

        window._load_history_record(record)
        window.summary_tab_button.click()
        window.copy_panel_text("summary")

        assert window.summary_markdown_text == markdown
        assert "会议总结" in window.summary_text.toPlainText()
        assert not window.summary_text.toPlainText().lstrip().startswith("#")
        assert QApplication.clipboard().text() == markdown
    finally:
        window.close()
        app.processEvents()


def test_empty_result_copy_buttons_are_hidden(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service

        window._load_history_record(record)

        assert window.transcript_copy_button.isHidden()
        assert window.summary_copy_button.isHidden()
    finally:
        window.close()
        app.processEvents()
