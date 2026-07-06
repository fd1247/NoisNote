from __future__ import annotations

import copy
import os
import shutil
import wave
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QAbstractItemView, QComboBox, QFileDialog, QPushButton, QSizePolicy
from PySide6.QtWidgets import QDialog
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest

from src.app.config import DEFAULT_MODEL_CATALOG, QWEN3_ASR_GGUF_06B_ID
from src.history.service import HistoryService, HistoryStatus
from src.history.types import format_size
from src.app.main_window import MainWindow
from src.ui.content import PlaybackRateCombo, SeekSlider
from src.ui.detail_models import build_metadata_fields


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
    return make_window_with_config(monkeypatch, config)


def make_window_with_config(monkeypatch, config: dict) -> MainWindow:
    monkeypatch.setattr("src.app.main_window.get_config", lambda: config)
    monkeypatch.setattr("src.app.main_window.save_config", lambda _config: None)
    monkeypatch.setattr("src.handlers.history_view.save_config", lambda _config: None)
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
    if row < window.history_tree.topLevelItemCount():
        return window.history_tree.topLevelItem(row)
    raise IndexError(row)


def history_tree_record_count(window: MainWindow) -> int:
    return window.history_tree.topLevelItemCount()


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


def test_recording_task_button_opens_dialog_without_switching_main_page(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.content_stack.setCurrentWidget(window.history_page)
        window.is_recording = True

        window.new_recording()

        assert window.content_stack.currentWidget() == window.history_page
        assert window.recording_dialog.isVisible()
    finally:
        window.close()
        app.processEvents()


def test_main_workbench_starts_on_history_detail(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.content_stack.currentWidget() == window.history_page
        assert not window.recording_page.isVisible()
        assert window.recording_page.parent() is None
        assert not window.capture_mode_combo.isVisible()
        assert window.settings_panel.parent() is None
        assert not window.settings_panel.isVisible()
    finally:
        window.close()
        app.processEvents()


def test_workbench_shell_has_menu_toolbar_and_task_panel(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.menuBar().objectName() == "WorkbenchMenuBar"
        assert [action.text() for action in window.menuBar().actions()] == ["文件", "笔记本", "导出", "视图", "帮助"]
        assert not window.quick_toolbar.isHidden()
        assert window.record_toolbar_button.toolTip() == "录音"
        assert window.record_toolbar_button.text() == ""
        assert window.import_audio_toolbar_button.toolTip() == "导入音视频"
        assert window.remote_import_toolbar_button.toolTip() == "从链接导入"
        assert not window.task_panel.isHidden()
        assert window.workbench_splitter.widget(0) == window.sidebar_stack
        assert not hasattr(window, "new_recording_sidebar_button")
        assert not hasattr(window, "settings_button")
        assert "enterEvent" not in window.record_toolbar_button.__dict__
        assert "leaveEvent" not in window.record_toolbar_button.__dict__
    finally:
        window.close()
        app.processEvents()


def test_detail_header_has_action_menu_and_metadata_button(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.detail_more_button.toolTip() == "记录操作"
        assert window.detail_metadata_button.text() == "详细信息"
        assert [action.text() for action in window.detail_action_menu.actions()] == [
            "转录",
            "生成总结",
            "打开文件位置",
            "删除记录",
        ]
    finally:
        window.close()
        app.processEvents()


def test_detail_action_menu_enable_rules(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service

        window._load_history_record(record)

        assert window.detail_transcribe_action.isEnabled()
        assert not window.detail_summary_action.isEnabled()
        assert window.detail_open_folder_action.isEnabled()
        assert window.detail_delete_action.isEnabled()
        assert window.detail_metadata_button.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_detail_action_menu_transcribe_disabled_for_missing_audio(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service

        window._load_history_record(record)
        record.audio_path.unlink()
        window._sync_detail_action_menu()

        assert not window.detail_transcribe_action.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_detail_action_menu_transcribe_disabled_while_processing(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service

        window._load_history_record(record)
        window.is_processing = True
        window._sync_detail_action_menu()

        assert not window.detail_transcribe_action.isEnabled()

        window.is_processing = False
        window._sync_detail_action_menu()

        assert window.detail_transcribe_action.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_detail_more_button_disabled_without_current_record(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.current_record = None
        window._sync_detail_action_menu()

        assert not window.detail_more_button.isEnabled()

        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service

        window._load_history_record(record)

        assert window.detail_more_button.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_detail_action_menu_summary_enabled_for_transcript_without_summary(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        service.save_transcript(record, "会议转录内容")
        record = service.scan()[0]
        window.history_service = service

        window._load_history_record(record)

        assert window.detail_summary_action.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_show_metadata_details_uses_current_record_fields(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    class FakeMetadataDialog:
        def __init__(self, parent, fields):
            captured["parent"] = parent
            captured["fields"] = fields

        def exec(self):
            captured["exec_called"] = True
            return QDialog.DialogCode.Accepted

    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window._load_history_record(record)
        monkeypatch.setattr("src.app.main_window.DetailMetadataDialog", FakeMetadataDialog)

        window.show_metadata_details()

        expected_labels = [field["label"] for field in build_metadata_fields(window.current_record)]
        actual_labels = [field["label"] for field in captured["fields"]]
        assert captured["parent"] == window
        assert captured["exec_called"] is True
        assert actual_labels == expected_labels
    finally:
        window.close()
        app.processEvents()


def test_history_sidebar_resizes_without_blank_child_region(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.notebook_selector.objectName() == "NotebookSelector"
        assert window.notebook_selector.currentText() == "默认笔记本"
        assert window.notebook_selector.sizeAdjustPolicy() == QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        assert window.notebook_selector.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
        assert window.history_tree.textElideMode() == Qt.TextElideMode.ElideRight
        assert window.history_tree.indentation() == 16
        assert window.history_tree.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
        assert window.history_tree.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
        assert window.history_tree.dragDropMode() == QAbstractItemView.DragDropMode.NoDragDrop
        assert not window.history_tree.dragDropOverwriteMode()
        assert not hasattr(window, "history_search")
        assert not hasattr(window, "history_filter_button")
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


def test_recording_dialog_reopens_with_recording_page_visible(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.show_recording_dialog()
        app.processEvents()

        assert window.recording_dialog.isVisible()
        assert window.recording_page.isVisible()
        assert window.capture_mode_combo.isVisible()

        window.recording_dialog.hide()
        app.processEvents()
        assert window.recording_page.isHidden()

        window.show_recording_dialog()
        app.processEvents()

        assert window.recording_dialog.isVisible()
        assert window.recording_page.isVisible()
        assert window.capture_mode_combo.isVisible()
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


def test_playback_panel_visibility_toggles_separator_with_player(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.show()
        app.processEvents()

        assert hasattr(window, "playback_separator")
        assert window.playback_widget.isVisible()
        assert window.playback_separator.isVisible()

        window._set_playback_panel_visible(False)
        app.processEvents()

        assert window.playback_widget.isHidden()
        assert window.playback_separator.isHidden()

        window._set_playback_panel_visible(True)
        app.processEvents()

        assert window.playback_widget.isVisible()
        assert window.playback_separator.isVisible()
    finally:
        window.close()
        app.processEvents()


def test_notebook_selector_filters_visible_records(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    default_dir = tmp_path / "data"
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

        assert [window.notebook_selector.itemText(index) for index in range(window.notebook_selector.count())] == [
            "默认笔记本",
            "工作",
        ]
        assert [record.record_id for record in window.current_items] == ["daily"]
        assert history_tree_record_count(window) == 1
        assert history_record_item_at(window, 0).text(0) == "daily"
        assert history_record_item_at(window, 0).toolTip(0) == "daily"
        window.select_history_index(0)
        assert history_record_item_at(window, 0).toolTip(0) == "daily"
        window.history_tree.update_subtitles(window._history_subtitle_for_record)
        assert history_record_item_at(window, 0).toolTip(0) == "daily"
        assert window.current_record.record_id == "daily"
        assert window.config["last_selected_record_key"] == "default:daily"

        window.notebook_selector.setCurrentIndex(window.notebook_selector.findData("work"))
        app.processEvents()

        assert window.current_notebook_id == "work"
        assert window.history_service.active_notebook_id == "work"
        assert window.current_record is not None
        assert window.current_record.record_id == "meeting"
        assert [record.record_id for record in window.current_items] == ["meeting"]
        assert history_record_item_at(window, 0).text(0) == "meeting"
    finally:
        window.close()
        app.processEvents()


def test_load_recordings_selects_first_record_when_no_notebook_selection(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    records_dir = tmp_path / "records"
    try:
        write_wav(records_dir / "a" / "audio.wav")
        write_wav(records_dir / "b" / "audio.wav")
        window.history_service = HistoryService(records_dir)

        window.load_recordings()

        assert window.current_items
        assert window.current_record is not None
        assert window.current_record.record_key == window.current_items[0].record_key
        assert window.history_tree.currentItem().data(0, Qt.ItemDataRole.UserRole + 1) == window.current_record.record_key
    finally:
        window.close()
        app.processEvents()


def test_notebook_selector_restores_each_notebooks_selected_record(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    default_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    try:
        write_wav(default_dir / "a" / "audio.wav")
        write_wav(default_dir / "b" / "audio.wav")
        write_wav(work_dir / "x" / "audio.wav")
        write_wav(work_dir / "y" / "audio.wav")
        window.config["notebooks"] = [
            {"id": "default", "name": "Default", "path": str(default_dir), "is_default": True},
            {"id": "work", "name": "Work", "path": str(work_dir), "is_default": False},
        ]
        window.history_service = HistoryService.from_notebooks(window.config["notebooks"])
        window.load_recordings()
        assert window._select_record_by_key("default:b")

        window.notebook_selector.setCurrentIndex(window.notebook_selector.findData("work"))
        app.processEvents()

        assert window.current_record is not None
        assert window.current_record.record_key == "work:x"
        assert window._select_record_by_key("work:y")

        window.notebook_selector.setCurrentIndex(window.notebook_selector.findData("default"))
        app.processEvents()

        assert window.current_record is not None
        assert window.current_record.record_key == "default:b"

        window.notebook_selector.setCurrentIndex(window.notebook_selector.findData("work"))
        app.processEvents()

        assert window.current_record is not None
        assert window.current_record.record_key == "work:y"
        assert window.config["last_selected_record_keys"] == {
            "default": "default:b",
            "work": "work:y",
        }
    finally:
        window.close()
        app.processEvents()


def test_startup_restores_last_selected_record_and_notebook(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    default_dir = tmp_path / "default"
    work_dir = tmp_path / "work"
    write_wav(default_dir / "daily" / "audio.wav")
    write_wav(work_dir / "meeting" / "audio.wav")
    config = make_config(tmp_path)
    config["notebooks"] = [
        {"id": "default", "name": "默认笔记本", "path": str(default_dir), "is_default": True},
        {"id": "work", "name": "工作", "path": str(work_dir), "is_default": False},
    ]
    config["active_notebook_id"] = "default"
    config["last_selected_record_key"] = "work:meeting"
    window = make_window_with_config(monkeypatch, config)
    try:
        assert window.current_notebook_id == "work"
        assert window.notebook_selector.currentData() == "work"
        assert window.current_record is not None
        assert window.current_record.record_key == "work:meeting"
        assert [record.record_id for record in window.current_items] == ["meeting"]
        assert window.history_tree.currentItem().data(0, Qt.ItemDataRole.UserRole + 1) == "work:meeting"
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
        assert window.current_notebook_id == "work"
    finally:
        window.close()
        app.processEvents()


def test_move_record_keeps_current_notebook_selected(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    default_dir = tmp_path / "default"
    work_dir = tmp_path / "work"
    try:
        write_wav(default_dir / "daily" / "audio.wav")
        window.config["notebooks"] = [
            {"id": "default", "name": "默认笔记本", "path": str(default_dir), "is_default": True},
            {"id": "work", "name": "工作", "path": str(work_dir), "is_default": False},
        ]
        window.history_service = HistoryService.from_notebooks(window.config["notebooks"])
        window.load_recordings()
        window.select_history_index(0)

        window._move_records_to_notebook(["default:daily"], "work")

        assert window.current_notebook_id == "default"
        assert window.notebook_selector.currentData() == "default"
        assert window.current_record is None
        assert window.current_items == []
        assert history_tree_record_count(window) == 0
        assert (work_dir / "daily" / "audio.wav").exists()
    finally:
        window.close()
        app.processEvents()


def test_multi_select_records_and_move_to_notebook(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    default_dir = tmp_path / "default"
    work_dir = tmp_path / "work"
    try:
        write_wav(default_dir / "a" / "audio.wav")
        write_wav(default_dir / "b" / "audio.wav")
        write_wav(default_dir / "c" / "audio.wav")
        window.config["notebooks"] = [
            {"id": "default", "name": "默认笔记本", "path": str(default_dir), "is_default": True},
            {"id": "work", "name": "工作", "path": str(work_dir), "is_default": False},
        ]
        window.history_service = HistoryService.from_notebooks(window.config["notebooks"])
        window.load_recordings()

        history_record_item_at(window, 0).setSelected(True)
        history_record_item_at(window, 2).setSelected(True)
        expected_keys = [
            str(history_record_item_at(window, row).data(0, Qt.ItemDataRole.UserRole + 1))
            for row in (0, 2)
        ]
        window.history_tree.setCurrentItem(
            history_record_item_at(window, 2),
            0,
            QItemSelectionModel.SelectionFlag.NoUpdate,
        )

        assert window.history_tree.selected_record_keys() == expected_keys

        window.history_tree.record_selected.emit("default:c")

        assert window.current_record.record_id == "c"
        assert window.history_tree.selected_record_keys() == expected_keys

        window._move_records_to_notebook(window.history_tree.selected_record_keys(), "work")

        assert window.current_notebook_id == "default"
        assert [record.record_id for record in window.current_items] == ["b"]
        assert (work_dir / "a" / "audio.wav").exists()
        assert (work_dir / "c" / "audio.wav").exists()
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


def test_new_notebook_dialog_adds_and_switches_notebook(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    selected_dir = tmp_path / "work-notebook"
    try:
        class FakeDialog:
            DialogCode = QDialog.DialogCode

            def __init__(self, parent=None):
                pass

            def exec(self):
                return QDialog.DialogCode.Accepted

            def values(self):
                return "工作", selected_dir

        monkeypatch.setattr("src.handlers.history_view.NewNotebookDialog", FakeDialog)

        window.show_new_notebook_dialog()

        assert window.current_notebook_id.startswith("notebook-")
        assert window.notebook_selector.currentText() == "工作"
        assert any(item["name"] == "工作" and item["path"] == str(selected_dir) for item in window.config["notebooks"])
        assert selected_dir.exists()
        assert window.history_service.active_notebook_id == window.current_notebook_id
    finally:
        window.close()
        app.processEvents()


def test_manage_notebooks_dialog_omits_missing_notebook(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    existing_dir = tmp_path / "existing"
    missing_dir = tmp_path / "missing"
    existing_dir.mkdir()
    seen_ids: list[str] = []
    try:
        window.config["notebooks"] = [
            {"id": "default", "name": "Default", "path": str(tmp_path / "records"), "is_default": True},
            {"id": "missing", "name": "Missing", "path": str(missing_dir), "is_default": False},
            {"id": "existing", "name": "Existing", "path": str(existing_dir), "is_default": False},
        ]
        window.config["active_notebook_id"] = "missing"
        window.config["last_selected_record_key"] = "missing:old-record"

        class FakeDialog:
            DialogCode = QDialog.DialogCode

            def __init__(self, notebooks, parent=None):
                self._notebooks = [dict(item) for item in notebooks]
                seen_ids[:] = [str(item.get("id") or "") for item in self._notebooks]

            def exec(self):
                return QDialog.DialogCode.Accepted

            def notebooks(self):
                return [dict(item) for item in self._notebooks]

        monkeypatch.setattr("src.handlers.history_view.ManageNotebooksDialog", FakeDialog)

        window.show_manage_notebooks_dialog()

        assert seen_ids == ["default", "existing"]
        assert [item["id"] for item in window.config["notebooks"]] == ["default", "existing"]
        assert window.config["active_notebook_id"] == "default"
        assert window.config["last_selected_record_key"] == ""
        assert not missing_dir.exists()
    finally:
        window.close()
        app.processEvents()


def test_manage_notebooks_dialog_renames_notebook(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    try:
        window.config["notebooks"] = [
            {"id": "default", "name": "默认笔记本", "path": str(tmp_path / "records"), "is_default": True},
            {"id": "work", "name": "工作", "path": str(work_dir), "is_default": False},
        ]
        window.config["active_notebook_id"] = "work"
        window._set_current_notebook("work", persist=False)

        class FakeDialog:
            DialogCode = QDialog.DialogCode

            def __init__(self, notebooks, parent=None):
                self._notebooks = [dict(item) for item in notebooks]

            def exec(self):
                return QDialog.DialogCode.Accepted

            def notebooks(self):
                updated = [dict(item) for item in self._notebooks]
                for item in updated:
                    if item["id"] == "work":
                        item["name"] = "项目"
                return updated

        monkeypatch.setattr("src.handlers.history_view.ManageNotebooksDialog", FakeDialog)

        window.show_manage_notebooks_dialog()

        assert next(item for item in window.config["notebooks"] if item["id"] == "work")["name"] == "项目"
        assert window.notebook_selector.currentText() == "项目"
        assert window.current_notebook_id == "work"
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


def test_detail_header_elides_long_record_name(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    long_name = "very-long-record-name-" * 12
    try:
        window._set_detail_title(long_name)

        assert window.detail_title_label.toolTip() == long_name
        assert window.detail_title_label.text() != long_name
        assert len(window.detail_title_label.text()) < len(long_name)
        assert window.detail_title_label.maximumWidth() == 520
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
        write_wav(tmp_path / "records" / "selected" / "audio.wav")
        window.history_service = service
        window.load_recordings()
        assert window._select_record_by_id("selected")
        record = next(item for item in window.current_items if item.record_id == "imported")
        window.history_record_notices[record.record_key] = "处理完成，点击查看详情"
        window._render_history_list()

        notice_index = next(index for index, item in enumerate(window.current_items) if item.record_key == record.record_key)
        assert history_subtitle_at(window, notice_index) == "处理完成，点击查看详情"

        window.select_history_index(notice_index)

        assert window.current_record.record_id == record.record_id
        assert window.content_stack.currentWidget() == window.history_page
        assert history_subtitle_at(window, notice_index) == ""
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


def test_transcription_completion_syncs_generated_timeline_text(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window.current_record = record
        window.processing_record = record
        window.current_items = [record]
        window.is_processing = True
        window.processing_started_at["transcription"] = 1.0
        window.active_task_ids["transcription"] = "asr-test"
        started_summaries: list[tuple[str, str]] = []
        monkeypatch.setattr(
            window,
            "start_summarization",
            lambda text, record=None: started_summaries.append((text, record.record_key if record else "")),
        )
        timeline_items = [{"start": 1.25, "end": 3.5, "text": "Generated timeline sentence."}]

        window._on_transcription_completed("Generated transcript.", {"timeline": timeline_items})

        assert started_summaries == [("Generated transcript.", record.record_key)]
        assert window.timeline_items == timeline_items
        assert window.timeline_loaded_record_id == record.record_key
        timeline_text = window.timeline_text.toPlainText()
        assert "00:01.250 - 00:03.500" in timeline_text
        assert "Generated timeline sentence." in timeline_text
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


def test_settings_dialog_shows_embedded_panel(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.settings_panel.isHidden()

        window.show_settings()
        app.processEvents()

        assert window.settings_dialog is not None
        assert window.settings_dialog.isVisible()
        assert window.settings_panel.isVisible()
        assert window.settings_panel.parent() == window.settings_dialog
        assert window.settings_panel.settings_stack.currentWidget() == window.settings_panel.general_page
        assert window.settings_panel.asr_model.isVisible()

        window.hide_settings()
        app.processEvents()

        assert window.settings_panel.isHidden()
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


def test_context_delete_selected_records_deletes_batch_once(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "a" / "audio.wav")
        write_wav(tmp_path / "records" / "b" / "audio.wav")
        write_wav(tmp_path / "records" / "c" / "audio.wav")
        window.history_service = service
        window.load_recordings()
        assert window._select_record_by_id("b")
        calls: list[str] = []

        def fake_confirm(parent, title, text, confirm_text="确认", cancel_text="取消"):
            calls.append(text)
            return True

        monkeypatch.setattr("src.app.main_window.confirm_without_icon", fake_confirm)

        window._delete_records_by_keys(["default:a", "default:c"])

        assert len(calls) == 1
        assert "2 条历史记录" in calls[0]
        assert (tmp_path / "records" / "b").exists()
        assert not (tmp_path / "records" / "a").exists()
        assert not (tmp_path / "records" / "c").exists()
        assert window.current_record.record_id == "b"
        assert [record.record_id for record in window.current_items] == ["b"]
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


def test_detail_webview_exists_in_history_page(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.detail_webview is not None
        assert callable(window.detail_webview.set_content)
        assert window.detail_webview.current_payload["mode"] == "transcript"
    finally:
        window.close()
        app.processEvents()


def test_detail_webview_receives_transcript_payload_on_record_load(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        service.save_transcript(record, "transcript from disk")
        record = service.scan()[0]
        window.history_service = service

        window._load_history_record(record)

        payload = window.detail_webview.current_payload
        assert payload["recordKey"] == record.record_key
        assert payload["mode"] == "transcript"
        assert "transcript from disk" in payload["content"]
    finally:
        window.close()
        app.processEvents()


def test_detail_webview_receives_summary_payload_when_tab_selected(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        service.save_transcript(record, "transcript")
        service.save_summary(record, "# summary\n\n- item")
        record = service.scan()[0]
        window.history_service = service

        window._load_history_record(record)
        window._set_result_tab("summary")

        payload = window.detail_webview.current_payload
        assert payload["mode"] == "summary"
        assert "# summary" in payload["content"]
    finally:
        window.close()
        app.processEvents()


def test_detail_webview_receives_timeline_payload_when_tab_selected(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        service.save_timeline(record, [{"start": 1.0, "end": 2.0, "text": "timeline text"}])
        record = service.scan()[0]
        window.history_service = service

        window._load_history_record(record)
        window._set_result_tab("timeline")

        payload = window.detail_webview.current_payload
        assert payload["mode"] == "timeline"
        assert payload["timeline"][0]["text"] == "timeline text"
        assert "timeline text" in payload["content"]
    finally:
        window.close()
        app.processEvents()


def test_detail_seek_command_calls_playback_seek(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window._load_history_record(record)
        calls: list[int] = []
        window.seek_playback = calls.append

        window._on_detail_web_command(
            {
                "command": "seek",
                "recordKey": record.record_key,
                "revision": window.detail_revision,
                "seconds": 12.6,
            }
        )

        assert calls == [12600]
    finally:
        window.close()
        app.processEvents()


def test_detail_copy_command_updates_clipboard(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window._load_history_record(record)

        window._on_detail_web_command(
            {
                "command": "copy",
                "recordKey": record.record_key,
                "revision": window.detail_revision,
                "mode": "transcript",
                "text": "copy me",
            }
        )

        assert QApplication.clipboard().text() == "copy me"
        assert "copy" in window.status_label.text().lower() or "复制" in window.status_label.text()
    finally:
        window.close()
        app.processEvents()


def test_detail_open_external_url_command_uses_desktop_services(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    opened: list[str] = []
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window._load_history_record(record)
        monkeypatch.setattr(
            "src.handlers.detail_view.QDesktopServices.openUrl",
            lambda url: opened.append(url.toString()) or True,
        )

        window._on_detail_web_command(
            {
                "command": "openExternalUrl",
                "recordKey": record.record_key,
                "revision": window.detail_revision,
                "url": "https://example.com/video",
            }
        )

        assert opened == ["https://example.com/video"]
    finally:
        window.close()
        app.processEvents()


def test_stale_detail_command_is_ignored(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window._load_history_record(record)
        window.seek_playback = lambda _ms: (_ for _ in ()).throw(AssertionError("stale command should be ignored"))

        window._on_detail_web_command(
            {
                "command": "seek",
                "recordKey": record.record_key,
                "revision": window.detail_revision - 1,
                "seconds": 1,
            }
        )
        window._on_detail_web_command(
            {
                "command": "seek",
                "recordKey": "default:other",
                "revision": window.detail_revision,
                "seconds": 1,
            }
        )
    finally:
        window.close()
        app.processEvents()


def test_transcript_content_update_rejects_previous_detail_revision(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        window.history_service = service
        window._load_history_record(record)
        old_revision = window.detail_revision

        window._set_transcript_text("new transcript")

        payload = window.detail_webview.current_payload
        assert window.detail_revision > old_revision
        assert payload["revision"] == window.detail_revision
        assert payload["mode"] == "transcript"
        assert payload["content"] == "new transcript"

        QApplication.clipboard().clear()
        window._on_detail_web_command(
            {
                "command": "copy",
                "recordKey": record.record_key,
                "revision": old_revision,
                "mode": "transcript",
                "text": "stale transcript copy",
            }
        )

        assert QApplication.clipboard().text() == ""
    finally:
        window.close()
        app.processEvents()


def test_summary_content_update_rejects_previous_detail_revision(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    opened: list[str] = []
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        service.save_summary(record, "old summary")
        record = service.scan()[0]
        window.history_service = service
        window._load_history_record(record)
        window._set_result_tab("summary")
        old_revision = window.detail_revision
        monkeypatch.setattr(
            "src.handlers.detail_view.QDesktopServices.openUrl",
            lambda url: opened.append(url.toString()) or True,
        )

        window._set_summary_text("new summary")

        payload = window.detail_webview.current_payload
        assert window.detail_revision > old_revision
        assert payload["revision"] == window.detail_revision
        assert payload["mode"] == "summary"
        assert payload["content"] == "new summary"

        window._on_detail_web_command(
            {
                "command": "openExternalUrl",
                "recordKey": record.record_key,
                "revision": old_revision,
                "url": "https://example.com/stale",
            }
        )

        assert opened == []
    finally:
        window.close()
        app.processEvents()


def test_manual_summary_uses_cached_or_record_transcript(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    started: list[str] = []
    try:
        service = HistoryService(tmp_path / "records")
        write_wav(tmp_path / "records" / "meeting" / "audio.wav")
        record = service.scan()[0]
        service.save_transcript(record, "record transcript")
        record = service.scan()[0]
        window.history_service = service
        window._load_history_record(record)
        window.transcript_text.clear()
        window.transcript_plain_text = ""
        window.start_summarization = lambda text, _record=None: started.append(text)

        window.manual_summarize()

        assert started == ["record transcript"]
    finally:
        window.close()
        app.processEvents()


def test_detail_status_rows_are_hidden_from_body(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.show()
        app.processEvents()

        assert window.detail_webview.isVisible()
        assert not window.transcript_status.isVisible()
        assert not window.timeline_status.isVisible()
        assert not window.summary_status.isVisible()
    finally:
        window.close()
        app.processEvents()


def test_detail_styles_remove_borders_and_thin_splitter() -> None:
    from src.ui.styles import APP_STYLESHEET

    def style_block(selector: str) -> str:
        start = APP_STYLESHEET.index(f"{selector} {{")
        end = APP_STYLESHEET.index("}", start)
        return APP_STYLESHEET[start:end]

    panel_block = style_block("QFrame#Panel")
    player_bar_block = style_block("QFrame#PlayerBar")
    splitter_block = style_block("QSplitter#WorkbenchSplitter::handle")

    assert "border: none;" in panel_block
    assert "border-radius: 0;" in panel_block
    assert "border: none;" in player_bar_block
    assert "border-radius: 0;" in player_bar_block
    assert "width:" in splitter_block


def test_detail_tab_switch_updates_webview_mode(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window.summary_tab_button.click()
        app.processEvents()

        assert window.active_result_tab == "summary"
        assert window.detail_webview.current_payload["mode"] == "summary"

        window.timeline_tab_button.click()
        app.processEvents()

        assert window.active_result_tab == "timeline"
        assert window.detail_webview.current_payload["mode"] == "timeline"
    finally:
        window.close()
        app.processEvents()


def test_timeline_items_sync_to_visible_detail_webview(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        items = [{"start": 0.0, "end": 1.0, "text": "hello"}]

        window._set_result_tab("timeline")
        window._set_timeline_items(items)
        app.processEvents()

        assert window.detail_webview.current_payload["mode"] == "timeline"
        assert window.detail_webview.current_payload["timeline"][0]["text"] == "hello"
    finally:
        window.close()
        app.processEvents()


def test_playback_position_updates_visible_detail_webview(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        payloads = []

        def capture_playback(payload: dict) -> None:
            payloads.append(payload)

        window.detail_webview.update_playback = capture_playback
        window.media_player = FakeMediaPlayer()
        window.media_player.play()

        window._on_playback_position_changed(2500)

        assert payloads[-1]["positionSeconds"] == 2.5
        assert payloads[-1]["isPlaying"] is True
    finally:
        window.close()
        app.processEvents()


def test_detail_playback_bridge_uses_current_player_position(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        payloads = []
        window.detail_webview.update_playback = payloads.append
        window.media_player = FakeMediaPlayer()

        window._update_detail_playback()

        assert payloads[-1] == {"positionSeconds": 30.0, "isPlaying": False}
    finally:
        window.close()
        app.processEvents()


def test_detail_web_command_placeholder_does_not_change_status_or_state(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window(monkeypatch, tmp_path)
    try:
        window._set_status("keep existing status")
        window.is_processing = True
        window.processing_source = "sentinel"
        window.active_result_tab = "summary"

        window._on_detail_web_command({"command": "renderError", "message": "x"})

        assert window.status_label.text() == "keep existing status"
        assert window.is_processing is True
        assert window.processing_source == "sentinel"
        assert window.active_result_tab == "summary"
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
        def fail_timeline_render(*_args, **_kwargs) -> str:
            raise AssertionError("playback highlight should not render hidden HTML")

        monkeypatch.setattr("src.asr.timestamps.timeline_to_html", fail_timeline_render)
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
        window.detail_webview.hide()
        window.result_stack.show()
        window._set_result_tab("timeline")
        window._set_timeline_items(items)
        window.timeline_text.setFixedHeight(120)
        app.processEvents()

        payloads = []
        window.detail_webview.update_playback = payloads.append
        window._refresh_timeline_highlight(10.1)
        app.processEvents()
        scroll_bar = window.timeline_text.verticalScrollBar()
        assert scroll_bar.maximum() > 0
        assert payloads[-1]["positionSeconds"] == 10.1

        manual_scroll = min(scroll_bar.maximum(), max(1, scroll_bar.maximum() // 2))
        scroll_bar.setValue(manual_scroll)
        app.processEvents()

        window._refresh_timeline_highlight(10.6)
        app.processEvents()

        assert scroll_bar.value() == manual_scroll
        assert payloads[-1]["positionSeconds"] == 10.6
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

        monkeypatch.setattr("src.asr.timestamps.timeline_to_html", fail_timeline_render)
        window.active_result_tab = "transcript"
        window.timeline_items = [{"start": 0.0, "end": 1.0, "text": "hidden"}]
        window.media_player = FakeMediaPlayer()
        payloads = []
        window.detail_webview.update_playback = payloads.append

        window.stop_playback()

        assert payloads[-1]["positionSeconds"] == 0.0
        assert payloads[-1]["isPlaying"] is False
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
        assert window.content_stack.currentWidget() == window.history_page
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
