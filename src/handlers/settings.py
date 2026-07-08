"""主窗口设置页和模型下载状态回调。"""
from __future__ import annotations

from ..app.config import get_notebooks, save_config
from ..history.service import HistoryService
from ..model_registry.service import ModelService
from ..ui.dialogs.settings import SettingsDialog


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
            "models": "模型",
            "hotwords": "",
            "shortcuts": "快捷键",
        }
        self.settings_panel.show_section(section)
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

    def _apply_settings_config(self, updated_config: dict) -> None:
        self._persist_settings_config(updated_config)
        self.load_recordings()
        self.hide_settings()
        self._set_status("配置已保存")

    def _persist_settings_config(self, updated_config: dict) -> None:
        """保存设置配置并同步依赖，不切换当前页面。"""
        self.config = updated_config
        self.current_notebook_id = str(self.config.get("active_notebook_id") or self.current_notebook_id or "default")
        save_config(self.config)
        self.history_service = HistoryService.from_notebooks(
            get_notebooks(self.config),
            active_notebook_id=self.current_notebook_id,
        )
        self._refresh_notebook_selector()
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
        message = f"模型下载失败：{error}"
        self._set_status(message)
        self._show_error(message)

    def _on_model_download_completed(self, name: str) -> None:
        self._set_status("模型下载完成")

    def _on_model_download_cancelled(self, name: str) -> None:
        self._set_status("模型下载已取消")
