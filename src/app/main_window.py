"""PySide6 主窗口。"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..audio import AudioRecorder
from .config import ensure_dirs, get_config, get_output_dir, save_config
from ..handlers.media_import import ImportHandlers
from ..handlers.processing import ProcessingHandlers
from ..handlers.recording import RecordingHandlers
from ..handlers.settings import SettingsHandlers
from ..handlers.summary import SummaryHandlers
from ..handlers.transcription import TranscriptionHandlers
from ..ui.widgets.dialogs import confirm_without_icon
from ..history.service import HistoryRecord, HistoryService, HistoryStatus
from ..model_registry.downloader import ModelDownloadManager
from ..ui.settings import SettingsPanel
from ..ui.content import build_history_page
from ..ui.widgets.history_item import HistoryListItemWidget
from ..ui.sidebar import build_history_sidebar, build_settings_sidebar
from ..ui.icons import make_action_icon, make_app_icon
from ..ui.recording import build_recording_page
from ..ui.result import set_result_tab, set_summary_text, set_transcript_text
from ..ui.widgets.update_dialog import UpdateDialog
from ..utils.logging import log_event, record_context
from .version import APP_VERSION
from .update import check_for_update_async


class MainWindow(ImportHandlers, RecordingHandlers, ProcessingHandlers, TranscriptionHandlers, SummaryHandlers, SettingsHandlers, QMainWindow):
    """NoisNote主窗口。"""

    def __init__(self):
        super().__init__()
        self.config = get_config()
        ensure_dirs(self.config)
        output_dir = get_output_dir(self.config)
        self.history_service = HistoryService(str(output_dir))
        self.model_download_manager = ModelDownloadManager(self.config, self)
        self.recorder: AudioRecorder | None = None
        self.current_record: HistoryRecord | None = None
        self.processing_record: HistoryRecord | None = None
        self.current_items: list[HistoryRecord] = []
        self.active_workers: list[object] = []
        self.is_recording = False
        self.is_processing = False
        self.processing_source: str | None = None
        self.previous_content_widget: QWidget | None = None
        self.processing_started_at: dict[str, float] = {}
        self.latest_processing_messages: dict[str, str] = {}
        self.latest_transcription_percent: int | None = None
        self.silence_started_at: float | None = None
        self.active_result_tab = "transcript"
        self.summary_markdown_text = ""
        self.active_task_ids: dict[str, str] = {}

        self.setWindowTitle("NoisNote")
        self.setWindowIcon(make_app_icon())
        self.resize(1100, 760)
        self.setMinimumSize(880, 620)
        self.setAcceptDrops(True)

        self.record_timer = QTimer(self)
        self.record_timer.setInterval(120)
        self.record_timer.timeout.connect(self._refresh_recording_state)

        self._build_ui()
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

        # 启动时检查版本更新
        self._update_worker = check_for_update_async(APP_VERSION, self._on_update_checked)

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
            self._show_active_task,
            self._select_history_item,
            self.show_settings,
        )
        self.new_recording_sidebar_button = controls.new_recording_button
        self.import_audio_sidebar_button = controls.import_audio_button
        self.active_recording_button = controls.active_recording_button
        self.history_list = controls.history_list
        self.empty_history_label = controls.empty_history_label
        self.settings_button = controls.settings_button
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
        self.settings_shortcuts_button = controls.shortcuts_button
        self.settings_nav_buttons = [
            self.settings_general_button,
            self.settings_models_button,
            self.settings_shortcuts_button,
        ]
        return sidebar

    def _build_main_area(self) -> QWidget:
        container = QFrame()
        container.setObjectName("MainArea")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(16)

        header = QHBoxLayout()
        self.page_title_label = QLabel("")
        self.page_title_label.setObjectName("Title")
        self.status_label = QLabel()
        self.status_label.setObjectName("Muted")
        header.addWidget(self.page_title_label)
        header.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        header.addWidget(self.status_label)

        self.content_stack = QStackedWidget()
        self.recording_page = self._build_recording_page()
        self.history_page = self._build_history_page()
        self.settings_panel = SettingsPanel(self.config, self.model_download_manager, self)
        self.settings_panel.saved.connect(self._apply_settings_config)
        self.settings_panel.cancelled.connect(self.hide_settings)
        self.content_stack.addWidget(self.recording_page)
        self.content_stack.addWidget(self.history_page)
        self.content_stack.addWidget(self.settings_panel)

        layout.addLayout(header)
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
            self._set_result_tab,
            self.manual_summarize,
            self.retry_transcription,
            self.copy_panel_text,
        )
        self.result_stack = controls.result_stack
        self.transcript_tab_button = controls.transcript_tab_button
        self.summary_tab_button = controls.summary_tab_button
        self.transcript_status = controls.transcript_status
        self.transcript_progress = controls.transcript_progress
        self.transcript_text = controls.transcript_text
        self.transcript_copy_button = controls.transcript_copy_button
        self.retry_transcription_button = controls.retry_transcription_button
        self.summary_status = controls.summary_status
        self.summary_progress = controls.summary_progress
        self.summary_text = controls.summary_text
        self.summary_copy_button = controls.summary_copy_button
        self.manual_summary_button = controls.manual_summary_button
        self._set_result_tab("transcript")
        return page

    def _set_transcript_text(self, text: str) -> None:
        """写入转录文本，并同步当前页复制按钮。"""
        set_transcript_text(self, text)

    def _set_result_tab(self, kind: str) -> None:
        """切换详情结果区标签，并保留用户的当前选择。"""
        set_result_tab(self, kind)

    def _set_summary_text(self, summary: str) -> None:
        """以 Markdown 方式展示总结，同时保留原文用于复制和导出。"""
        set_summary_text(self, summary)

    def _new_task_id(self, prefix: str) -> str:
        """生成一次后台任务的轻量追踪 ID。"""
        return f"{prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    def _import_demo_audio_if_empty(self) -> None:
        """历史记录为空时导入内置测试音频（复制到用户数据目录）。"""
        if self.current_items or self.config.get("demo_audio_imported"):
            return
        demo_audio = self._resolve_demo_audio_path()
        if not demo_audio or not demo_audio.exists():
            return
        try:
            import shutil
            import tempfile
            # 复制到临时目录，再由 adopt_audio_file 移入记录目录
            tmp_dir = Path(tempfile.mkdtemp())
            tmp_file = tmp_dir / demo_audio.name
            shutil.copy2(demo_audio, tmp_file)
            record = self.history_service.adopt_audio_file(tmp_file)
            self.current_record = record
            self.load_recordings()
            self._select_record_by_id(record.record_id)
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
        dev_candidate = Path(__file__).resolve().parent / "assets" / "测试音频.mp3"
        if dev_candidate.exists():
            return dev_candidate
        return None

    def load_recordings(self) -> None:
        self.current_items = self.history_service.scan()
        self.history_list.clear()
        for index, item in enumerate(self.current_items):
            list_item = QListWidgetItem()
            list_item.setToolTip(str(item.record_dir if item.layout == "folder" else item.audio_path))
            list_item.setData(Qt.UserRole, index)
            self.history_list.addItem(list_item)
            widget = HistoryListItemWidget(item, index, self)
            list_item.setSizeHint(widget.sizeHint())
            self.history_list.setItemWidget(list_item, widget)
        self.empty_history_label.setVisible(not self.current_items)

    def _select_history_item(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.UserRole)
        if index is None:
            return
        self.select_history_index(index)

    def select_history_index(self, index: int) -> None:
        """按索引选中并加载历史记录。"""
        if index < 0 or index >= len(self.current_items):
            return
        self.history_list.setCurrentRow(index)
        self._sync_history_selection(index)
        recording = self.current_items[index]
        self._load_history_record(recording)

    def _load_history_record(self, recording: HistoryRecord) -> None:
        """加载一条历史记录到右侧内容区。"""
        self.current_record = recording
        self.content_stack.setCurrentWidget(self.history_page)
        self.page_title_label.setText(recording.record_dir.name)
        self._set_transcript_text(self.history_service.read_transcript(recording))
        self._set_summary_text(self.history_service.read_summary(recording))
        if recording.input_error:
            self.transcript_status.setText(f"音频处理失败：{recording.input_error.get('message') or recording.error_message}")
        elif recording.status == HistoryStatus.ERROR and recording.error_message:
            self.transcript_status.setText(f"处理失败：{recording.error_message}")
        else:
            self.transcript_status.setText("已加载转录" if recording.has_transcript else "暂无转录")
        self.summary_status.setText("已加载总结" if recording.has_summary else "暂无总结")
        self.manual_summary_button.setVisible(recording.has_transcript and not recording.has_summary)
        self._update_retry_transcription_button(recording)
        self._sync_detail_processing_view()
        self._set_status("")

    def rename_history_record(self, index: int) -> None:
        """重命名历史记录。"""
        if index < 0 or index >= len(self.current_items):
            return
        record = self.current_items[index]
        new_name, accepted = QInputDialog.getText(
            self,
            "重命名",
            "记录名称：",
            text=record.record_id,
        )
        if not accepted:
            return
        try:
            renamed = self.history_service.rename_record(record, new_name)
        except Exception as exc:
            self._show_error(f"重命名失败：{exc}")
            return

        self.current_record = renamed
        self.load_recordings()
        self._select_record_by_id(renamed.record_id)
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
        self.current_record = self.current_items[index]
        self.delete_current_record()

    def _select_record_by_id(self, record_id: str) -> bool:
        for index, record in enumerate(self.current_items):
            if record.record_id == record_id:
                self.select_history_index(index)
                return True
        return False

    def _sync_history_selection(self, selected_index: int) -> None:
        for row in range(self.history_list.count()):
            item = self.history_list.item(row)
            widget = self.history_list.itemWidget(item)
            if isinstance(widget, HistoryListItemWidget):
                widget.set_selected(row == selected_index)

    def copy_panel_text(self, kind: str) -> None:
        """复制转录或总结文本到系统剪贴板。"""
        if kind == "transcript":
            text = self.transcript_text.toPlainText()
            label = "转录文字"
        else:
            text = self.summary_markdown_text
            label = "总结内容"

        if not text.strip():
            self._set_status(f"{label}为空，无法复制")
            return
        QApplication.clipboard().setText(text)
        self._set_status(f"已复制{label}")

    def export_markdown(self) -> None:
        if not self.current_record:
            self._show_error("请先选择或生成一条录音")
            return

        transcript = self.transcript_text.toPlainText().strip() or "（无转录文字）"
        summary = self.summary_markdown_text.strip() or "（无总结）"
        content = (
            f"# 录音记录 - {self.current_record.display_name}\n\n"
            f"## 转录文字\n\n{transcript}\n\n"
            f"## 总结\n\n{summary}\n"
        )
        markdown_file = self.history_service.save_markdown(self.current_record, content)
        self.current_record = self.history_service.refresh_metadata(self.current_record)
        self._set_status(f"已导出：{markdown_file.name}")
        self.load_recordings()

    def delete_current_record(self) -> None:
        """删除当前选中的历史记录。"""
        if not self.current_record:
            self._show_error("请先选择一条历史记录")
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

        record = self.current_record
        log_event(
            "record.delete.started",
            module="history",
            message="开始删除历史记录",
            record_id=record.record_id,
            context={"record": record_context(record)},
        )
        result = self.history_service.delete_record(self.current_record)
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

        self.new_recording()
        self.load_recordings()
        self._set_status(result.message)

    def _show_processing_record(self) -> None:
        """在处理进行中返回当前任务对应的详情页。"""
        if not self.processing_record:
            self.show_recording_page()
            return
        if self._select_record_by_id(self.processing_record.record_id):
            return
        self.load_recordings()
        if not self._select_record_by_id(self.processing_record.record_id):
            self.show_recording_page()

    def _show_active_task(self) -> None:
        """跳转到当前正在进行的任务。"""
        if self.is_processing:
            self._show_processing_record()
            return
        if self.is_recording:
            self.show_recording_page()

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _show_error(self, message: str) -> None:
        self._set_status(message)
        QMessageBox.warning(self, "提示", message)

    def _display_time(self, path: Path) -> str:
        try:
            return datetime.strptime(path.stem, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return path.stem

    def closeEvent(self, event: QCloseEvent) -> None:
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
        # 等待版本检查线程结束，避免 QThread 被销毁时仍在运行
        if self._update_worker and self._update_worker.isRunning():
            self._update_worker.quit()
            self._update_worker.wait(2000)
        event.accept()

    def _on_update_checked(self, update_info) -> None:
        """版本检查完成回调"""
        if update_info.has_update:
            log_event(
                "app.update.available",
                module="ui",
                message="发现新版本",
                context={
                    "current_version": update_info.current_version,
                    "latest_version": update_info.latest_version,
                },
            )
            UpdateDialog.show_update_dialog(self, update_info)
        else:
            log_event(
                "app.update.none",
                module="ui",
                message="已是最新版本",
                context={"current_version": update_info.current_version},
            )
