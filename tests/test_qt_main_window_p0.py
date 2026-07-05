from __future__ import annotations

import copy
import os
import shutil
import wave
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest

from src.app.config import DEFAULT_MODEL_CATALOG, QWEN3_ASR_GGUF_06B_ID
from src.history.service import HistoryService, HistoryStatus
from src.history.types import format_size
from src.app.main_window import MainWindow
from src.ui.content import PlaybackRateCombo, SeekSlider


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
    monkeypatch.setattr("src.handlers.settings.save_config", lambda _config: None)
    monkeypatch.setattr("src.app.main_window.ensure_dirs", lambda _config=None: None)
    monkeypatch.setattr("src.app.main_window.AudioRecorder", lambda output_dir: None)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    app.processEvents()
    return window


def history_subtitle_at(window: MainWindow, row: int) -> str:
    item = history_record_item_at(window, row)
    return str(item.data(0, Qt.ItemDataRole.UserRole + 2) or "")


def history_record_item_at(window: MainWindow, row: int):
    current_row = 0
    for root_index in range(window.history_tree.topLevelItemCount()):
        root = window.history_tree.topLevelItem(root_index)
        for child_index in range(root.childCount()):
            if current_row == row:
                return root.child(child_index)
            current_row += 1
    raise IndexError(row)


def history_tree_record_count(window: MainWindow) -> int:
    total = 0
    for root_index in range(window.history_tree.topLevelItemCount()):
        total += window.history_tree.topLevelItem(root_index).childCount()
    return total


def test_resolve_demo_audio_path_uses_src_assets_in_development(monkeypatch) -> None:
    monkeypatch.delattr("sys._MEIPASS", raising=False)

    path = MainWindow._resolve_demo_audio_path(object())

    assert path == Path(__file__).resolve().parents[1] / "src" / "assets" / "测试音频.mp3"
    assert path.exists()


