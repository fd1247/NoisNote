"""主窗口历史列表与详情加载逻辑。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QListWidgetItem, QMenu

from ..history.service import HistoryRecord, HistoryStatus
from ..history.types import format_size
from ..ui.widgets.history_item import HistoryListItemWidget


class HistoryViewHandlers:
    """历史记录过滤、选择和详情加载。"""

    def _build_history_filter_menu(self) -> QMenu:
        menu = QMenu(self)
        group = QActionGroup(menu)
        group.setExclusive(True)
        options = [
            ("all", "全部"),
            (HistoryStatus.AUDIO_ONLY.value, "仅录音"),
            (HistoryStatus.TRANSCRIBED.value, "已转录"),
            (HistoryStatus.SUMMARIZED.value, "已总结"),
            (HistoryStatus.EXPORTED.value, "已导出"),
            (HistoryStatus.ERROR.value, "异常"),
            (HistoryStatus.MISSING_AUDIO.value, "缺少音频"),
        ]
        for value, label in options:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setData(value)
            action.setChecked(value == self.history_status_filter)
            action.triggered.connect(lambda checked=False, key=value, text=label: self._set_history_filter(key, text))
            group.addAction(action)
            menu.addAction(action)
        return menu

    def load_recordings(self) -> None:
        selected_id = self.current_record.record_id if self.current_record else ""
        self.all_history_items = self.history_service.scan()
        self.current_items = self._filtered_history_items()
        self._render_history_list()
        if selected_id:
            still_exists = any(record.record_id == selected_id for record in self.all_history_items)
            if still_exists:
                self._sync_selected_record_in_visible_list(selected_id)
            else:
                self._clear_missing_current_record()

    def _clear_missing_current_record(self) -> None:
        """当前历史记录被外部删除时，清空右侧详情引用。"""
        if self.current_record and self.current_record.record_id == self.playback_record_id:
            self.stop_playback()
            self.playback_record_id = ""
        self.current_record = None
        self.history_list.setCurrentRow(-1)
        self._sync_history_selection(-1)
        self.detail_title_label.setText("请选择历史记录")
        self.detail_duration_label.setText("--:--")
        self.detail_size_label.setText("--")
        self.detail_time_label.setText("--")
        self.detail_status_label.setText("状态 --")
        self._set_transcript_text("")
        self._set_timeline_items([])
        self.timeline_tab_button.hide()
        self._set_summary_text("")
        self.transcript_status.setText("等待内容")
        self.timeline_status.setText("等待内容")
        self.summary_status.setText("等待内容")
        self.manual_summary_button.hide()
        self.retry_transcription_button.hide()

    def _render_history_list(self) -> None:
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

    def _filtered_history_items(self) -> list[HistoryRecord]:
        query = self.history_search_text.strip().lower()
        items: list[HistoryRecord] = []
        for record in self.all_history_items:
            if self.history_status_filter != "all" and record.status.value != self.history_status_filter:
                continue
            if query and query not in self._history_search_blob(record):
                continue
            items.append(record)
        return items

    def _history_search_blob(self, record: HistoryRecord) -> str:
        parts = [
            record.display_name,
            record.record_id,
            record.status_text,
            record.audio_path.name,
        ]
        if record.original_file_path:
            parts.append(record.original_file_path.name)
        return " ".join(parts).lower()

    def _on_history_search_changed(self, text: str) -> None:
        self.history_search_text = text
        self.current_items = self._filtered_history_items()
        self._render_history_list()
        if self.current_record:
            self._sync_selected_record_in_visible_list(self.current_record.record_id)

    def _set_history_filter(self, value: str, label: str) -> None:
        self.history_status_filter = value
        self.history_filter_button.setToolTip("筛选历史记录" if value == "all" else f"筛选：{label}")
        self.current_items = self._filtered_history_items()
        self._render_history_list()
        if self.current_record:
            self._sync_selected_record_in_visible_list(self.current_record.record_id)

    def _clear_history_filters(self) -> None:
        self.history_search_text = ""
        if hasattr(self, "history_search"):
            self.history_search.blockSignals(True)
            self.history_search.clear()
            self.history_search.blockSignals(False)
        self.history_status_filter = "all"
        self.history_filter_button.setToolTip("筛选历史记录")
        menu = self.history_filter_button.menu()
        if menu:
            for action in menu.actions():
                action.setChecked(action.data() == "all")
        self.current_items = list(self.all_history_items)
        self._render_history_list()

    def _sync_selected_record_in_visible_list(self, record_id: str) -> bool:
        for index, record in enumerate(self.current_items):
            if record.record_id == record_id:
                self.history_list.setCurrentRow(index)
                self._sync_history_selection(index)
                return True
        self.history_list.setCurrentRow(-1)
        self._sync_history_selection(-1)
        return False

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
        self._update_detail_header(recording)
        self._set_transcript_text(self.history_service.read_transcript(recording))
        self._set_timeline_items(self.history_service.read_timeline(recording))
        self.timeline_tab_button.setVisible(recording.has_timeline)
        self.playback_cc_button.setVisible(True)
        self._set_summary_text(self.history_service.read_summary(recording))
        if recording.input_error:
            self.transcript_status.setText(f"音频处理失败：{recording.input_error.get('message') or recording.error_message}")
        elif recording.status == HistoryStatus.ERROR and recording.error_message:
            self.transcript_status.setText(f"处理失败：{recording.error_message}")
        else:
            self.transcript_status.setText("已加载转录" if recording.has_transcript else "暂无转录")
        self.summary_status.setText("已加载总结" if recording.has_summary else "暂无总结")
        self.timeline_status.setText("已加载逐句时间轴" if recording.has_timeline else "暂无逐句时间轴")
        if not recording.has_timeline and self.active_result_tab == "timeline":
            self._set_result_tab("transcript")
        self.manual_summary_button.setVisible(recording.has_transcript and not recording.has_summary)
        self._update_retry_transcription_button(recording)
        self._set_playback_source(recording)
        self._sync_detail_processing_view()
        self._set_status("")

    def _update_detail_header(self, record: HistoryRecord) -> None:
        self.detail_title_label.setText(record.display_name)
        self.detail_duration_label.setText(record.duration_text)
        self.detail_size_label.setText(format_size(record.total_size_bytes))
        self.detail_time_label.setText(record.created_at.strftime("%Y-%m-%d %H:%M"))
        self.detail_status_label.setText(record.status_text)

    def _select_record_by_id(self, record_id: str) -> bool:
        for index, record in enumerate(self.current_items):
            if record.record_id == record_id:
                self.select_history_index(index)
                return True
        if any(record.record_id == record_id for record in self.all_history_items):
            self._clear_history_filters()
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
