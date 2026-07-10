"""主窗口历史列表与详情加载逻辑。"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from PySide6.QtCore import Qt

from ..app.config import get_notebooks, normalize_notebooks, save_config
from ..history.service import HistoryRecord
from ..history.types import format_size
from ..ui.dialogs.notebook import ManageNotebooksDialog, NewNotebookDialog


class HistoryViewHandlers:
    """历史记录选择和详情加载。"""

    def load_recordings(self) -> None:
        active_notebook_id = self._active_notebook_id()
        selected_key = (
            self.current_record.record_key
            if self.current_record and self.current_record.notebook_id == active_notebook_id
            else ""
        )
        self._refresh_notebook_selector()
        self.all_history_items = self.history_service.scan()
        self.current_items = self._filtered_history_items()
        self._render_history_list()
        self._restore_visible_record_selection(preferred_key=selected_key)

    def _active_notebook_id(self) -> str:
        return str(getattr(self, "current_notebook_id", "") or self.config.get("active_notebook_id") or "default")

    def _clear_missing_current_record(self, *, clear_persisted_selection: bool = True) -> None:
        """当前历史记录被外部删除时，清空右侧详情引用。"""
        missing_record = self.current_record
        if self.current_record and self.current_record.record_key == self.playback_record_id:
            self.stop_playback()
            self.playback_record_id = ""
        self.current_record = None
        if clear_persisted_selection:
            self._clear_persisted_record_selection(record=missing_record)
        self._set_app_window_title()
        self.history_tree.clearSelection()
        self._sync_history_selection(-1)
        self.detail_title_label.setText("请选择历史记录")
        self.detail_duration_label.setText("--:--")
        self.detail_size_label.setText("--")
        self.detail_time_label.setText("--")
        self.detail_processing_status_label.hide()
        self._set_transcript_text("")
        self._set_timeline_items([])
        self._set_summary_text("")
        self.transcript_status.setText("等待内容")
        self.timeline_status.setText("等待内容")
        self.summary_status.setText("等待内容")
        if hasattr(self, "_bump_detail_revision"):
            self._bump_detail_revision()
        if hasattr(self, "_refresh_detail_payload"):
            self._refresh_detail_payload()

    def _last_selected_record_key_for_notebook(self, notebook_id: str) -> str:
        selected_keys = self.config.get("last_selected_record_keys")
        if isinstance(selected_keys, dict):
            record_key = str(selected_keys.get(notebook_id) or "").strip()
            if record_key:
                return record_key
        legacy_key = str(self.config.get("last_selected_record_key") or "").strip()
        if legacy_key.startswith(f"{notebook_id}:"):
            return legacy_key
        return ""

    def _restore_visible_record_selection(self, *, preferred_key: str = "") -> bool:
        active_notebook_id = self._active_notebook_id()
        candidate_keys = [
            key
            for key in (
                preferred_key,
                self._last_selected_record_key_for_notebook(active_notebook_id),
            )
            if key
        ]
        for record_key in dict.fromkeys(candidate_keys):
            for index, record in enumerate(self.current_items):
                if record.record_key == record_key:
                    if self.current_record and self.current_record.record_key == record_key:
                        self._sync_selected_record_in_visible_list(record_key)
                        return True
                    self.select_history_index(index)
                    return True
            self._clear_persisted_record_selection(notebook_id=active_notebook_id, record_key=record_key)
        if self.current_items:
            self.select_history_index(0)
            return True
        self._clear_missing_current_record(clear_persisted_selection=False)
        self._clear_persisted_record_selection(notebook_id=active_notebook_id)
        return False

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
        finally:
            self.history_tree.setUpdatesEnabled(updates_enabled)

    def _filtered_history_items(self) -> list[HistoryRecord]:
        notebook_id = str(getattr(self, "current_notebook_id", "") or self.config.get("active_notebook_id") or "default")
        items: list[HistoryRecord] = []
        for record in self.all_history_items:
            if notebook_id and record.notebook_id != notebook_id:
                continue
            items.append(record)
        return items

    def _refresh_notebook_selector(self) -> None:
        """同步主侧栏的笔记本下拉框。"""
        if not hasattr(self, "notebook_selector"):
            return
        notebooks = get_notebooks(self.config)
        current_id = str(getattr(self, "current_notebook_id", "") or self.config.get("active_notebook_id") or "default")
        if not any(str(item.get("id") or "") == current_id for item in notebooks):
            current_id = str(notebooks[0].get("id") or "default")
            self.current_notebook_id = current_id
            self.config["active_notebook_id"] = current_id

        self.notebook_selector.blockSignals(True)
        try:
            self.notebook_selector.clear()
            for notebook in notebooks:
                notebook_id = str(notebook.get("id") or "")
                self.notebook_selector.addItem(str(notebook.get("name") or "笔记本"), notebook_id)
            index = self.notebook_selector.findData(current_id)
            self.notebook_selector.setCurrentIndex(max(index, 0))
        finally:
            self.notebook_selector.blockSignals(False)

    def _on_notebook_selection_changed(self, index: int) -> None:
        """切换当前笔记本并刷新可见记录。"""
        if index < 0:
            return
        notebook_id = str(self.notebook_selector.itemData(index) or "")
        if not notebook_id:
            return
        self._set_current_notebook(notebook_id, persist=True)

    def _set_current_notebook(self, notebook_id: str, *, persist: bool) -> None:
        """设置当前笔记本并同步历史服务。"""
        if notebook_id == self.current_notebook_id and self.history_service.active_notebook_id == notebook_id:
            return
        self.current_notebook_id = notebook_id
        self.config["active_notebook_id"] = notebook_id
        if persist:
            save_config(self.config)
        self._refresh_notebook_selector()
        self.history_service = self.history_service.from_notebooks(
            get_notebooks(self.config),
            active_notebook_id=notebook_id,
        )
        if self.recorder:
            self.recorder.set_output_dir(str(self.history_service.recordings_dir))
        self.all_history_items = self.history_service.scan()
        self.current_items = self._filtered_history_items()
        self._render_history_list()
        preferred_key = (
            self.current_record.record_key
            if self.current_record and self.current_record.notebook_id == notebook_id
            else ""
        )
        self._restore_visible_record_selection(preferred_key=preferred_key)

    def show_new_notebook_dialog(self) -> None:
        """显示新建笔记本窗口，创建成功后切换到新笔记本。"""
        dialog = NewNotebookDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        name, path = dialog.values()
        if not name:
            self._show_error("笔记本名称不能为空")
            return
        path_text = str(path).strip()
        if not path_text or path_text == ".":
            self._show_error("请选择笔记本根文件夹")
            return
        if self._notebook_path_exists(path):
            self._show_error("这个目录已经在笔记本列表中")
            return
        notebook_id = f"notebook-{uuid.uuid4().hex[:8]}"
        path.mkdir(parents=True, exist_ok=True)
        notebooks = get_notebooks(self.config)
        notebooks.append(
            {
                "id": notebook_id,
                "name": name,
                "path": str(path),
                "is_default": False,
            }
        )
        self.config["notebooks"] = notebooks
        self.config["active_notebook_id"] = notebook_id
        normalize_notebooks(self.config)
        save_config(self.config)
        self._set_current_notebook(notebook_id, persist=False)
        self._set_status("笔记本已新建")

    def show_manage_notebooks_dialog(self) -> None:
        """显示笔记本管理窗口，保存名称修改。"""
        dialog = ManageNotebooksDialog(get_notebooks(self.config), self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        updated = dialog.notebooks()
        for item in updated:
            if not str(item.get("name") or "").strip():
                self._show_error("笔记本名称不能为空")
                return
        active_id = str(self.config.get("active_notebook_id") or self.current_notebook_id or "default")
        self.config["notebooks"] = updated
        self.config["active_notebook_id"] = active_id
        normalize_notebooks(self.config)
        save_config(self.config)
        self.history_service = self.history_service.from_notebooks(
            get_notebooks(self.config),
            active_notebook_id=active_id,
        )
        self._refresh_notebook_selector()
        self.load_recordings()
        self._set_status("笔记本已更新")

    def _notebook_path_exists(self, path: Path) -> bool:
        target = os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))
        for item in get_notebooks(self.config):
            existing = os.path.normcase(os.path.abspath(os.path.expanduser(str(item.get("path") or ""))))
            if existing == target:
                return True
        return False

    def _sync_selected_record_in_visible_list(self, record_key: str) -> bool:
        matched = self.history_tree.select_record(record_key)
        self._sync_history_selection(
            next((index for index, record in enumerate(self.current_items) if record.record_key == record_key), -1)
        )
        return matched

    def _select_history_item(self, item) -> None:
        if isinstance(item, str):
            self._load_visible_record_by_key(item)
            return
        record_key = item.data(0, Qt.ItemDataRole.UserRole + 1) if item is not None else ""
        if record_key:
            self._load_visible_record_by_key(str(record_key))

    def _load_visible_record_by_key(self, record_key: str) -> bool:
        """加载当前可见记录详情，保留树控件已经形成的多选状态。"""
        for index, record in enumerate(self.current_items):
            if record.record_key == record_key:
                self._dismiss_history_notice(record)
                self.history_tree.update_subtitles(self._history_subtitle_for_record)
                self._load_history_record(record)
                self._sync_history_selection(index)
                return True
        return self._select_record_by_key(record_key)

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
        self._persist_last_selected_record(recording)
        self.transcript_loaded_record_id = ""
        self.summary_loaded_record_id = ""
        self.timeline_loaded_record_id = ""
        self.content_stack.setCurrentWidget(self.history_page)
        self.page_title_label.setText(recording.record_dir.name)
        self._set_app_window_title(recording)
        self._update_detail_header(recording)
        self.playback_cc_button.setVisible(True)
        if hasattr(self, "_bump_detail_revision"):
            self._bump_detail_revision()
        if recording.input_error:
            detail = recording.input_error.get("details") or recording.input_error.get("message") or _last_error_message(recording)
            self.transcript_status.setText(f"音频处理失败：{detail}")
        elif _last_error_message(recording):
            self.transcript_status.setText(f"处理失败：{_last_error_message(recording)}")
        else:
            self.transcript_status.setText("已加载转录" if recording.has_transcript else "")
        self.summary_status.setText("已加载总结" if recording.has_summary else "")
        self.timeline_status.setText("已加载逐句时间轴" if recording.has_timeline else "")
        if hasattr(self, "timeline_tab_button"):
            self.timeline_tab_button.setVisible(recording.has_timeline)
        if self.active_result_tab != "transcript":
            self._set_result_tab("transcript")
        else:
            self._ensure_transcript_loaded()
        self._set_playback_source(recording)
        self._sync_detail_processing_view()
        if hasattr(self, "_refresh_detail_payload"):
            self._refresh_detail_payload()
        if hasattr(self, "_sync_detail_action_menu"):
            self._sync_detail_action_menu()
        self._set_status("")

    def _persist_last_selected_record(self, record: HistoryRecord) -> None:
        """保存最后一次选中的笔记本和记录，用于下次启动恢复。"""
        changed = False
        selected_keys = self.config.get("last_selected_record_keys")
        if not isinstance(selected_keys, dict):
            selected_keys = {}
            self.config["last_selected_record_keys"] = selected_keys
            changed = True
        if selected_keys.get(record.notebook_id) != record.record_key:
            selected_keys[record.notebook_id] = record.record_key
            changed = True
        if self.config.get("last_selected_record_key") != record.record_key:
            self.config["last_selected_record_key"] = record.record_key
            changed = True
        if self.config.get("active_notebook_id") != record.notebook_id:
            self.config["active_notebook_id"] = record.notebook_id
            self.current_notebook_id = record.notebook_id
            changed = True
        if changed:
            save_config(self.config)

    def _clear_persisted_record_selection(
        self,
        *,
        record: HistoryRecord | None = None,
        notebook_id: str = "",
        record_key: str = "",
    ) -> None:
        target_notebook_id = notebook_id or (record.notebook_id if record else "")
        target_record_key = record_key or (record.record_key if record else "")
        changed = False
        selected_keys = self.config.get("last_selected_record_keys")
        if isinstance(selected_keys, dict) and target_notebook_id:
            existing_key = str(selected_keys.get(target_notebook_id) or "")
            if existing_key and (not target_record_key or existing_key == target_record_key):
                selected_keys.pop(target_notebook_id, None)
                changed = True
        legacy_key = str(self.config.get("last_selected_record_key") or "")
        if legacy_key and (
            (target_record_key and legacy_key == target_record_key)
            or (target_notebook_id and legacy_key.startswith(f"{target_notebook_id}:"))
        ):
            self.config["last_selected_record_key"] = ""
            changed = True
        if changed:
            save_config(self.config)

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
        self._set_detail_title(record.display_name)
        self.detail_duration_label.setText(record.duration_text)
        self.detail_size_label.setText(format_size(record.total_size_bytes))
        self.detail_time_label.setText(record.created_at.strftime("%Y-%m-%d %H:%M"))

    def _set_detail_title(self, title: str) -> None:
        """设置详情标题，超长记录名用省略号避免撑宽布局。"""
        max_width = 520
        self.detail_title_label.setMaximumWidth(max_width)
        self.detail_title_label.setToolTip(title)
        elided = self.detail_title_label.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, max_width)
        self.detail_title_label.setText(elided)

    def _select_record_by_id(self, record_id: str) -> bool:
        for index, record in enumerate(self.current_items):
            if record.record_id == record_id:
                self.select_history_index(index)
                return True
        target = next((record for record in self.all_history_items if record.record_id == record_id), None)
        if target is not None:
            if target.notebook_id != self.current_notebook_id:
                self._set_current_notebook(target.notebook_id, persist=True)
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
        target = next((record for record in self.all_history_items if record.record_key == record_key), None)
        if target is not None:
            if target.notebook_id != self.current_notebook_id:
                self._set_current_notebook(target.notebook_id, persist=True)
            for index, record in enumerate(self.current_items):
                if record.record_key == record_key:
                    self.select_history_index(index)
                    return True
        return False

    def _sync_history_selection(self, selected_index: int) -> None:
        self._last_history_selected_index = selected_index

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

    def _delete_records_by_keys(self, record_keys: list[str]) -> None:
        records = self._records_for_keys(record_keys)
        if records:
            self._delete_records(records)

    def _move_records_to_notebook(self, record_keys: list[str], target_notebook_id: str) -> None:
        records = self._records_for_keys(record_keys)
        if not records:
            return
        failures: list[str] = []
        moved_keys: set[str] = set()
        for record in records:
            result = self.history_service.move_record_to_notebook(record, target_notebook_id)
            if result.success:
                moved_keys.add(record.record_key)
            else:
                failures.append(f"{record.display_name}: {result.message}")
        self.load_recordings()
        if self.current_record and self.current_record.record_key in moved_keys:
            self._clear_missing_current_record()
        if failures:
            self._show_error("部分记录移动失败：\n" + "\n".join(failures))
            return
        self._set_status(f"已移动 {len(moved_keys)} 条记录")

    def _records_for_keys(self, record_keys: list[str]) -> list[HistoryRecord]:
        ordered_keys = {str(key) for key in record_keys if key}
        return [record for record in self.all_history_items if record.record_key in ordered_keys]


def _last_error_message(record: HistoryRecord) -> str:
    last_error = record.last_error if isinstance(record.last_error, dict) else None
    if not last_error:
        return ""
    return str(last_error.get("message") or "").strip()