def test_demo_audio_import_preserves_duration_for_mp3(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    demo_audio = tmp_path / "assets" / "测试音频.mp3"
    demo_audio.parent.mkdir(parents=True)
    demo_audio.write_bytes(b"fake mp3 data")
    config = make_config(tmp_path)
    config["data_root"] = str(tmp_path / "data_root")
    config["demo_audio_imported"] = False
    monkeypatch.setattr("src.app.main_window.get_config", lambda: config)
    monkeypatch.setattr("src.app.main_window.save_config", lambda _config: None)
    monkeypatch.setattr("src.app.main_window.ensure_dirs", lambda _config=None: None)
    monkeypatch.setattr("src.app.main_window.AudioRecorder", lambda output_dir: None)
    monkeypatch.setattr("src.app.main_window.MainWindow._resolve_demo_audio_path", lambda self: demo_audio)
    monkeypatch.setattr(
        "src.app.main_window.probe_media",
        lambda path, config=None: SimpleNamespace(
            duration_seconds=49.0,
            audio_sample_rate=44100,
            audio_channels=2,
            source_format="mp3",
        ),
    )

    window = MainWindow()
    try:
        assert window.current_record is not None
        assert window.current_record.audio_path.name == "测试音频.mp3"
        assert window.current_record.duration_text == "00:49"
        assert window.detail_duration_label.text() == "00:49"
        assert config["demo_audio_imported"] is True
    finally:
        window.close()
        app.processEvents()


def test_demo_audio_flag_is_set_when_history_already_exists(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    data_root = tmp_path / "data_root"
    write_wav(data_root / "data" / "existing-record" / "audio.wav")
    config = make_config(tmp_path)
    config["data_root"] = str(data_root)
    config["demo_audio_imported"] = False
    save_calls: list[dict] = []
    monkeypatch.setattr("src.app.main_window.get_config", lambda: config)
    monkeypatch.setattr("src.app.main_window.save_config", lambda saved: save_calls.append(dict(saved)))
    monkeypatch.setattr("src.app.main_window.ensure_dirs", lambda _config=None: None)
    monkeypatch.setattr("src.app.main_window.AudioRecorder", lambda output_dir: None)
    monkeypatch.setattr(
        "src.app.main_window.MainWindow._resolve_demo_audio_path",
        lambda self: (_ for _ in ()).throw(AssertionError("已有历史记录时不应再解析测试音频")),
    )

    window = MainWindow()
    try:
        assert config["demo_audio_imported"] is True
        assert save_calls and save_calls[-1]["demo_audio_imported"] is True
        assert [record.record_id for record in window.all_history_items] == ["existing-record"]
    finally:
        window.close()
        app.processEvents()


def test_history_sidebar_keeps_import_actions_out_of_sidebar(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        assert not hasattr(window, "new_recording_sidebar_button")
        assert not hasattr(window, "import_audio_sidebar_button")
        assert not hasattr(window, "remote_import_sidebar_button")
        assert not hasattr(window, "settings_button")

        window.is_recording = True
        window._sync_sidebar_actions()

        assert not hasattr(window, "active_recording_button")
        assert window.record_toolbar_button.objectName() == "ToolbarRecordingButton"
        assert window.import_audio_toolbar_button.isEnabled()

        window.is_recording = False
        window.is_processing = True
        window.processing_source = "import"
        window._sync_sidebar_actions()

        assert window.record_toolbar_button.objectName() == "ToolbarIconButton"
        assert window.import_audio_toolbar_button.isEnabled()

        window.is_processing = False
        window.processing_source = None
        window._sync_sidebar_actions()

        assert window.record_toolbar_button.objectName() == "ToolbarIconButton"
        assert window.import_audio_toolbar_button.isEnabled()
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


def test_workbench_shell_has_menu_toolbar_and_task_panel(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        assert [action.text() for action in window.menuBar().actions()] == ["文件", "导出", "视图", "帮助"]
        assert not window.quick_toolbar.isHidden()
        assert window.record_toolbar_button.toolTip() == "录音"
        assert window.record_toolbar_button.text() == ""
        assert window.import_audio_toolbar_button.toolTip() == "导入音视频"
        assert window.remote_import_toolbar_button.toolTip() == "从链接导入"
        assert not window.task_panel.isHidden()
        assert window.workbench_splitter.widget(0) == window.sidebar_stack
        assert not hasattr(window, "new_recording_sidebar_button")
        assert not hasattr(window, "settings_button")
    finally:
        window.close()
        app.processEvents()


def test_history_sidebar_resizes_without_blank_child_region(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.history_tree.textElideMode() == Qt.TextElideMode.ElideRight
        assert window.history_tree.indentation() <= 10
        assert window.main_sidebar.maximumWidth() > window.sidebar_stack.maximumWidth()
        assert 520 <= window.sidebar_stack.maximumWidth() <= 680
    finally:
        window.close()
        app.processEvents()


def test_help_check_update_does_not_open_settings_dialog(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        calls: list[str] = []
        window.show_settings = lambda: (_ for _ in ()).throw(AssertionError("不应打开设置界面"))
        window.settings_panel._on_check_update_clicked = lambda: calls.append("checked")

        window._show_update_check()

        assert calls == ["checked"]
        assert window.settings_dialog is None
    finally:
        window.close()
        app.processEvents()


def test_general_settings_page_has_no_check_update_button(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        button_texts = {button.text() for button in window.settings_panel.general_page.findChildren(QPushButton)}

        assert "检查更新" not in button_texts
    finally:
        window.close()
        app.processEvents()


def test_record_toolbar_button_opens_recording_dialog(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.record_toolbar_button.click()
        app.processEvents()

        assert window.recording_dialog.isVisible()
        assert window.recording_dialog.start_stop_button.text() == "开始录音"
    finally:
        window.close()
        app.processEvents()


def test_view_menu_toggles_workbench_regions(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.toggle_quick_toolbar_action.trigger()
        window.toggle_history_panel_action.trigger()
        window.toggle_playback_panel_action.trigger()
        window.toggle_task_panel_action.trigger()

        assert window.quick_toolbar.isHidden()
        assert window.sidebar_stack.isHidden()
        assert window.playback_widget.isHidden()
        assert window.task_panel.isHidden()

        window.toggle_quick_toolbar_action.trigger()
        window.toggle_history_panel_action.trigger()
        window.toggle_playback_panel_action.trigger()
        window.toggle_task_panel_action.trigger()

        assert not window.quick_toolbar.isHidden()
        assert not window.sidebar_stack.isHidden()
        assert not window.playback_widget.isHidden()
        assert not window.task_panel.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_history_search_filters_visible_records(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "alpha-meeting" / "audio.wav")
        write_wav(tmp_path / "records" / "beta-note" / "audio.wav")
        window.history_service = service

        window.load_recordings()
        window.history_search.setText("alpha")
        app.processEvents()

        assert [record.record_id for record in window.current_items] == ["alpha-meeting"]
        assert history_tree_record_count(window) == 1
    finally:
        window.close()
        app.processEvents()


def test_history_tree_groups_records_by_notebook(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    default_dir = tmp_path / "default"
    work_dir = tmp_path / "work"
    try:
        write_wav(default_dir / "daily" / "audio.wav")
        write_wav(work_dir / "meeting" / "audio.wav")
        window.config["notebooks"] = [
            {"id": "default", "name": "默认笔记本", "path": str(default_dir), "is_default": True},
            {"id": "work", "name": "工作", "path": str(work_dir), "is_default": False},
        ]
        window.history_service = HistoryService.from_notebooks(window.config["notebooks"])

        window.load_recordings()

        assert window.history_tree.topLevelItemCount() == 2
        assert window.history_tree.topLevelItem(0).text(0) == "默认笔记本"
        assert window.history_tree.topLevelItem(0).child(0).text(0) == "daily"
        assert window.history_tree.topLevelItem(1).text(0) == "工作"
        assert window.history_tree.topLevelItem(1).child(0).text(0) == "meeting"
    finally:
        window.close()
        app.processEvents()


def test_history_tree_selects_duplicate_record_id_by_record_key(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    default_dir = tmp_path / "default"
    work_dir = tmp_path / "work"
    try:
        write_wav(default_dir / "meeting" / "audio.wav")
        write_wav(work_dir / "meeting" / "audio.wav")
        window.config["notebooks"] = [
            {"id": "default", "name": "默认笔记本", "path": str(default_dir), "is_default": True},
            {"id": "work", "name": "工作", "path": str(work_dir), "is_default": False},
        ]
        window.history_service = HistoryService.from_notebooks(window.config["notebooks"])
        window.load_recordings()

        window.history_tree.record_selected.emit("work:meeting")

        assert window.current_record is not None
        assert window.current_record.record_key == "work:meeting"
    finally:
        window.close()
        app.processEvents()


def test_settings_dialog_save_refreshes_history_after_external_delete(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        record_dir = tmp_path / "records" / "external-delete"
        write_wav(record_dir / "audio.wav")
        window.config["data_root"] = str(tmp_path / "root")
        window.config["notebooks"] = [
            {"id": "default", "name": "默认笔记本", "path": str(tmp_path / "records"), "is_default": True}
        ]
        window.history_service = HistoryService.from_notebooks(window.config["notebooks"])
        window.load_recordings()
        window.select_history_index(0)

        window.show_settings()
        shutil.rmtree(record_dir)
        window._apply_settings_config(window.config)
        app.processEvents()

        assert window.current_record is None
        assert history_tree_record_count(window) == 0
        assert not window.settings_dialog or not window.settings_dialog.isVisible()
    finally:
        window.close()
        app.processEvents()


def test_escape_key_closes_settings_dialog(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.show_settings()
        app.processEvents()
        assert window.settings_dialog.isVisible()

        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        window.settings_dialog.keyPressEvent(event)
        app.processEvents()

        assert event.isAccepted()
        assert not window.settings_dialog or not window.settings_dialog.isVisible()
    finally:
        window.close()
        app.processEvents()


def test_settings_notebook_page_adds_selected_directory(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    selected_dir = tmp_path / "work-notebook"
    try:
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(selected_dir))
        window.show_settings()
        window.show_settings_section("notebooks")

        window.settings_panel.add_notebook_button.click()
        updated = window.settings_panel.updated_config()

        assert any(item["path"] == str(selected_dir) for item in updated["notebooks"])
        assert window.settings_panel.settings_stack.currentWidget() == window.settings_panel.notebooks_page
    finally:
        window.close()
        app.processEvents()


def test_persist_settings_config_rebuilds_history_service_from_notebooks(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    work_dir = tmp_path / "work"
    write_wav(work_dir / "meeting" / "audio.wav")
    try:
        updated = dict(window.config)
        updated["data_root"] = str(tmp_path / "root")
        updated["active_notebook_id"] = "work"
        updated["notebooks"] = [
            {"id": "default", "name": "默认笔记本", "path": str(tmp_path / "root" / "data"), "is_default": True},
            {"id": "work", "name": "工作", "path": str(work_dir), "is_default": False},
        ]

        window._persist_settings_config(updated)
        records = window.history_service.scan()

        assert len(records) == 1
        assert records[0].notebook_id == "work"
        assert records[0].record_id == "meeting"
    finally:
        window.close()
        app.processEvents()


def test_history_status_filter_limits_visible_records(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "audio-only" / "audio.wav")
        write_wav(tmp_path / "records" / "done" / "audio.wav")
        records = {record.record_id: record for record in service.scan()}
        service.save_transcript(records["done"], "转录")
        window.history_service = service

        window.load_recordings()
        window._set_history_filter(HistoryStatus.TRANSCRIBED.value, "已转录")

        assert [record.record_id for record in window.current_items] == ["done"]
        assert window.history_filter_button.text() == ""
        assert window.history_filter_button.toolTip() == "筛选：已转录"

        window._set_history_filter("all", "全部")
        assert len(window.current_items) == 2
    finally:
        window.close()
        app.processEvents()


def test_detail_header_populates_record_metadata(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service

        window._load_history_record(record)

        assert window.detail_title_label.text() == "meeting"
        assert window.detail_duration_label.text() == record.duration_text
        assert window.detail_size_label.text() == format_size(record.total_size_bytes)
        assert window.detail_status_label.text() == record.status_text
        assert window.detail_time_label.text() == record.created_at.strftime("%Y-%m-%d %H:%M")
        assert not hasattr(window, "export_button")
        assert window.windowTitle() == "meeting - NoisNote"
    finally:
        window.close()
        app.processEvents()


def test_export_txt_without_transcript_warns_before_choosing_directory(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "audio-only" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window.current_record = record
        messages: list[str] = []
        monkeypatch.setattr(
            "src.app.main_window.alert_without_icon",
            lambda parent, title, text, confirm_text="确认": messages.append(text),
        )
        monkeypatch.setattr(
            "src.handlers.export.QFileDialog.getExistingDirectory",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应打开目录选择器")),
        )

        window._export_result_with_format("txt")

        assert messages == ["当前记录没有可导出的转录文字"]
        assert window.status_label.text() == "当前记录没有可导出的转录文字"
    finally:
        window.close()
        app.processEvents()


def test_export_markdown_without_summary_warns_before_choosing_directory(monkeypatch, tmp_path: Path) -> None:
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
        messages: list[str] = []
        monkeypatch.setattr(
            "src.app.main_window.alert_without_icon",
            lambda parent, title, text, confirm_text="确认": messages.append(text),
        )
        monkeypatch.setattr(
            "src.handlers.export.QFileDialog.getExistingDirectory",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应打开目录选择器")),
        )

        window._export_result_with_format("markdown")

        assert messages == ["当前记录没有可导出的总结内容"]
        assert window.status_label.text() == "当前记录没有可导出的总结内容"
    finally:
        window.close()
        app.processEvents()


def test_processing_notice_clicks_to_record_and_then_hides(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "imported" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window.load_recordings()
        record = window.current_items[0]
        window.history_record_notices[record.record_key] = "处理完成，点击查看详情"
        window._render_history_list()

        assert history_subtitle_at(window, 0) == "处理完成，点击查看详情"

        window.select_history_index(0)

        assert window.current_record.record_id == record.record_id
        assert window.content_stack.currentWidget() == window.history_page
        assert history_subtitle_at(window, 0) == ""
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
        assert not window.detail_processing_status_label.isHidden()

        window._load_history_record(records["b"])
        assert window.detail_processing_status_label.isHidden()

        window._load_history_record(records["a"])
        assert not window.detail_processing_status_label.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_summary_processing_status_restores_after_switching_records(monkeypatch, tmp_path: Path) -> None:
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

        window._load_history_record(records["b"])
        assert window.detail_processing_status_label.isHidden()

        window._load_history_record(records["a"])
        assert not window.detail_processing_status_label.isHidden()
        assert "正在总结" in window.detail_processing_status_label.text()
        assert window.manual_summary_button.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_transcription_text_progress_keeps_generic_processing_status(monkeypatch, tmp_path: Path) -> None:
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

        assert "正在转录: 0%" in window.detail_processing_status_label.text()
    finally:
        window.close()
        app.processEvents()


def test_summary_processing_status_uses_static_detail_text(monkeypatch, tmp_path: Path) -> None:
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

        window._sync_detail_processing_view()

        assert "正在总结" in window.detail_processing_status_label.text()
    finally:
        window.close()
        app.processEvents()


def test_unselected_summary_failure_does_not_update_current_detail(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "a" / "audio.wav")
        write_wav(tmp_path / "records" / "b" / "audio.wav")
        records = {record.record_id: record for record in service.scan()}
        service.save_transcript(records["a"], "A 转录")
        service.save_transcript(records["b"], "B 转录")
        records = {record.record_id: record for record in service.scan()}
        window.history_service = service
        window.load_recordings()
        window._select_record_by_id("b")
        window.processing_record = records["a"]
        window.is_processing = True
        window.processing_started_at["summary"] = 1.0
        window.summary_status.setText("B 详情状态")
        window.manual_summary_button.setVisible(True)
        monkeypatch.setattr(window, "_show_error", lambda *_args, **_kwargs: None)

        window._on_summary_failed("API timeout")

        assert window.current_record.record_id == "b"
        assert window.summary_status.text() == "B 详情状态"
        assert not window.manual_summary_button.isHidden()
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
        assert captured["confirm_text"] == "确认"
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


def test_menu_rename_non_current_record_keeps_current_selection(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "selected" / "audio.wav")
        write_wav(tmp_path / "records" / "target" / "audio.wav")
        window.history_service = service
        window.load_recordings()
        assert window._select_record_by_id("selected")
        selected_id = window.current_record.record_id
        target_index = next(index for index, record in enumerate(window.current_items) if record.record_id == "target")
        monkeypatch.setattr(
            "src.app.main_window.prompt_text_without_icon",
            lambda *_args, **_kwargs: ("renamed-target", True),
        )

        window.rename_history_record(target_index)

        assert window.current_record.record_id == selected_id
        assert (tmp_path / "records" / "renamed-target").exists()
        assert not (tmp_path / "records" / "target").exists()
        assert window.history_tree.currentItem().data(0, Qt.ItemDataRole.UserRole + 1) == window.current_record.record_key
    finally:
        window.close()
        app.processEvents()


def test_menu_delete_non_current_record_keeps_current_selection(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "selected" / "audio.wav")
        write_wav(tmp_path / "records" / "target" / "audio.wav")
        window.history_service = service
        window.load_recordings()
        assert window._select_record_by_id("selected")
        selected_id = window.current_record.record_id
        target_index = next(index for index, record in enumerate(window.current_items) if record.record_id == "target")
        monkeypatch.setattr("src.app.main_window.confirm_without_icon", lambda *_args, **_kwargs: True)

        window.delete_history_record(target_index)

        assert window.current_record.record_id == selected_id
        assert (tmp_path / "records" / "selected").exists()
        assert not (tmp_path / "records" / "target").exists()
        assert [record.record_id for record in window.current_items] == ["selected"]
        assert window.history_tree.currentItem().data(0, Qt.ItemDataRole.UserRole + 1) == window.current_record.record_key
        assert window.content_stack.currentWidget() == window.history_page
    finally:
        window.close()
        app.processEvents()


def test_result_tabs_reset_to_transcript_when_switching_records(monkeypatch, tmp_path: Path) -> None:
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

        assert window.active_result_tab == "transcript"
        assert window.result_stack.currentIndex() == 0
        assert window.transcript_tab_button.isChecked()
        assert not window.summary_tab_button.isChecked()
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


def test_timeline_token_highlight_preserves_manual_scroll_within_same_sentence(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        items = [
            {
                "start": float(index),
                "end": float(index) + 0.9,
                "text": f"sentence {index}",
                "tokens": [
                    {"start": float(index), "end": float(index) + 0.4, "text": "a"},
                    {"start": float(index) + 0.4, "end": float(index) + 0.9, "text": "b"},
                ],
            }
            for index in range(40)
        ]
        window.resize(800, 420)
        window.show()
        window.content_stack.setCurrentWidget(window.history_page)
        window._set_result_tab("timeline")
        window._set_timeline_items(items)
        window.timeline_text.setFixedHeight(120)
        app.processEvents()

        window._refresh_timeline_highlight(10.1)
        app.processEvents()
        scroll_bar = window.timeline_text.verticalScrollBar()
        assert scroll_bar.maximum() > 0

        manual_scroll = min(scroll_bar.maximum(), max(1, scroll_bar.maximum() // 2))
        scroll_bar.setValue(manual_scroll)
        app.processEvents()

        window._refresh_timeline_highlight(10.6)
        app.processEvents()

        assert scroll_bar.value() == manual_scroll
    finally:
        window.close()
        app.processEvents()


def test_timeline_resources_are_released_when_leaving_timeline_tab(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        items = [{"start": 0.0, "end": 1.0, "text": "hello"}]
        window._set_result_tab("timeline")
        window._set_timeline_items(items)

        assert window.timeline_items
        assert "hello" in window.timeline_text.toPlainText()

        window._set_result_tab("transcript")

        assert window.timeline_items == []
        assert window.timeline_loaded_record_id == ""
        assert window.timeline_text.toPlainText() == ""
        assert window.timeline_copy_button.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_hidden_timeline_is_not_refreshed_by_playback_stop(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        def fail_timeline_render(*_args, **_kwargs) -> str:
            raise AssertionError("hidden timeline should not render")

        monkeypatch.setattr("src.handlers.timeline_view.timeline_to_html", fail_timeline_render)
        window.active_result_tab = "transcript"
        window.timeline_items = [{"start": 0.0, "end": 1.0, "text": "hidden"}]
        window.media_player = FakeMediaPlayer()

        window.stop_playback()
    finally:
        window.close()
        app.processEvents()


class FakeMediaPlayer:
    def __init__(self) -> None:
        self._position = 30_000
        self._duration = 90_000
        self._state = QMediaPlayer.PlaybackState.StoppedState
        self.rate = 1.0
        self.source = None
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True
        self._position = 0
        self._state = QMediaPlayer.PlaybackState.StoppedState

    def setSource(self, source) -> None:
        self.source = source

    def setPlaybackRate(self, rate: float) -> None:
        self.rate = rate

    def playbackState(self):
        return self._state

    def play(self) -> None:
        self._state = QMediaPlayer.PlaybackState.PlayingState

    def pause(self) -> None:
        self._state = QMediaPlayer.PlaybackState.PausedState

    def duration(self) -> int:
        return self._duration

    def position(self) -> int:
        return self._position

    def setPosition(self, position: int) -> None:
        self._position = position


def test_playback_controls_seek_rate_and_toggle_with_fake_player(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        fake = FakeMediaPlayer()
        window.media_player = fake
        window.history_service = service

        window._load_history_record(record)
        assert fake.source is None or fake.source.isEmpty()

        window.seek_playback_forward()
        assert fake.position() == 15_000

        window.seek_playback_backward()
        assert fake.position() == 0

        window.set_playback_rate("1.5x")
        assert fake.rate == 1.5

        window.toggle_playback()
        assert fake.source is not None
        assert fake.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        window.toggle_playback()
        assert fake.playbackState() == QMediaPlayer.PlaybackState.PausedState

        window.stop_playback()
        assert fake.source.isEmpty()
    finally:
        window.close()
        app.processEvents()


def test_processing_record_switch_keeps_playback_available_without_preloading_source(
    monkeypatch, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting-a" / "audio.wav")
        write_wav(tmp_path / "records" / "meeting-b" / "audio.wav")
        records = service.scan()
        fake = FakeMediaPlayer()
        window.media_player = fake
        window.history_service = service
        window.is_processing = True
        window.processing_record = records[0]

        window._load_history_record(records[0])
        window._load_history_record(records[1])
        window._load_history_record(records[0])

        assert fake.source is None or fake.source.isEmpty()
        assert window.playback_play_button.isEnabled()
        window.toggle_playback()
        assert fake.source is not None
        assert not fake.source.isEmpty()
        assert fake.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    finally:
        window.close()
        app.processEvents()


def test_new_recording_stops_playback_and_clears_playback_record(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        fake = FakeMediaPlayer()
        window.media_player = fake
        window.history_service = service
        window._load_history_record(record)
        fake.stopped = False

        window.new_recording()

        assert fake.stopped is True
        assert window.playback_record_id == ""
        assert window.current_record is None
        assert window.content_stack.currentWidget() == window.recording_page
    finally:
        window.close()
        app.processEvents()


def test_playback_rate_control_is_left_of_cc_button(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        transport_layout = window.playback_back_button.parentWidget().layout()
        layout = window.playback_rate_combo.parentWidget().layout()

        assert transport_layout.spacing() == 6
        assert layout.indexOf(window.playback_rate_combo) < layout.indexOf(window.playback_cc_button)
        assert layout.spacing() == 6
    finally:
        window.close()
        app.processEvents()


def test_playback_rate_combo_uses_positioned_menu() -> None:
    app = QApplication.instance() or QApplication([])
    combo = PlaybackRateCombo()
    try:
        for value in ("0.5x", "1x", "1.5x", "2x"):
            combo.addItem(value)
        combo.setCurrentText("1x")
        combo.resize(38, 28)
        combo.show()
        app.processEvents()

        combo.showPopup()
        app.processEvents()

        menu = combo._rate_menu
        assert menu is not None
        assert menu.objectName() == "PlayerRateMenu"
        assert menu.width() >= combo.popup_width

        menu.actions()[2].trigger()
        assert combo.currentText() == "1.5x"
    finally:
        menu = getattr(combo, "_rate_menu", None)
        if menu is not None:
            menu.close()
        combo.close()
        app.processEvents()


def test_playback_cc_button_stays_visible_without_timeline(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service

        window._load_history_record(record)
        window._set_result_tab("transcript")
        window.playback_cc_button.click()

        assert not window.playback_cc_button.isHidden()
        assert window.active_result_tab == "transcript"
    finally:
        window.close()
        app.processEvents()


def test_playback_keyboard_shortcuts_control_selected_record(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        fake = FakeMediaPlayer()
        window.media_player = fake
        window.history_service = service
        window._load_history_record(record)
        window.show()
        window.activateWindow()
        window.setFocus(Qt.FocusReason.OtherFocusReason)
        app.processEvents()

        QTest.keyClick(window, Qt.Key.Key_Space)
        assert fake.playbackState() == QMediaPlayer.PlaybackState.PlayingState

        QTest.keyClick(window, Qt.Key.Key_Right)
        assert fake.position() == 15_000

        QTest.keyClick(window, Qt.Key.Key_Left)
        assert fake.position() == 0
    finally:
        window.close()
        app.processEvents()


def test_seek_slider_click_jumps_to_clicked_position() -> None:
    app = QApplication.instance() or QApplication([])
    slider = SeekSlider(Qt.Orientation.Horizontal)
    moved: list[int] = []
    slider.setRange(0, 1000)
    slider.resize(200, 20)
    slider.sliderMoved.connect(moved.append)
    slider.show()
    app.processEvents()

    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, 10))
    app.processEvents()

    assert moved
    assert 450 <= moved[-1] <= 550
