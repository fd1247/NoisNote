"""主窗口历史列表与详情加载逻辑。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu

from ..history.service import HistoryRecord, HistoryStatus
from ..history.types import format_size


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
        selected_key = self.current_record.record_key if self.current_record else ""
        self.all_history_items = self.history_service.scan()
        self.current_items = self._filtered_history_items()
        self._render_history_list()
        if selected_key:
            still_exists = any(record.record_key == selected_key for record in self.all_history_items)
            if still_exists:
                self._sync_selected_record_in_visible_list(selected_key)
            else:
                self._clear_missing_current_record()

    def _clear_missing_current_record(self) -> None:
        """当前历史记录被外部删除时，清空右侧详情引用。"""
        if self.current_record and self.current_record.record_key == self.playback_record_id:
            self.stop_playback()
            self.playback_record_id = ""
        self.current_record = None
        self.history_tree.clearSelection()
        self._sync_history_selection(-1)
        self.detail_title_label.setText("请选择历史记录")
        self.detail_duration_label.setText("--:--")
        self.detail_size_label.setText("--")
        self.detail_time_label.setText("--")
        self.detail_status_label.setText("状态 --")
        self.detail_processing_status_label.hide()
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
        updates_enabled = self.history_tree.updatesEnabled()
        self.history_tree.setUpdatesEnabled(False)
        try:
            self._last_history_selected_index = -1
            self.history_tree.render(
                self.config.get("notebooks", []),
                self.current_items,
                self._history_subtitle_for_record,
            )
            self.empty_history_label.setVisible(not self.current_items)
        finally:
            self.history_tree.setUpdatesEnabled(updates_enabled)

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
            record.notebook_name,
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
            self._sync_selected_record_in_visible_list(self.current_record.record_key)

    def _set_history_filter(self, value: str, label: str) -> None:
        self.history_status_filter = value
        self.history_filter_button.setToolTip("筛选历史记录" if value == "all" else f"筛选：{label}")
        self.current_items = self._filtered_history_items()
        self._render_history_list()
        if self.current_record:
            self._sync_selected_record_in_visible_list(self.current_record.record_key)

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

    def _sync_selected_record_in_visible_list(self, record_key: str) -> bool:
        matched = self.history_tree.select_record(record_key)
        self._sync_history_selection(
            next((index for index, record in enumerate(self.current_items) if record.record_key == record_key), -1)
        )
        return matched

    def _select_history_item(self, item) -> None:
        if isinstance(item, str):
            self._select_record_by_key(item)
            return
        record_key = item.data(0, Qt.ItemDataRole.UserRole + 1) if item is not None else ""
        if record_key:
            self._select_record_by_key(str(record_key))

    def select_history_index(self, index: int) -> None:
        """按索引选中并加载历史记录。"""
        if index < 0 or index >= len(self.current_items):
            return
        recording = self.current_items[index]
        self._dismiss_history_notice(recording)
        self.history_tree.select_record(recording.record_key)
        self.history_tree.update_subtitles(self._history_subtitle_for_record)
        self._load_history_record(recording)
        self._sync_history_selection(index)

    def _load_history_record(self, recording: HistoryRecord) -> None:
        """加载一条历史记录到右侧内容区。"""
        self._release_timeline_resources()
        self.current_record = recording
        self.transcript_loaded_record_id = ""
        self.summary_loaded_record_id = ""
        self.timeline_loaded_record_id = ""
        self.content_stack.setCurrentWidget(self.history_page)
        self.page_title_label.setText(recording.record_dir.name)
        self._update_detail_header(recording)
        self.timeline_tab_button.setVisible(recording.has_timeline)
        self.playback_cc_button.setVisible(True)
        if recording.input_error:
            detail = recording.input_error.get("details") or recording.input_error.get("message") or recording.error_message
            self.transcript_status.setText(f"音频处理失败：{detail}")
        elif recording.status == HistoryStatus.ERROR and recording.error_message:
            self.transcript_status.setText(f"处理失败：{recording.error_message}")
        else:
            self.transcript_status.setText("已加载转录" if recording.has_transcript else "暂无转录")
        self.summary_status.setText("已加载总结" if recording.has_summary else "暂无总结")
        self.timeline_status.setText("已加载逐句时间轴" if recording.has_timeline else "暂无逐句时间轴")
        if self.active_result_tab != "transcript":
            self._set_result_tab("transcript")
        else:
            self._ensure_transcript_loaded()
        self.manual_summary_button.setVisible(recording.has_transcript and not recording.has_summary)
        self._update_retry_transcription_button(recording)
        self._set_playback_source(recording)
        self._sync_detail_processing_view()
        self._set_status("")

    def _ensure_active_result_loaded(self) -> None:
        if not self.current_record:
            return
        if self.active_result_tab == "summary":
            self._ensure_summary_loaded()
        elif self.active_result_tab == "timeline":
            self._ensure_timeline_loaded()
        else:
            self._ensure_transcript_loaded()

    def _ensure_transcript_loaded(self) -> None:
        if not self.current_record:
            return
        record_key = self.current_record.record_key
        if self.transcript_loaded_record_id == record_key:
            return
        self._set_transcript_text(self.history_service.read_transcript(self.current_record))
        self.transcript_loaded_record_id = record_key

    def _ensure_summary_loaded(self) -> None:
        if not self.current_record:
            return
        record_key = self.current_record.record_key
        if self.summary_loaded_record_id == record_key:
            return
        self._set_summary_text(self.history_service.read_summary(self.current_record))
        self.summary_loaded_record_id = record_key

    def _ensure_timeline_loaded(self) -> None:
        if not self.current_record:
            return
        record_key = self.current_record.record_key
        if self.timeline_loaded_record_id == record_key:
            return
        items = self.history_service.read_timeline(self.current_record) if self.current_record.has_timeline else []
        self._set_timeline_items(items)
        self.timeline_loaded_record_id = record_key

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

    def _select_record_by_key(self, record_key: str) -> bool:
        for index, record in enumerate(self.current_items):
            if record.record_key == record_key:
                self.select_history_index(index)
                return True
        if any(record.record_key == record_key for record in self.all_history_items):
            self._clear_history_filters()
            for index, record in enumerate(self.current_items):
                if record.record_key == record_key:
                    self.select_history_index(index)
                    return True
        return False

    def _sync_history_selection(self, selected_index: int) -> None:
        self._last_history_selected_index = selected_index

    def _sync_history_row(self, row: int, selected_index: int) -> None:
        return

    def _record_index_by_key(self, record_key: str) -> int:
        for index, record in enumerate(self.current_items):
            if record.record_key == record_key:
                return index
        return -1

    def _rename_record_by_key(self, record_key: str) -> None:
        index = self._record_index_by_key(record_key)
        if index >= 0:
            self.rename_history_record(index)

    def _open_record_folder_by_key(self, record_key: str) -> None:
        index = self._record_index_by_key(record_key)
        if index >= 0:
            self.open_history_record_folder(index)

    def _delete_record_by_key(self, record_key: str) -> None:
        index = self._record_index_by_key(record_key)
        if index >= 0:
            self.delete_history_record(index)

    def _move_record_to_notebook(self, record_key: str, target_notebook_id: str) -> None:
        record = next((item for item in self.all_history_items if item.record_key == record_key), None)
        if not record:
            return
        result = self.history_service.move_record_to_notebook(record, target_notebook_id)
        if not result.success:
            self._show_error(result.message)
            return
        self.load_recordings()
        moved = next((item for item in self.all_history_items if item.record_dir == result.target_dir), None)
        if moved is not None:
            self._select_record_by_key(moved.record_key)
        self._set_status(result.message)
