"""PySide6 主窗口。"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..audio import AudioRecorder
from ..audio.preprocess import AudioInputError, probe_media
from .config import ensure_dirs, get_config, get_notebooks, save_config
from ..handlers.detail_view import DetailViewHandlers
from ..handlers.export import ExportHandlers
from ..handlers.history_view import HistoryViewHandlers
from ..handlers.media_import import ImportHandlers
from ..handlers.playback import PlaybackHandlers
from ..handlers.processing import ProcessingHandlers
from ..handlers.recording import RecordingHandlers
from ..handlers.remote_import import RemoteImportHandlers
from ..handlers.settings import SettingsHandlers
from ..handlers.summary import SummaryHandlers
from ..handlers.task_queue import TaskQueueHandlers
from ..handlers.timeline_view import TimelineViewHandlers
from ..handlers.transcription import TranscriptionHandlers
from ..ui.widgets.dialogs import alert_without_icon, confirm_without_icon, prompt_text_without_icon
from ..history.service import HistoryRecord, HistoryService
from ..model_registry.downloader import ModelDownloadManager
from ..ui.pages.settings import SettingsPanel
from ..ui.pages.content import HistoryPageCallbacks, build_history_page
from ..ui.detail.models import build_metadata_fields
from ..ui.widgets.history_item import ElidedLabel, ElidedLinkLabel
from ..ui.pages.sidebar import build_history_sidebar
from ..ui.core.icons import make_action_icon, make_app_icon
from ..ui.pages.recording import build_recording_page
from ..ui.pages.result import set_result_tab, set_summary_text, set_transcript_text
from ..ui.dialogs.settings import SettingsDialog
from ..ui.pages.workbench import build_quick_toolbar, build_task_panel, install_workbench_menus
from ..utils.logging import log_event, record_context

if TYPE_CHECKING:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


_DETAIL_METADATA_ANIMATION_MS = 140
_DETAIL_WEBVIEW_RESIZE_COVER_HEIGHT = 180
_DETAIL_WEBVIEW_RESIZE_COVER_MS = 220
_DETAIL_WEBVIEW_WIDTH_RESIZE_COVER_MS = 260
_DETAIL_SCROLL_STATE_DELAY_MS = 80

class MainWindow(
    ImportHandlers,
    RemoteImportHandlers,
    RecordingHandlers,
    ProcessingHandlers,
    TranscriptionHandlers,
    SummaryHandlers,
    SettingsHandlers,
    HistoryViewHandlers,
    DetailViewHandlers,
    TimelineViewHandlers,
    PlaybackHandlers,
    ExportHandlers,
    TaskQueueHandlers,
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
        self.task_manager = None
        self.current_processing_task = None
        self.summary_worker = None
        self.all_history_items: list[HistoryRecord] = []
        self.current_items: list[HistoryRecord] = []
        self.current_notebook_id = str(self.config.get("active_notebook_id") or "default")
        self.active_workers: list[object] = []
        self.is_recording = False
        self.is_processing = False
        self.processing_source: str | None = None
        self.active_remote_imports: dict[str, dict[str, object]] = {}
        self._closing_for_exit = False
        self.previous_content_widget: QWidget | None = None
        self.processing_started_at: dict[str, float] = {}
        self.latest_transcription_percent: int | None = None
        self.history_record_notices: dict[str, str] = {}
        self.dismissed_history_notice_ids: set[str] = set()
        self.silence_started_at: float | None = None
        self.active_result_tab = "transcript"
        self.detail_revision = 0
        self.detail_edit_mode = False
        self.detail_search_query = ""
        self.detail_search_index = 0
        self.detail_search_match_count_from_webview: int | None = None
        self.transcript_plain_text = ""
        self.summary_markdown_text = ""
        self.active_task_ids: dict[str, str] = {}
        self.timeline_items: list[dict] = []
        self.transcript_loaded_record_id = ""
        self.summary_loaded_record_id = ""
        self.timeline_loaded_record_id = ""
        self._last_history_selected_index = -1
        self.media_player: QMediaPlayer | None = None
        self.audio_output: QAudioOutput | None = None
        self.playback_record_id = ""
        self.playback_loaded_record_id = ""
        self.playback_duration_ms = 0
        self.playback_rate = 1.0
        self._updating_playback_slider = False
        self.settings_dialog: SettingsDialog | None = None
        self.recording_dialog = None
        self._stopping_recording = False
        self.detail_metadata_expanded = False
        self._detail_metadata_animation: QPropertyAnimation | None = None
        self._detail_metadata_discard_parent: QWidget | None = None
        self._pending_detail_scroll_at_top: bool | None = None
        self._detail_scroll_state_timer = QTimer(self)
        self._detail_scroll_state_timer.setSingleShot(True)
        self._detail_scroll_state_timer.timeout.connect(self._apply_pending_detail_scroll_state)

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
        self._init_task_queue()
        self._import_demo_audio_if_empty()
        self._restore_last_selected_record()
        if not self.status_label.text():
            self._set_status("")
        log_event(
            "app.window.ready",
            module="ui",
            message="主窗口初始化完成",
            context={"history_count": len(self.current_items)},
        )

    def _build_ui(self) -> None:
        self._build_workbench_chrome()

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        root_layout.addWidget(self.quick_toolbar)

        self.sidebar_stack = QStackedWidget()
        self.sidebar_stack.setMinimumWidth(220)
        self.sidebar_stack.setMaximumWidth(620)
        self.main_sidebar = self._build_sidebar()
        self.main_sidebar.setMinimumWidth(220)
        self.sidebar_stack.addWidget(self.main_sidebar)

        self.workbench_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workbench_splitter.setObjectName("WorkbenchSplitter")
        self.workbench_splitter.setChildrenCollapsible(False)
        self.task_panel = build_task_panel(self)
        self.workbench_splitter.addWidget(self.sidebar_stack)
        self.workbench_splitter.addWidget(self._build_main_area())
        self.workbench_splitter.addWidget(self.task_panel)
        self.workbench_splitter.setStretchFactor(0, 0)
        self.workbench_splitter.setStretchFactor(1, 1)
        self.workbench_splitter.setStretchFactor(2, 0)
        self.workbench_splitter.setSizes([240, 760, 240])

        root_layout.addWidget(self.workbench_splitter, stretch=1)

    def _build_workbench_chrome(self) -> None:
        toolbar_controls = build_quick_toolbar(
            self,
            make_action_icon,
            record=self.show_recording_dialog,
            import_audio=self.import_audio_recording,
            remote_import=self.import_remote_url,
            export_result=self._export_result_with_format,
            settings=self.show_settings,
        )
        self.quick_toolbar = toolbar_controls.toolbar
        self.record_toolbar_button = toolbar_controls.record_button
        self.import_audio_toolbar_button = toolbar_controls.import_audio_button
        self.remote_import_toolbar_button = toolbar_controls.remote_import_button
        self.export_toolbar_button = toolbar_controls.export_button
        self.settings_toolbar_button = toolbar_controls.settings_button
        view_actions = install_workbench_menus(
            self,
            record=self.show_recording_dialog,
            import_audio=self.import_audio_recording,
            remote_import=self.import_remote_url,
            export_result=self._export_result_with_format,
            new_notebook=self.show_new_notebook_dialog,
            manage_notebooks=self.show_manage_notebooks_dialog,
            settings=self.show_settings,
            check_update=self._show_update_check,
            toggle_quick_toolbar=self._set_quick_toolbar_visible,
            toggle_history=self._set_history_panel_visible,
            toggle_playback=self._set_playback_panel_visible,
            toggle_tasks=self._set_task_panel_visible,
        )
        self.toggle_quick_toolbar_action = view_actions["quick_toolbar"]
        self.toggle_history_panel_action = view_actions["history"]
        self.toggle_playback_panel_action = view_actions["playback"]
        self.toggle_task_panel_action = view_actions["tasks"]

    def _set_quick_toolbar_visible(self, visible: bool) -> None:
        self.quick_toolbar.setVisible(visible)

    def _set_history_panel_visible(self, visible: bool) -> None:
        if hasattr(self, "sidebar_stack") and self.sidebar_stack.isHidden() == visible:
            self._cover_detail_webview_width_resize()
        self.sidebar_stack.setVisible(visible)

    def _set_playback_panel_visible(self, visible: bool) -> None:
        if hasattr(self, "playback_widget"):
            self.playback_widget.setVisible(visible)
        if hasattr(self, "playback_separator"):
            self.playback_separator.setVisible(visible)

    def _set_task_panel_visible(self, visible: bool) -> None:
        if hasattr(self, "task_panel") and self.task_panel.isHidden() == visible:
            self._cover_detail_webview_width_resize()
        self.task_panel.setVisible(visible)

    def _show_update_check(self) -> None:
        self.settings_panel._on_check_update_clicked()

    def _build_sidebar(self) -> QWidget:
        sidebar, controls = build_history_sidebar(
            self,
            self._select_history_item,
        )
        self.notebook_selector = controls.notebook_selector
        self.history_tree = controls.history_tree
        self._refresh_notebook_selector()
        self.notebook_selector.currentIndexChanged.connect(self._on_notebook_selection_changed)
        self.history_tree.rename_requested.connect(self._rename_record_by_key)
        self.history_tree.open_folder_requested.connect(self._open_record_folder_by_key)
        self.history_tree.delete_requested.connect(self._delete_records_by_keys)
        self.history_tree.move_requested.connect(self._move_records_to_notebook)
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
        self.settings_panel = SettingsPanel(self.config, self.model_download_manager, None)
        self.settings_panel.saved.connect(self._apply_settings_config)
        self.settings_panel.cancelled.connect(self.hide_settings)
        self.settings_panel.hotwords_changed.connect(self._persist_settings_config)
        self.settings_panel.hide()
        self.content_stack.addWidget(self.history_page)
        self.content_stack.setCurrentWidget(self.history_page)

        layout.addWidget(self.content_stack, stretch=1)
        return container

    def _build_recording_page(self) -> QWidget:
        page, controls = build_recording_page(
            None,
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
        page.hide()
        return page

    def _build_history_page(self) -> QWidget:
        page, controls = build_history_page(
            self,
            HistoryPageCallbacks(
                set_result_tab=self._set_result_tab,
                manual_summarize=self.manual_summarize,
                retry_transcription=self.retry_transcription,
                show_metadata_details=self.show_metadata_details,
                show_detail_action_menu=self.show_detail_action_menu,
                open_current_record_folder=self.open_current_record_folder,
                delete_current_record=self.delete_current_record,
                copy_panel_text=self.copy_panel_text,
                export_result=self._export_result_with_format,
                toggle_detail_search=self.toggle_detail_search,
                update_detail_search=self.update_detail_search,
                find_detail_previous=self.find_detail_previous,
                find_detail_next=self.find_detail_next,
                clear_detail_search=self.clear_detail_search,
                toggle_detail_edit_mode=self.toggle_detail_edit_mode,
                seek_backward=self.seek_playback_backward,
                toggle_playback=self.toggle_playback,
                seek_forward=self.seek_playback_forward,
                seek_playback=self.seek_playback,
                set_playback_rate=self.set_playback_rate,
                switch_to_timeline=self._switch_to_timeline_tab,
                detail_web_command=self._on_detail_web_command,
            ),
        )
        self.detail_webview = controls.detail_webview
        self.result_stack = controls.result_stack
        self.detail_header = controls.detail_header
        self.transcript_tab_button = controls.transcript_tab_button
        self.timeline_tab_button = controls.timeline_tab_button
        self.summary_tab_button = controls.summary_tab_button
        self.detail_title_label = controls.detail_title_label
        self.detail_duration_label = controls.detail_duration_label
        self.detail_size_label = controls.detail_size_label
        self.detail_time_label = controls.detail_time_label
        self.detail_processing_status_label = controls.detail_processing_status_label
        self.detail_metadata_button = controls.detail_metadata_button
        self.detail_metadata_panel = controls.detail_metadata_panel
        self.detail_more_button = controls.detail_more_button
        self.detail_copy_button = controls.detail_copy_button
        self.detail_search_button = controls.detail_search_button
        self.detail_edit_toggle_button = controls.detail_edit_toggle_button
        self.detail_copy_notice_label = controls.detail_copy_notice_label
        self.detail_search_bar = controls.detail_search_bar
        self.detail_search_input = controls.detail_search_input
        self.detail_search_count_label = controls.detail_search_count_label
        self.detail_search_prev_button = controls.detail_search_prev_button
        self.detail_search_next_button = controls.detail_search_next_button
        self.detail_search_clear_button = controls.detail_search_clear_button
        self.detail_action_menu = controls.detail_action_menu
        self.detail_transcribe_action = controls.detail_transcribe_action
        self.detail_summary_action = controls.detail_summary_action
        self.detail_open_folder_action = controls.detail_open_folder_action
        self.detail_delete_action = controls.detail_delete_action
        self.transcript_status = controls.transcript_status
        self.transcript_text = controls.transcript_text
        self.transcript_copy_button = controls.transcript_copy_button
        self.transcript_copy_notice_label = controls.transcript_copy_notice_label
        self.timeline_status = controls.timeline_status
        self.timeline_text = controls.timeline_text
        self.timeline_copy_button = controls.timeline_copy_button
        self.timeline_copy_notice_label = controls.timeline_copy_notice_label
        self.summary_status = controls.summary_status
        self.summary_text = controls.summary_text
        self.summary_copy_button = controls.summary_copy_button
        self.summary_copy_notice_label = controls.summary_copy_notice_label
        self.playback_widget = controls.playback_widget
        self.playback_separator = controls.playback_separator
        self.playback_back_button = controls.playback_back_button
        self.playback_play_button = controls.playback_play_button
        self.playback_forward_button = controls.playback_forward_button
        self.playback_position_label = controls.playback_position_label
        self.playback_duration_label = controls.playback_duration_label
        self.playback_notice_label = controls.playback_notice_label
        self.playback_slider = controls.playback_slider
        self.playback_rate_combo = controls.playback_rate_combo
        self.playback_cc_button = controls.playback_cc_button
        self._set_result_tab("transcript")
        self._apply_detail_edit_mode()
        self._sync_detail_action_menu()
        return page

    def _on_detail_web_command(self, value: dict) -> None:
        """接收详情 WebView 命令并交给详情处理器分发。"""
        DetailViewHandlers._on_detail_web_command(self, value)

    def _set_transcript_text(self, text: str) -> None:
        """写入转录文本，并同步当前页复制按钮。"""
        set_transcript_text(self, text)
        if self.current_record:
            self.transcript_loaded_record_id = self.current_record.record_key
        if self.active_result_tab == "transcript":
            self._bump_detail_revision()
            self._refresh_detail_payload()

    def _set_result_tab(self, kind: str) -> None:
        """切换详情结果区标签，并保留用户的当前选择。"""
        previous_tab = self.active_result_tab
        set_result_tab(self, kind)
        if previous_tab == "timeline" and self.active_result_tab != "timeline":
            self._release_timeline_resources()
        self._ensure_active_result_loaded()
        if previous_tab != self.active_result_tab:
            self._bump_detail_revision()
        self._refresh_detail_payload()
        self._refresh_detail_search()
        self._apply_detail_edit_mode()

    def _set_summary_text(self, summary: str) -> None:
        """以 Markdown 方式展示总结，同时保留原文用于复制和导出。"""
        set_summary_text(self, summary)
        if self.current_record:
            self.summary_loaded_record_id = self.current_record.record_key
        if self.active_result_tab == "summary":
            self._bump_detail_revision()
            self._refresh_detail_payload()

    def _sync_detail_action_menu(self) -> None:
        """同步详情页头部菜单和详细信息入口的可用状态。"""
        if not hasattr(self, "detail_action_menu"):
            return
        record = self.current_record
        has_record = record is not None
        self.detail_more_button.setEnabled(True)
        self.detail_metadata_button.setEnabled(has_record)
        if not has_record:
            self.detail_metadata_expanded = False
            self.detail_metadata_button.setChecked(False)
            self._set_detail_metadata_panel_expanded(False, animate=False)
            self.detail_header.show()
        for action in self.detail_action_menu.actions():
            action.setEnabled(True)

    def show_metadata_details(self) -> None:
        """展开或收起当前历史记录的内联元数据区域。"""
        if not self.current_record:
            self._set_status("请先选择一条历史记录")
            return
        expanded = not bool(getattr(self, "detail_metadata_expanded", False))
        self.detail_metadata_expanded = expanded
        self._set_detail_metadata_panel_expanded(expanded, animate=True)
        self.detail_metadata_button.setChecked(expanded)

    def _set_detail_metadata_panel_expanded(self, expanded: bool, *, animate: bool) -> None:
        panel = self.detail_metadata_panel
        animation = getattr(self, "_detail_metadata_animation", None)
        if animation is not None:
            animation.stop()
            self._detail_metadata_animation = None

        if expanded:
            self._populate_detail_metadata_panel()
            panel.setVisible(True)
            target_height = self._detail_metadata_panel_height()
            if not animate:
                panel.setMaximumHeight(target_height)
                return
            self._cover_detail_webview_resize()
            start_height = panel.height() if panel.maximumHeight() > target_height else panel.maximumHeight()
            self._animate_detail_metadata_panel_height(max(0, start_height), target_height)
            return

        start_height = panel.height() if panel.isVisible() else panel.maximumHeight()
        if not animate or start_height <= 0:
            if panel.isVisible():
                self._cover_detail_webview_resize()
            panel.setMaximumHeight(0)
            panel.hide()
            return
        self._cover_detail_webview_resize()
        self._animate_detail_metadata_panel_height(start_height, 0)

    def _cover_detail_webview_resize(self) -> None:
        cover = getattr(self.detail_webview, "cover_bottom_for_layout_transition", None)
        if callable(cover):
            cover(_DETAIL_WEBVIEW_RESIZE_COVER_HEIGHT, _DETAIL_WEBVIEW_RESIZE_COVER_MS)

    def _cover_detail_webview_width_resize(self) -> None:
        cover = getattr(self.detail_webview, "cover_for_layout_transition", None)
        if callable(cover):
            cover(_DETAIL_WEBVIEW_WIDTH_RESIZE_COVER_MS)
            return
        self._cover_detail_webview_resize()

    def _detail_metadata_panel_height(self) -> int:
        layout = self.detail_metadata_panel.layout()
        if layout is not None:
            layout.activate()
        return max(1, self.detail_metadata_panel.sizeHint().height())

    def _animate_detail_metadata_panel_height(self, start: int, end: int) -> None:
        panel = self.detail_metadata_panel
        panel.setMaximumHeight(max(0, start))
        animation = QPropertyAnimation(panel, b"maximumHeight", self)
        animation.setDuration(_DETAIL_METADATA_ANIMATION_MS)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(max(0, start))
        animation.setEndValue(max(0, end))
        animation.valueChanged.connect(lambda _value: self._relayout_detail_metadata_panel())

        def finish() -> None:
            self._detail_metadata_animation = None
            if bool(getattr(self, "detail_metadata_expanded", False)):
                panel.setVisible(True)
                panel.setMaximumHeight(self._detail_metadata_panel_height())
            else:
                panel.setMaximumHeight(0)
                panel.hide()

        animation.finished.connect(finish)
        self._detail_metadata_animation = animation
        animation.start()

    def _relayout_detail_metadata_panel(self) -> None:
        panel = self.detail_metadata_panel
        panel.updateGeometry()
        for widget in (self.detail_header, self.history_page):
            layout = widget.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()

    def _populate_detail_metadata_panel(self) -> None:
        """将当前记录元数据填充到详情头的内联面板。"""
        if not self.current_record:
            return
        layout = self.detail_metadata_panel.layout()
        if not isinstance(layout, QGridLayout):
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(self._detail_metadata_discard_widget())
                widget.deleteLater()

        fields = build_metadata_fields(self.current_record)
        split_at = (len(fields) + 1) // 2
        for index, field in enumerate(fields):
            side = 0 if index < split_at else 1
            row = index if side == 0 else index - split_at
            label_column = side * 2
            value_column = label_column + 1

            field_label = str(field.get("label") or "")
            field_value = str(field.get("value") or "--")
            label = QLabel(field_label)
            label.setObjectName("DetailMetadataLabel")
            if field_label == "网址" and field_value != "--":
                value = ElidedLinkLabel(field_value, field_value)
                value.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
            else:
                value = ElidedLabel(field_value)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setObjectName("DetailMetadataValue")
            value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value.setWordWrap(False)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

            layout.addWidget(label, row, label_column)
            layout.addWidget(value, row, value_column)
            label.show()
            value.show()

    def _detail_metadata_discard_widget(self) -> QWidget:
        discard = self._detail_metadata_discard_parent
        if discard is None:
            discard = QWidget(self.detail_metadata_panel)
            discard.hide()
            self._detail_metadata_discard_parent = discard
        return discard

    def _set_detail_metadata_scrolled_to_top(self, at_top: bool) -> None:
        """根据正文滚动位置自动显示或隐藏整个详情头部区域。"""
        if not self.current_record:
            return
        self._pending_detail_scroll_at_top = bool(at_top)
        self._detail_scroll_state_timer.start(_DETAIL_SCROLL_STATE_DELAY_MS)

    def _apply_pending_detail_scroll_state(self) -> None:
        if not self.current_record:
            return
        at_top = bool(self._pending_detail_scroll_at_top)
        self._pending_detail_scroll_at_top = None
        if at_top:
            self._set_detail_metadata_panel_expanded(
                bool(getattr(self, "detail_metadata_expanded", False)),
                animate=False,
            )
        if self.detail_header.isVisible() != bool(at_top):
            self._cover_detail_webview_resize()
        self.detail_header.setVisible(bool(at_top))
        self.detail_metadata_button.setChecked(bool(getattr(self, "detail_metadata_expanded", False)))

    def show_detail_action_menu(self) -> None:
        """在详情页更多按钮下方弹出记录操作菜单。"""
        self._sync_detail_action_menu()
        pos = self.detail_more_button.mapToGlobal(self.detail_more_button.rect().bottomLeft())
        self.detail_action_menu.popup(pos)

    def _update_detail_header(self, record: HistoryRecord) -> None:
        """刷新详情头部内容后同步头部操作状态。"""
        HistoryViewHandlers._update_detail_header(self, record)
        self.detail_header.show()
        if bool(getattr(self, "detail_metadata_expanded", False)):
            self._set_detail_metadata_panel_expanded(True, animate=False)
        self._sync_detail_action_menu()

    def _clear_missing_current_record(self, *, clear_persisted_selection: bool = True) -> None:
        """清空详情视图后同步头部操作状态。"""
        HistoryViewHandlers._clear_missing_current_record(
            self,
            clear_persisted_selection=clear_persisted_selection,
        )
        self.detail_metadata_expanded = False
        self.detail_metadata_button.setChecked(False)
        self._set_detail_metadata_panel_expanded(False, animate=False)
        self._bump_detail_revision()
        self._refresh_detail_payload()
        self._sync_detail_action_menu()

    def _set_processing_ui(self, processing: bool) -> None:
        """处理状态变化时同步详情头部菜单。"""
        ProcessingHandlers._set_processing_ui(self, processing)
        self._sync_detail_action_menu()

    def new_recording(self) -> None:
        """创建新录音入口清空当前记录后同步详情头部菜单。"""
        RecordingHandlers.new_recording(self)
        self._sync_detail_action_menu()

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

    def _restore_last_selected_record(self) -> None:
        """启动后恢复上次选中的笔记本和记录。"""
        record_key = self._last_selected_record_key_for_notebook(self.current_notebook_id)
        if not record_key:
            record_key = str(self.config.get("last_selected_record_key") or "")
        if not record_key:
            self._restore_visible_record_selection()
            return
        if self._select_record_by_key(record_key):
            return
        self._clear_persisted_record_selection(notebook_id=self.current_notebook_id, record_key=record_key)
        self._restore_visible_record_selection()

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

    def open_current_record_folder(self) -> None:
        """在系统文件管理器中打开当前历史记录文件夹。"""
        if not self.current_record:
            self._show_error("请先选择一条历史记录")
            return
        folder = self.current_record.record_dir
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
        if not self.current_record:
            self._set_status("请先选择一条历史记录")
            return
        notice_kind = "detail" if kind == "active" else kind
        if kind == "active":
            kind = self.active_result_tab
        if kind == "transcript":
            text = self.transcript_plain_text or self.history_service.read_transcript(self.current_record)
            label = "转录文字"
        elif kind == "timeline":
            text = self._timeline_display_text(self.current_record)
            label = "逐句时间轴"
        else:
            text = self._detail_summary_content(self.current_record)
            label = "总结内容"

        if not text.strip():
            message = f"{label}为空，无法复制"
            self._set_status(message)
            self._show_copy_notice(notice_kind, message)
            return
        QApplication.clipboard().setText(text)
        message = f"{label}已复制"
        self._set_status(message)
        self._show_copy_notice(notice_kind, message)

    def _show_copy_notice(self, kind: str, message: str) -> None:
        label = {
            "transcript": getattr(self, "transcript_copy_notice_label", None),
            "timeline": getattr(self, "timeline_copy_notice_label", None),
            "summary": getattr(self, "summary_copy_notice_label", None),
            "detail": getattr(self, "detail_copy_notice_label", None),
        }.get(kind)
        if label is None:
            return
        label.setText(message)
        label.show()

        def hide_if_current() -> None:
            if label.text() == message:
                label.hide()

        QTimer.singleShot(2000, hide_if_current)

    def toggle_detail_search(self) -> None:
        visible = self.detail_search_bar.isHidden()
        self.detail_search_bar.setVisible(visible)
        if visible:
            self.detail_search_input.setFocus()
            self.detail_search_input.selectAll()
            self._refresh_detail_search()
            return
        self.detail_search_query = ""
        self.detail_search_index = 0
        self.detail_search_match_count_from_webview = None
        self.detail_search_input.blockSignals(True)
        self.detail_search_input.clear()
        self.detail_search_input.blockSignals(False)
        self._set_detail_web_search("", 0)
        self._sync_detail_search_controls(0)

    def update_detail_search(self, text: str) -> None:
        self.detail_search_query = text
        self.detail_search_index = 0
        self.detail_search_match_count_from_webview = None
        self._refresh_detail_search()

    def find_detail_previous(self) -> None:
        count = self._detail_search_match_count()
        if count <= 0:
            self._sync_detail_search_controls(0)
            return
        self.detail_search_index = (self.detail_search_index - 1) % count
        self._sync_detail_search_controls(count)
        self._set_detail_web_search(self.detail_search_query, self.detail_search_index)

    def find_detail_next(self) -> None:
        count = self._detail_search_match_count()
        if count <= 0:
            self._sync_detail_search_controls(0)
            return
        self.detail_search_index = (self.detail_search_index + 1) % count
        self._sync_detail_search_controls(count)
        self._set_detail_web_search(self.detail_search_query, self.detail_search_index)

    def clear_detail_search(self) -> None:
        if self.detail_search_input.text():
            self.detail_search_input.clear()
            return
        self.update_detail_search("")

    def _sync_detail_search_from_webview(self, match_count: int, index: int) -> None:
        if not str(getattr(self, "detail_search_query", "") or ""):
            self.detail_search_match_count_from_webview = 0
            self.detail_search_index = 0
            self._sync_detail_search_controls(0)
            return
        count = max(0, int(match_count))
        self.detail_search_match_count_from_webview = count
        if count <= 0:
            self.detail_search_index = 0
        else:
            self.detail_search_index = min(max(0, int(index)), count - 1)
        self._sync_detail_search_controls(count)

    def toggle_detail_edit_mode(self) -> None:
        self.detail_edit_mode = not bool(getattr(self, "detail_edit_mode", False))
        self._apply_detail_edit_mode()

    def _refresh_detail_search(self) -> None:
        count = self._detail_search_match_count()
        if count <= 0:
            self.detail_search_index = 0
        elif self.detail_search_index >= count:
            self.detail_search_index = count - 1
        self._sync_detail_search_controls(count)
        self._set_detail_web_search(self.detail_search_query, self.detail_search_index)

    def _detail_search_match_count(self) -> int:
        query = str(getattr(self, "detail_search_query", "") or "")
        if not query:
            return 0
        detail_webview = getattr(self, "detail_webview", None)
        is_webengine_available = getattr(detail_webview, "is_webengine_available", None)
        if callable(is_webengine_available) and is_webengine_available():
            return max(0, int(getattr(self, "detail_search_match_count_from_webview", 0) or 0))
        text = self._detail_current_source_text()
        lowered_text = text.lower()
        lowered_query = query.lower()
        count = 0
        start = 0
        while lowered_query:
            index = lowered_text.find(lowered_query, start)
            if index < 0:
                break
            count += 1
            start = index + len(lowered_query)
        return count

    def _sync_detail_search_controls(self, count: int) -> None:
        if not str(getattr(self, "detail_search_query", "") or "") or count <= 0:
            self.detail_search_count_label.setText("0 / 0")
            self.detail_search_prev_button.setEnabled(False)
            self.detail_search_next_button.setEnabled(False)
            return
        self.detail_search_prev_button.setEnabled(True)
        self.detail_search_next_button.setEnabled(True)
        self.detail_search_count_label.setText(f"{self.detail_search_index + 1} / {count}")

    def _set_detail_web_search(self, query: str, index: int) -> None:
        detail_webview = getattr(self, "detail_webview", None)
        set_search_state = getattr(detail_webview, "set_search_state", None)
        if callable(set_search_state):
            set_search_state(query, index)

    def _detail_current_source_text(self) -> str:
        if not self.current_record:
            return ""
        if self.active_result_tab == "summary":
            return self._detail_summary_content(self.current_record)
        if self.active_result_tab == "timeline":
            return self._timeline_display_text(self.current_record)
        return self._detail_transcript_content(self.current_record)

    def _apply_detail_edit_mode(self) -> None:
        if not hasattr(self, "detail_edit_toggle_button"):
            return
        editable_tab = self.active_result_tab in {"transcript", "summary", "timeline"}
        enabled = bool(getattr(self, "detail_edit_mode", False)) and editable_tab
        icon_name = "视图.svg" if enabled else "编辑.svg"
        tooltip = "逐句时间轴不可编辑" if not editable_tab else "视图" if enabled else "编辑"
        icon_path = Path(__file__).resolve().parents[1] / "assets" / "svg" / icon_name
        self.detail_edit_toggle_button.setIcon(QIcon(str(icon_path)))
        self.detail_edit_toggle_button.setToolTip(tooltip)
        self.detail_edit_toggle_button.setEnabled(editable_tab)
        detail_webview = getattr(self, "detail_webview", None)
        set_edit_mode = getattr(detail_webview, "set_edit_mode", None)
        if callable(set_edit_mode):
            set_edit_mode(enabled)

    def delete_current_record(self) -> None:
        """删除当前选中的历史记录。"""
        if not self.current_record:
            self._show_error("请先选择一条历史记录")
            return
        self._delete_record(self.current_record, clear_current=True)

    def _delete_record(self, record: HistoryRecord, clear_current: bool) -> None:
        if getattr(self, "_record_has_running_task", lambda _record: False)(record):
            self._show_error("正在处理，删除前先取消任务")
            return
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
            self._clear_missing_current_record()
        if hasattr(self, "_discard_tasks_for_deleted_record"):
            self._discard_tasks_for_deleted_record(record.record_key)
        self.load_recordings()
        self._set_status(result.message)

    def _delete_records(self, records: list[HistoryRecord]) -> None:
        """批量删除历史记录，只弹出一次确认。"""
        if not records:
            return
        if any(getattr(self, "_record_has_running_task", lambda _record: False)(record) for record in records):
            self._show_error("正在处理，删除前先取消任务")
            return
        confirmed = confirm_without_icon(
            self,
            "删除历史记录",
            f"确定删除选中的 {len(records)} 条历史记录吗?\n"
            "音频文件、转录结果等都会被清理。",
        )
        if not confirmed:
            self._set_status("已取消删除")
            return

        current_key = self.current_record.record_key if self.current_record else ""
        clear_current = any(record.record_key == current_key for record in records)
        failures: list[str] = []
        deleted_count = 0
        for record in records:
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
                failures.append(f"{record.display_name}: {result.message}")
                continue
            deleted_count += 1
            log_event(
                "record.delete.completed",
                module="history",
                message="历史记录已删除",
                record_id=record.record_id,
                context={"deleted_count": len(result.deleted_paths), "skipped_count": len(result.skipped_paths)},
            )
            if hasattr(self, "_discard_tasks_for_deleted_record"):
                self._discard_tasks_for_deleted_record(record.record_key)

        if clear_current:
            self._clear_missing_current_record()
        self.load_recordings()
        if failures:
            self._show_error("部分记录删除失败：\n" + "\n".join(failures))
        else:
            self._set_status(f"已删除 {deleted_count} 条记录")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _set_app_window_title(self, record: HistoryRecord | None = None) -> None:
        if record is None:
            self.setWindowTitle("NoisNote")
            return
        self.setWindowTitle(f"{record.display_name} - NoisNote")

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
        has_task_queue_work = bool(getattr(self, "task_manager", None) and self.task_manager.has_unfinished_tasks())
        has_recording_work = bool(self.is_recording and self.recorder)
        has_remote_import_work = bool(getattr(self, "active_remote_imports", {}))
        if has_recording_work or has_remote_import_work or has_task_queue_work or self.active_workers:
            confirmed = confirm_without_icon(
                self,
                "后台任务仍在运行",
                "仍有任务正在运行或排队，退出应用会中断运行中的任务并保留排队任务。确定退出吗?",
            )
            if not confirmed:
                event.ignore()
                return
            self._closing_for_exit = True
            if has_recording_work:
                self.stop_recording()
            if hasattr(self, "prepare_remote_imports_for_close"):
                self.prepare_remote_imports_for_close()
            if hasattr(self, "prepare_task_queue_for_close"):
                self.prepare_task_queue_for_close()
        if self.recorder:
            self.recorder.cleanup()
        event.accept()
