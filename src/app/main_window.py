"""PySide6 主窗口。"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..audio import AudioRecorder
from ..audio.preprocess import AudioInputError, probe_media
from .config import ensure_dirs, get_config, get_notebooks, save_config
from ..handlers.export import ExportHandlers
from ..handlers.history_view import HistoryViewHandlers
from ..handlers.media_import import ImportHandlers
from ..handlers.playback import PlaybackHandlers
from ..handlers.processing import ProcessingHandlers
from ..handlers.recording import RecordingHandlers
from ..handlers.remote_import import RemoteImportHandlers
from ..handlers.settings import SettingsHandlers
from ..handlers.summary import SummaryHandlers
from ..handlers.timeline_view import TimelineViewHandlers
from ..handlers.transcription import TranscriptionHandlers
from ..ui.widgets.dialogs import alert_without_icon, confirm_without_icon, prompt_text_without_icon
from ..history.service import HistoryRecord, HistoryService
from ..model_registry.downloader import ModelDownloadManager
from ..ui.settings import SettingsPanel
from ..ui.content import HistoryPageCallbacks, build_history_page
from ..ui.sidebar import build_history_sidebar, build_settings_sidebar
from ..ui.icons import make_action_icon, make_app_icon
from ..ui.recording import build_recording_page
from ..ui.result import set_result_tab, set_summary_text, set_transcript_text
from ..utils.logging import log_event, record_context

if TYPE_CHECKING:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


class MainWindow(
    ImportHandlers,
    RemoteImportHandlers,
    RecordingHandlers,
    ProcessingHandlers,
    TranscriptionHandlers,
    SummaryHandlers,
    SettingsHandlers,
    HistoryViewHandlers,
    TimelineViewHandlers,
    PlaybackHandlers,
    ExportHandlers,
    QMainWindow,
):
    """NoisNote主窗口。"""

    def __init__(self):
        super().__init__()
        self.config = get_config()
        ensure_dirs(self.config)
        self.history_service = HistoryService.from_notebooks(
            get_notebooks(self.config),
            active_notebook_id=str(self.config.get("active_notebook_id") or "default"),
        )
        self.model_download_manager = ModelDownloadManager(self.config, self)
        self.recorder: AudioRecorder | None = None
        self.current_record: HistoryRecord | None = None
        self.processing_record: HistoryRecord | None = None
        self.all_history_items: list[HistoryRecord] = []
        self.current_items: list[HistoryRecord] = []
        self.history_search_text = ""
        self.history_status_filter = "all"
        self.active_workers: list[object] = []
        self.is_recording = False
        self.is_processing = False
        self.processing_source: str | None = None
        self.previous_content_widget: QWidget | None = None
        self.processing_started_at: dict[str, float] = {}
        self.latest_transcription_percent: int | None = None
        self.history_record_notices: dict[str, str] = {}
        self.dismissed_history_notice_ids: set[str] = set()
        self.silence_started_at: float | None = None
        self.active_result_tab = "transcript"
        self.summary_markdown_text = ""
        self.active_task_ids: dict[str, str] = {}
        self.timeline_items: list[dict] = []
        self.transcript_loaded_record_id = ""
        self.summary_loaded_record_id = ""
        self.timeline_loaded_record_id = ""
        self._last_timeline_highlight_key: tuple[int | None, int | None] = (None, None)
        self._last_history_selected_index = -1
        self.media_player: QMediaPlayer | None = None
        self.audio_output: QAudioOutput | None = None
        self.playback_record_id = ""
        self.playback_loaded_record_id = ""
        self.playback_duration_ms = 0
        self.playback_rate = 1.0
        self._updating_playback_slider = False

        self.setWindowTitle("NoisNote")
        self.setWindowIcon(make_app_icon())
        self.resize(1100, 760)
        self.setMinimumSize(880, 620)
        self.setAcceptDrops(True)

        self.record_timer = QTimer(self)
        self.record_timer.setInterval(120)
        self.record_timer.timeout.connect(self._refresh_recording_state)

        self._build_ui()
        self._init_media_player()
        self._init_playback_shortcuts()
        self.model_download_manager.download_failed.connect(self._on_model_download_failed)
        self.model_download_manager.download_completed.connect(self._on_model_download_completed)
        self.model_download_manager.download_cancelled.connect(self._on_model_download_cancelled)
        self.model_download_manager.models_changed.connect(self._refresh_settings_after_model_change)
        self._init_recorder()
        self.load_recordings()
        self._import_demo_audio_if_empty()
        self._set_status("")
        log_event(
            "app.window.ready",
            module="ui",
            message="主窗口初始化完成",
            context={"history_count": len(self.current_items)},
        )

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        self.sidebar_stack = QStackedWidget()
        self.sidebar_stack.setFixedWidth(240)
        self.main_sidebar = self._build_sidebar()
        self.settings_sidebar = self._build_settings_sidebar()
        self.sidebar_stack.addWidget(self.main_sidebar)
        self.sidebar_stack.addWidget(self.settings_sidebar)

        root_layout.addWidget(self.sidebar_stack)
        root_layout.addWidget(self._build_main_area(), stretch=1)

    def _build_sidebar(self) -> QWidget:
        sidebar, controls = build_history_sidebar(
            self,
            make_action_icon,
            self.new_recording,
            self.import_audio_recording,
            self.import_remote_url,
            self._select_history_item,
            self.show_settings,
        )
        self.new_recording_sidebar_button = controls.new_recording_button
        self.import_audio_sidebar_button = controls.import_audio_button
        self.remote_import_sidebar_button = controls.remote_import_button
        self.history_search = controls.history_search
        self.history_filter_button = controls.history_filter_button
        self.history_list = controls.history_list
        self.empty_history_label = controls.empty_history_label
        self.settings_button = controls.settings_button
        self.history_search.textChanged.connect(self._on_history_search_changed)
        self.history_filter_button.setMenu(self._build_history_filter_menu())
        return sidebar

    def _build_settings_sidebar(self) -> QWidget:
        sidebar, controls = build_settings_sidebar(
            self,
            make_action_icon,
            self.hide_settings,
            self.show_settings_section,
        )
        self.settings_back_button = controls.back_button
        self.settings_general_button = controls.general_button
        self.settings_models_button = controls.models_button
        self.settings_hotwords_button = controls.hotwords_button
        self.settings_shortcuts_button = controls.shortcuts_button
        self.settings_nav_buttons = [
            self.settings_general_button,
            self.settings_models_button,
            self.settings_hotwords_button,
            self.settings_shortcuts_button,
        ]
        return sidebar

    def _build_main_area(self) -> QWidget:
        container = QFrame()
        container.setObjectName("MainArea")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 18, 18)
        layout.setSpacing(0)

        self.page_title_label = QLabel("")
        self.page_title_label.setObjectName("Title")
        self.page_title_label.hide()
        self.status_label = QLabel()
        self.status_label.setObjectName("Muted")
        self.status_label.hide()

        self.content_stack = QStackedWidget()
        self.recording_page = self._build_recording_page()
        self.history_page = self._build_history_page()
        self.settings_panel = SettingsPanel(self.config, self.model_download_manager, self)
        self.settings_panel.saved.connect(self._apply_settings_config)
        self.settings_panel.cancelled.connect(self.hide_settings)
        self.settings_panel.hotwords_changed.connect(self._persist_settings_config)
        self.content_stack.addWidget(self.recording_page)
        self.content_stack.addWidget(self.history_page)
        self.content_stack.addWidget(self.settings_panel)

        layout.addWidget(self.content_stack, stretch=1)
        return container

    def _build_recording_page(self) -> QWidget:
        page, controls = build_recording_page(
            self,
            make_action_icon,
            self.toggle_recording,
            self._on_capture_mode_changed,
            self._on_device_selection_changed,
        )
        self.record_button = controls.record_button
        self.capture_mode_combo = controls.capture_mode_combo
        self.system_device_combo = controls.system_device_combo
        self.microphone_device_combo = controls.microphone_device_combo
        self.system_device_widget = controls.system_device_widget
        self.microphone_device_widget = controls.microphone_device_widget
        self.duration_label = controls.duration_label
        self.level_bar = controls.level_bar
        self.level_text_label = controls.level_text_label
        self.record_device_label = controls.record_device_label
        self.recording_hint_label = controls.recording_hint_label
        return page

    def _build_history_page(self) -> QWidget:
        page, controls = build_history_page(
            self,
            HistoryPageCallbacks(
                set_result_tab=self._set_result_tab,
                manual_summarize=self.manual_summarize,
                retry_transcription=self.retry_transcription,
                copy_panel_text=self.copy_panel_text,
                export_result=self._export_result_with_format,
                seek_backward=self.seek_playback_backward,
                toggle_playback=self.toggle_playback,
                seek_forward=self.seek_playback_forward,
                seek_playback=self.seek_playback,
                set_playback_rate=self.set_playback_rate,
                switch_to_timeline=self._switch_to_timeline_tab,
            ),
        )
        self.result_stack = controls.result_stack
        self.transcript_tab_button = controls.transcript_tab_button
        self.timeline_tab_button = controls.timeline_tab_button
        self.summary_tab_button = controls.summary_tab_button
        self.detail_title_label = controls.detail_title_label
        self.detail_duration_label = controls.detail_duration_label
        self.detail_size_label = controls.detail_size_label
        self.detail_status_label = controls.detail_status_label
        self.detail_time_label = controls.detail_time_label
        self.detail_processing_status_label = controls.detail_processing_status_label
        self.transcript_status = controls.transcript_status
        self.transcript_text = controls.transcript_text
        self.transcript_copy_button = controls.transcript_copy_button
        self.retry_transcription_button = controls.retry_transcription_button
        self.timeline_status = controls.timeline_status
        self.timeline_text = controls.timeline_text
        self.timeline_copy_button = controls.timeline_copy_button
        self.summary_status = controls.summary_status
        self.summary_text = controls.summary_text
        self.summary_copy_button = controls.summary_copy_button
        self.manual_summary_button = controls.manual_summary_button
        self.export_button = controls.export_button
        self.playback_back_button = controls.playback_back_button
        self.playback_play_button = controls.playback_play_button
        self.playback_forward_button = controls.playback_forward_button
        self.playback_position_label = controls.playback_position_label
        self.playback_duration_label = controls.playback_duration_label
        self.playback_slider = controls.playback_slider
        self.playback_rate_combo = controls.playback_rate_combo
        self.playback_cc_button = controls.playback_cc_button
        self._set_result_tab("transcript")
        return page

    def _set_transcript_text(self, text: str) -> None:
        """写入转录文本，并同步当前页复制按钮。"""
        set_transcript_text(self, text)

    def _set_result_tab(self, kind: str) -> None:
        """切换详情结果区标签，并保留用户的当前选择。"""
        previous_tab = self.active_result_tab
        set_result_tab(self, kind)
        if previous_tab == "timeline" and self.active_result_tab != "timeline":
            self._release_timeline_resources()
        self._ensure_active_result_loaded()

    def _set_summary_text(self, summary: str) -> None:
        """以 Markdown 方式展示总结，同时保留原文用于复制和导出。"""
        set_summary_text(self, summary)

    def _new_task_id(self, prefix: str) -> str:
        """生成一次后台任务的轻量追踪 ID。"""
        return f"{prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    def _import_demo_audio_if_empty(self) -> None:
        """历史记录为空时导入内置测试音频（复制到用户数据目录）。"""
        if self.config.get("demo_audio_imported"):
            return
        if self.all_history_items:
            self.config["demo_audio_imported"] = True
            save_config(self.config)
            return
        demo_audio = self._resolve_demo_audio_path()
        if not demo_audio or not demo_audio.exists():
            return
        try:
            try:
                probe = probe_media(demo_audio, self.config)
            except AudioInputError as exc:
                log_event(
                    "record.import.demo_failed",
                    level="ERROR",
                    module="history",
                    message="内置测试音频探测失败",
                    context={"error": exc.to_metadata()},
                )
                return
            audio_format: dict[str, object] = {
                "sample_rate": probe.audio_sample_rate,
                "channels": probe.audio_channels,
                "format": demo_audio.suffix.lower().lstrip("."),
                "source_format": probe.source_format,
            }
            record = self.history_service.copy_imported_audio_file(
                demo_audio,
                duration_seconds=probe.duration_seconds,
                audio_format=audio_format,
                source_kind="local_audio",
            )
            self.current_record = record
            self.load_recordings()
            self._select_record_by_key(record.record_key)
            self.config["demo_audio_imported"] = True
            save_config(self.config)
            log_event(
                "record.import.demo",
                module="history",
                message="已导入内置测试音频",
                context={"record_id": record.record_id},
            )
        except Exception as exc:
            log_event(
                "record.import.demo_failed",
                level="WARNING",
                module="history",
                message="导入内置测试音频失败",
                context={"error": str(exc)},
            )

    def _resolve_demo_audio_path(self) -> Path | None:
        """定位内置测试音频文件路径。"""
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            candidate = Path(str(bundle_root)) / "src" / "assets" / "测试音频.mp3"
            if candidate.exists():
                return candidate
        # 开发环境：项目源码目录
        dev_candidate = Path(__file__).resolve().parents[1] / "assets" / "测试音频.mp3"
        if dev_candidate.exists():
            return dev_candidate
        return None

    def rename_history_record(self, index: int) -> None:
        """重命名历史记录。"""
        if index < 0 or index >= len(self.current_items):
            return
        record = self.current_items[index]
        was_current = bool(self.current_record and self.current_record.record_key == record.record_key)
        new_name, accepted = prompt_text_without_icon(
            self,
            "重命名",
            "记录名称：",
            value=record.record_id,
        )
        if not accepted:
            return
        try:
            renamed = self.history_service.rename_record(record, new_name)
        except Exception as exc:
            self._show_error(f"重命名失败：{exc}")
            return

        if was_current:
            self.current_record = renamed
        self.load_recordings()
        if was_current:
            self._select_record_by_key(renamed.record_key)
        self._set_status("记录已重命名")

    def open_history_record_folder(self, index: int) -> None:
        """在系统文件管理器中打开记录文件夹。"""
        if index < 0 or index >= len(self.current_items):
            return
        record = self.current_items[index]
        folder = record.record_dir
        if not folder.exists():
            self._show_error(f"记录文件夹不存在：{folder}")
            return
        try:
            os.startfile(str(folder))
        except OSError as exc:
            self._show_error(f"无法打开记录文件夹：{exc}")

    def delete_history_record(self, index: int) -> None:
        """从菜单删除指定历史记录。"""
        if index < 0 or index >= len(self.current_items):
            return
        record = self.current_items[index]
        clear_current = bool(self.current_record and self.current_record.record_key == record.record_key)
        self._delete_record(record, clear_current=clear_current)

    def copy_panel_text(self, kind: str) -> None:
        """复制转录或总结文本到系统剪贴板。"""
        if kind == "transcript":
            text = self.transcript_text.toPlainText()
            label = "转录文字"
        elif kind == "timeline":
            text = self.timeline_text.toPlainText()
            label = "逐句时间轴"
        else:
            text = self.summary_markdown_text
            label = "总结内容"

        if not text.strip():
            self._set_status(f"{label}为空，无法复制")
            return
        QApplication.clipboard().setText(text)
        self._set_status(f"已复制{label}")

    def delete_current_record(self) -> None:
        """删除当前选中的历史记录。"""
        if not self.current_record:
            self._show_error("请先选择一条历史记录")
            return
        self._delete_record(self.current_record, clear_current=True)

    def _delete_record(self, record: HistoryRecord, clear_current: bool) -> None:
        confirmed = confirm_without_icon(
            self,
            "删除历史记录",
            "确定删除这条历史记录吗?\n"
            "音频文件、转录结果等都会被清理。",
        )
        if not confirmed:
            self._set_status("已取消删除")
            return

        if record.record_key == self.playback_record_id:
            self.stop_playback()
            self.playback_record_id = ""
            QApplication.processEvents()
        log_event(
            "record.delete.started",
            module="history",
            message="开始删除历史记录",
            record_id=record.record_id,
            context={"record": record_context(record)},
        )
        result = self.history_service.delete_record(record)
        if not result.success:
            log_event(
                "record.delete.failed",
                level="ERROR",
                module="history",
                message="删除历史记录失败",
                record_id=record.record_id,
                context={"record": record_context(record), "error": result.message},
                error_code="HIS-002",
            )
            self._show_error(result.message)
            return
        log_event(
            "record.delete.completed",
            module="history",
            message="历史记录已删除",
            record_id=record.record_id,
            context={"deleted_count": len(result.deleted_paths), "skipped_count": len(result.skipped_paths)},
        )

        if clear_current:
            self.new_recording()
        self.load_recordings()
        self._set_status(result.message)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _show_error(self, message: str) -> None:
        self._set_status(message)
        alert_without_icon(self, "提示", message)

    def _display_time(self, path: Path) -> str:
        try:
            return datetime.strptime(path.stem, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return path.stem

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_playback()
        if self.is_recording and self.recorder:
            self.recorder.stop_recording()
        if self.model_download_manager.has_active_downloads():
            confirmed = confirm_without_icon(
                self,
                "模型下载仍在运行",
                "模型仍在下载中，退出应用会中断下载。确定退出吗?",
            )
            if not confirmed:
                event.ignore()
                return
            self.model_download_manager.cancel_all_downloads()
        if self.active_workers:
            confirmed = confirm_without_icon(
                self,
                "后台任务仍在运行",
                "转录或总结仍在运行，确定退出吗?",
            )
            if not confirmed:
                event.ignore()
                return
        if self.recorder:
            self.recorder.cleanup()
        event.accept()
