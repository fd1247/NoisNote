"""主窗口设置页和模型下载状态回调。"""
from __future__ import annotations

from ..app.config import get_notebooks, save_config
from ..history.service import HistoryService
from ..model_registry.service import ModelService
from ..ui.settings_dialog import SettingsDialog


class SettingsHandlers:
    """设置覆盖页导航、配置保存和模型下载状态处理。"""

    def show_settings(self) -> None:
        if hasattr(self, "stop_playback"):
            self.stop_playback()
            self.playback_record_id = ""
        self.settings_panel.reset_from_config()
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self.settings_panel, self.show_settings_section, self)
        self.show_settings_section("general")
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()
        self._set_status("")

    def show_settings_section(self, section: str) -> None:
        """切换设置模式中的左侧导航和右侧详情。"""
        titles = {
            "general": "通用",
            "notebooks": "笔记本",
            "models": "模型",
            "hotwords": "",
            "shortcuts": "快捷键",
        }
        self.settings_panel.show_section(section)
        for button in self.settings_nav_buttons:
            button.setChecked(False)
        button_map = {
            "general": self.settings_general_button,
            "models": self.settings_models_button,
            "hotwords": self.settings_hotwords_button,
            "shortcuts": self.settings_shortcuts_button,
        }
        button_map.get(section, self.settings_general_button).setChecked(True)
        if self.settings_dialog is not None:
            self.settings_dialog.set_active_section(section)
        self.page_title_label.setText(titles.get(section, "设置"))
        self._set_status("")

    def hide_settings(self) -> None:
        """关闭设置窗口并刷新历史记录。"""
        self.load_recordings()
        if self.settings_dialog is not None:
            self.settings_dialog.hide()
        self._set_status("")

    def _leave_settings(self) -> None:
        """切回主界面，不重复刷新历史记录。"""
        self.sidebar_stack.setCurrentWidget(self.main_sidebar)
        target = self.previous_content_widget or self.recording_page
        if target == self.settings_panel:
            target = self.recording_page
        if target != self.recording_page and not self.current_record:
            target = self.recording_page
        self.content_stack.setCurrentWidget(target)
        if target == self.recording_page:
            self.page_title_label.setText("")
        elif self.current_record:
            self.page_title_label.setText(self.current_record.record_dir.name)
            if hasattr(self, "_set_playback_source"):
                self._set_playback_source(self.current_record)
        self.previous_content_widget = None
        self._set_status("")

    def _apply_settings_config(self, updated_config: dict) -> None:
        self._persist_settings_config(updated_config)
        self.load_recordings()
        self.hide_settings()
        self._set_status("配置已保存")

    def _persist_settings_config(self, updated_config: dict) -> None:
        """保存设置配置并同步依赖，不切换当前页面。"""
        self.config = updated_config
        save_config(self.config)
        self.history_service = HistoryService.from_notebooks(
            get_notebooks(self.config),
            active_notebook_id=str(self.config.get("active_notebook_id") or "default"),
        )
        if self.recorder:
            self.recorder.set_output_dir(str(self.history_service.recordings_dir))
        self.model_download_manager.config = self.config
        self.model_download_manager.service = ModelService(self.config)
        self.settings_panel.config = self.config
        self.settings_panel.model_service = ModelService(self.config)
        self.settings_panel._sync_hotword_service()
        self.settings_panel.model_manager.config = self.config
        self.settings_panel.model_manager.service = ModelService(self.config)

    def _refresh_settings_after_model_change(self) -> None:
        self.settings_panel._refresh_asr_model_options()

    def _on_model_download_failed(self, name: str, error: str) -> None:
        self._set_status(f"模型下载失败：{error}")

    def _on_model_download_completed(self, name: str) -> None:
        self._set_status("模型下载完成")

    def _on_model_download_cancelled(self, name: str) -> None:
        self._set_status("模型下载已取消")
