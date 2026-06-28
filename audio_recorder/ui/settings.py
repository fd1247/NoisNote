"""设置页面与模型管理 Qt 控件。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from ..app.config import ANTHROPIC_DEFAULT_BASE_URL, ANTHROPIC_DEFAULT_MODEL
from ..model_registry.downloader import ModelDownloadManager
from ..model_registry.service import ModelService
from .icons import make_eye_icon
from .model_panel import ModelManagerWidget
from .widgets.update_dialog import UpdateDialog
from ..app.version import APP_VERSION, get_version_string
from ..app.update import check_for_update_sync

# provider 下拉框的 data 值
_PROVIDER_OPENAI = "openai"
_PROVIDER_ANTHROPIC = "anthropic"
_PROVIDER_ITEMS = [
    ("OpenAI 兼容", _PROVIDER_OPENAI),
    ("Anthropic", _PROVIDER_ANTHROPIC),
]


class SettingsPanel(QWidget):
    """嵌入主窗口的设置页。"""

    saved = Signal(dict)
    cancelled = Signal()

    def __init__(self, config: dict, download_manager: ModelDownloadManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.model_service = ModelService(self.config)
        self.download_manager = download_manager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.settings_stack = QStackedWidget()
        self.general_page = self._build_general_tab()
        self.model_manager = ModelManagerWidget(self.config, self.download_manager, self)
        self.model_manager.models_changed.connect(self._refresh_asr_model_options)
        self.shortcuts_page = self._build_shortcuts_page()
        self.settings_stack.addWidget(self.general_page)
        self.settings_stack.addWidget(self.model_manager)
        self.settings_stack.addWidget(self.shortcuts_page)

        footer = QHBoxLayout()
        footer.addItem(QSpacerItem(12, 12, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.clicked.connect(self._emit_saved_config)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("SmallButton")
        self.cancel_button.clicked.connect(self.cancelled.emit)
        footer.addWidget(self.save_button)
        footer.addWidget(self.cancel_button)

        layout.addWidget(self.settings_stack, stretch=1)
        layout.addLayout(footer)

    def show_section(self, section: str) -> None:
        """切换设置分类。"""
        sections = {
            "general": self.general_page,
            "models": self.model_manager,
            "shortcuts": self.shortcuts_page,
        }
        target = sections.get(section, self.general_page)
        self.settings_stack.setCurrentWidget(target)
        if target is self.general_page:
            self._refresh_asr_model_options()

    def reset_from_config(self) -> None:
        """丢弃未保存的界面修改，恢复到当前配置。"""
        self.model_service = ModelService(self.config)
        self._refresh_asr_model_options()
        self.asr_device.setCurrentText(self.config["selected_asr"].get("device", "cpu"))
        self.api_key.setText(self.config["llm"].get("api_key", ""))
        self.llm_model.setText(self.config["llm"].get("model", "gpt-4o-mini"))
        self.base_url.setText(self.config["llm"].get("base_url", "https://api.openai.com/v1"))
        self.auto_summarize.setChecked(bool(self.config["audio"].get("auto_summarize", True)))
        self.auto_transcribe.setChecked(bool(self.config["audio"].get("auto_transcribe", True)))
        self.model_manager.refresh_lists()

    def _build_general_tab(self) -> QWidget:
        """创建通用设置页。"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setColumnMinimumWidth(0, 110)
        form.setColumnStretch(1, 1)

        self.asr_model = QComboBox()
        self._refresh_asr_model_options()

        self.asr_device = QComboBox()
        self.asr_device.addItems(["auto", "cpu", "gpu"])
        self.asr_device.setToolTip("gpu 会尝试启用 GGUF 路线可用的 GPU/DirectML 加速")
        self.asr_device.setCurrentText(self.config["selected_asr"].get("device", "cpu"))

        # LLM 服务商选择
        self.llm_provider = QComboBox()
        for label, data in _PROVIDER_ITEMS:
            self.llm_provider.addItem(label, data)
        current_provider = self.config["llm"].get("provider", "openai")
        provider_index = self.llm_provider.findData(current_provider)
        if provider_index >= 0:
            self.llm_provider.setCurrentIndex(provider_index)
        self.llm_provider.currentIndexChanged.connect(self._on_provider_changed)

        self.api_key = QLineEdit(self.config["llm"].get("api_key", ""))
        self.api_key.setEchoMode(QLineEdit.Password)
        self._update_api_key_placeholder()
        self.api_key_visible = False
        self.api_key_toggle = self.api_key.addAction(
            make_eye_icon(showing=False),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self.api_key_toggle.setToolTip("显示 API Key")
        self.api_key_toggle.triggered.connect(self._toggle_api_key_visible)

        self.llm_model = QLineEdit(self.config["llm"].get("model", ""))
        self._update_model_placeholder()
        self.base_url = QLineEdit(self.config["llm"].get("base_url", ""))
        self._update_base_url_placeholder()

        self.auto_transcribe = QCheckBox("录音/导入后自动转录")
        self.auto_transcribe.setChecked(bool(self.config["audio"].get("auto_transcribe", True)))

        self.auto_summarize = QCheckBox("转录完成后自动总结")
        self.auto_summarize.setChecked(bool(self.config["audio"].get("auto_summarize", True)))

        form.addWidget(self._make_label("ASR 模型"), 0, 0)
        form.addWidget(self.asr_model, 0, 1)
        form.addWidget(self._make_label("推理设备"), 1, 0)
        form.addWidget(self.asr_device, 1, 1)
        form.addWidget(self._make_label("LLM 服务商"), 2, 0)
        form.addWidget(self.llm_provider, 2, 1)
        form.addWidget(self._make_label("LLM API Key"), 3, 0)
        form.addWidget(self.api_key, 3, 1)
        form.addWidget(self._make_label("LLM 模型"), 4, 0)
        form.addWidget(self.llm_model, 4, 1)
        form.addWidget(self._make_label("Base URL"), 5, 0)
        form.addWidget(self.base_url, 5, 1)
        form.addWidget(self._make_label("自动转录"), 6, 0)
        form.addWidget(self.auto_transcribe, 6, 1)
        form.addWidget(self._make_label("自动总结"), 7, 0)
        form.addWidget(self.auto_summarize, 7, 1)

        layout.addLayout(form)

        # 版本信息和检查更新
        version_layout = QHBoxLayout()
        version_layout.setContentsMargins(0, 16, 0, 0)
        version_layout.setSpacing(12)

        version_label = QLabel(f"当前版本：{get_version_string()}")
        version_label.setObjectName("SettingsVersionLabel")
        version_layout.addWidget(version_label)

        check_update_button = QPushButton("检查更新")
        check_update_button.setObjectName("SmallButton")
        check_update_button.clicked.connect(self._on_check_update_clicked)
        version_layout.addWidget(check_update_button)

        version_layout.addStretch(1)
        layout.addLayout(version_layout)

        layout.addStretch(1)
        return tab

    def _build_shortcuts_page(self) -> QWidget:
        """创建快捷键设置页占位。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        label = QLabel("快捷键设置会在后续阶段开放")
        label.setObjectName("Muted")
        layout.addWidget(label)
        layout.addStretch(1)
        return page

    def _refresh_asr_model_options(self) -> None:
        """刷新通用页中的已下载 ASR 模型列表。"""
        if not hasattr(self, "asr_model"):
            return
        current_model = self.config["selected_asr"].get("model", "")
        self.asr_model.blockSignals(True)
        self.asr_model.clear()
        downloaded_models = self.model_service.get_downloaded_models()
        if downloaded_models:
            for info in downloaded_models:
                self.asr_model.addItem(info.entry.display_name, info.entry.name)
            target_index = self.asr_model.findData(current_model)
            if target_index >= 0:
                self.asr_model.setCurrentIndex(target_index)
        else:
            self.asr_model.addItem("暂无已下载模型", current_model)
        self.asr_model.blockSignals(False)

    def _make_label(self, text: str) -> QLabel:
        """创建设置表单左侧标签。"""
        label = QLabel(text)
        label.setObjectName("SettingsLabel")
        return label

    def _toggle_api_key_visible(self) -> None:
        """切换 API Key 可见状态。"""
        self.api_key_visible = not self.api_key_visible
        if self.api_key_visible:
            self.api_key.setEchoMode(QLineEdit.Normal)
            self.api_key_toggle.setIcon(make_eye_icon(showing=True))
            self.api_key_toggle.setToolTip("隐藏 API Key")
        else:
            self.api_key.setEchoMode(QLineEdit.Password)
            self.api_key_toggle.setIcon(make_eye_icon(showing=False))
            self.api_key_toggle.setToolTip("显示 API Key")

    def _current_provider(self) -> str:
        """获取当前选中的 provider 标识。"""
        return self.llm_provider.currentData() or _PROVIDER_OPENAI

    def _on_provider_changed(self) -> None:
        """切换 LLM 服务商时更新 placeholder。"""
        self._update_api_key_placeholder()
        self._update_model_placeholder()
        self._update_base_url_placeholder()

    def _update_api_key_placeholder(self) -> None:
        """根据 provider 更新 API Key 输入框的 placeholder。"""
        if self._current_provider() == _PROVIDER_ANTHROPIC:
            self.api_key.setPlaceholderText("sk-ant-...")
        else:
            self.api_key.setPlaceholderText("sk-...")

    def _update_model_placeholder(self) -> None:
        """根据 provider 更新模型输入框的 placeholder。"""
        if self._current_provider() == _PROVIDER_ANTHROPIC:
            self.llm_model.setPlaceholderText(ANTHROPIC_DEFAULT_MODEL)
        else:
            self.llm_model.setPlaceholderText("gpt-4o-mini")

    def _update_base_url_placeholder(self) -> None:
        """根据 provider 更新 Base URL 输入框的 placeholder。"""
        if self._current_provider() == _PROVIDER_ANTHROPIC:
            self.base_url.setPlaceholderText(ANTHROPIC_DEFAULT_BASE_URL)
        else:
            self.base_url.setPlaceholderText("https://api.openai.com/v1")

    def updated_config(self) -> dict:
        """返回更新后的配置副本。"""
        config = dict(self.config)
        config["selected_asr"] = dict(self.config.get("selected_asr", {}))
        config["llm"] = dict(self.config.get("llm", {}))
        config["audio"] = dict(self.config.get("audio", {}))

        selected_model = self.asr_model.currentData() or self.asr_model.currentText()
        config["selected_asr"]["model"] = selected_model
        selected_model_path = self.model_service.resolve_selected_model_path(selected_model)
        config["selected_asr"]["model_path"] = str(selected_model_path) if selected_model_path else ""
        config["selected_asr"]["device"] = self.asr_device.currentText()

        provider = self._current_provider()
        config["llm"]["provider"] = provider
        config["llm"]["api_key"] = self.api_key.text().strip()
        if provider == _PROVIDER_ANTHROPIC:
            config["llm"]["model"] = self.llm_model.text().strip() or ANTHROPIC_DEFAULT_MODEL
            config["llm"]["base_url"] = self.base_url.text().strip() or ANTHROPIC_DEFAULT_BASE_URL
        else:
            config["llm"]["model"] = self.llm_model.text().strip() or "gpt-4o-mini"
            config["llm"]["base_url"] = self.base_url.text().strip() or "https://api.openai.com/v1"

        config["audio"]["auto_transcribe"] = self.auto_transcribe.isChecked()
        config["audio"]["auto_summarize"] = self.auto_summarize.isChecked()
        return config

    def _emit_saved_config(self) -> None:
        self.saved.emit(self.updated_config())

    def _on_check_update_clicked(self) -> None:
        """点击检查更新按钮"""
        try:
            update_info = check_for_update_sync(APP_VERSION)
            if update_info.has_update:
                UpdateDialog.show_update_dialog(self, update_info)
            else:
                QMessageBox.information(
                    self,
                    "检查更新",
                    f"已是最新版本：{get_version_string()}",
                )
        except Exception as e:
            QMessageBox.warning(
                self,
                "检查更新失败",
                f"无法检查更新：{e}",
            )
