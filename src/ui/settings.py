"""设置页面与模型管理 Qt 控件。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..app.config import ANTHROPIC_DEFAULT_BASE_URL, ANTHROPIC_DEFAULT_MODEL
from ..hotwords.service import HotwordService
from ..hotwords.import_export import export_hotword_sets, import_hotword_sets
from ..model_registry.downloader import ModelDownloadManager
from ..model_registry.service import ModelService
from .icons import make_eye_icon
from .model_panel import ModelManagerWidget
from .widgets.dialogs import alert_without_icon, confirm_without_icon
from .widgets.update_dialog import UpdateDialog
from ..app.version import APP_VERSION, get_version_string
from ..app.update import check_for_update_async

# provider 下拉框的 data 值
_PROVIDER_OPENAI = "openai"
_PROVIDER_ANTHROPIC = "anthropic"
_PROVIDER_ITEMS = [
    ("OpenAI 兼容", _PROVIDER_OPENAI),
    ("Anthropic", _PROVIDER_ANTHROPIC),
]
_SVG_DIR = Path(__file__).resolve().parents[1] / "assets" / "svg"


def _asset_icon(svg_name: str) -> QIcon:
    """加载设置页使用的 SVG 图标。"""
    svg_path = _SVG_DIR / svg_name
    return QIcon(str(svg_path)) if svg_path.exists() else QIcon()


class SettingsPanel(QWidget):
    """嵌入主窗口的设置页。"""

    saved = Signal(dict)
    cancelled = Signal()
    hotwords_changed = Signal(dict)

    def __init__(self, config: dict, download_manager: ModelDownloadManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.model_service = ModelService(self.config)
        self.hotword_service = HotwordService(self.config)
        self.download_manager = download_manager
        self.current_hotword_set_id: str | None = None
        self._manual_update_worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.settings_stack = QStackedWidget()
        self.general_page = self._build_general_tab()
        self.model_manager = ModelManagerWidget(self.config, self.download_manager, self)
        self.model_manager.models_changed.connect(self._refresh_asr_model_options)
        self.hotwords_page = self._build_hotword_page()
        self.shortcuts_page = self._build_shortcuts_page()
        self.settings_stack.addWidget(self.general_page)
        self.settings_stack.addWidget(self.model_manager)
        self.settings_stack.addWidget(self.hotwords_page)
        self.settings_stack.addWidget(self.shortcuts_page)

        self.footer_widget = QWidget()
        footer = QHBoxLayout(self.footer_widget)
        footer.setContentsMargins(0, 0, 0, 0)
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
        layout.addWidget(self.footer_widget)

    def show_section(self, section: str) -> None:
        """切换设置分类。"""
        self._sync_hotword_service()
        sections = {
            "general": self.general_page,
            "models": self.model_manager,
            "hotwords": self.hotwords_page,
            "shortcuts": self.shortcuts_page,
        }
        target = sections.get(section, self.general_page)
        self.settings_stack.setCurrentWidget(target)
        if target is self.general_page:
            self._refresh_asr_model_options()
        elif target is self.hotwords_page:
            self._refresh_hotword_list()
        self.footer_widget.setVisible(target is not self.hotwords_page)

    def reset_from_config(self) -> None:
        """丢弃未保存的界面修改，恢复到当前配置。"""
        self.model_service = ModelService(self.config)
        self._sync_hotword_service()
        self._refresh_asr_model_options()
        self.asr_device.setCurrentText(self.config["selected_asr"].get("device", "cpu"))
        self.enable_timestamps.setChecked(
            bool(self.config.get("qwen3_asr_gguf", {}).get("enable_timestamps", False))
        )
        self.api_key.setText(self.config["llm"].get("api_key", ""))
        self.llm_model.setText(self.config["llm"].get("model", "gpt-4o-mini"))
        self.base_url.setText(self.config["llm"].get("base_url", "https://api.openai.com/v1"))
        self.auto_summarize.setChecked(bool(self.config["audio"].get("auto_summarize", True)))
        self.auto_transcribe.setChecked(bool(self.config["audio"].get("auto_transcribe", True)))
        self.model_manager.refresh_lists()
        self._refresh_hotword_list()

    def _sync_hotword_service(self) -> None:
        """确保热词服务始终绑定当前配置对象。"""
        if not hasattr(self, "hotword_service") or self.hotword_service.config is not self.config:
            self.hotword_service = HotwordService(self.config)

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

        self.enable_timestamps = QCheckBox("启用时间戳")
        self.enable_timestamps.setToolTip("启用后会在转录时尝试使用时间戳对齐模型生成逐句时间轴")
        self.enable_timestamps.setChecked(
            bool(self.config.get("qwen3_asr_gguf", {}).get("enable_timestamps", False))
        )
        self.timestamp_hint = QLabel("需要先在模型管理中下载 Qwen3-ForceAligner 时间戳对齐模型。")
        self.timestamp_hint.setObjectName("Muted")
        self.timestamp_hint.setWordWrap(True)

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
        form.addWidget(self._make_label("时间戳"), 2, 0)
        timestamp_box = QVBoxLayout()
        timestamp_box.setContentsMargins(0, 0, 0, 0)
        timestamp_box.setSpacing(4)
        timestamp_box.addWidget(self.enable_timestamps)
        timestamp_box.addWidget(self.timestamp_hint)
        form.addLayout(timestamp_box, 2, 1)
        form.addWidget(self._make_label("LLM 服务商"), 3, 0)
        form.addWidget(self.llm_provider, 3, 1)
        form.addWidget(self._make_label("LLM API Key"), 4, 0)
        form.addWidget(self.api_key, 4, 1)
        form.addWidget(self._make_label("LLM 模型"), 5, 0)
        form.addWidget(self.llm_model, 5, 1)
        form.addWidget(self._make_label("Base URL"), 6, 0)
        form.addWidget(self.base_url, 6, 1)
        form.addWidget(self._make_label("自动转录"), 7, 0)
        form.addWidget(self.auto_transcribe, 7, 1)
        form.addWidget(self._make_label("自动总结"), 8, 0)
        form.addWidget(self.auto_summarize, 8, 1)

        layout.addLayout(form)

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
        downloaded_models = self.model_service.get_downloaded_asr_models()
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
        config["qwen3_asr_gguf"] = dict(self.config.get("qwen3_asr_gguf", {}))
        config["llm"] = dict(self.config.get("llm", {}))
        config["audio"] = dict(self.config.get("audio", {}))

        selected_model = self.asr_model.currentData() or self.asr_model.currentText()
        config["selected_asr"]["model"] = selected_model
        selected_model_path = self.model_service.resolve_selected_model_path(selected_model)
        config["selected_asr"]["model_path"] = str(selected_model_path) if selected_model_path else ""
        config["selected_asr"]["device"] = self.asr_device.currentText()
        config["qwen3_asr_gguf"]["enable_timestamps"] = self.enable_timestamps.isChecked()

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

        # 包含热词配置
        config["hotword_sets"] = list(self.config.get("hotword_sets", []))
        config["active_hotword_set_ids"] = list(self.config.get("active_hotword_set_ids", []))

        return config

    def _emit_saved_config(self) -> None:
        self.saved.emit(self.updated_config())

    def _emit_hotwords_changed(self) -> None:
        """通知外层保存热词相关配置，但不关闭设置页。"""
        self.hotwords_changed.emit(self.updated_config())

    def _on_check_update_clicked(self) -> None:
        """点击检查更新按钮"""
        dialog = UpdateDialog.show_pending_dialog(self, get_version_string())
        self._manual_update_worker = check_for_update_async(APP_VERSION, dialog.set_update_info)

    def _build_hotword_page(self) -> QWidget:
        """创建热词管理页面。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        header_widget = QWidget()
        header_widget.setFixedHeight(76)
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        hero_icon = QLabel()
        hero_icon.setObjectName("HotwordHeroIcon")
        hero_icon.setFixedSize(30, 30)
        hero_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_icon.setPixmap(_asset_icon("热词管理.svg").pixmap(QSize(18, 18)))
        title_block = QVBoxLayout()
        title_block.setSpacing(4)
        section_title = QLabel("热词管理")
        section_title.setObjectName("HotwordHeroTitle")
        section_hint = QLabel("勾选后的热词会在下一次转录时传入ASR上下文")
        section_hint.setObjectName("Muted")
        section_hint.setWordWrap(True)
        title_row.addWidget(hero_icon)
        title_row.addWidget(section_title)
        title_row.addStretch(1)
        section_hint.setContentsMargins(40, 0, 0, 0)
        title_block.addLayout(title_row)
        title_block.addWidget(section_hint)

        active_card, self.active_metric_value, self.active_metric_suffix = self._make_hotword_metric_card("热词表", "激活.svg")
        total_card, self.total_metric_value, self.total_metric_suffix = self._make_hotword_metric_card("总热词", "堆叠.svg")

        header.addLayout(title_block, stretch=1)
        header.addWidget(active_card, alignment=Qt.AlignmentFlag.AlignTop)
        header.addWidget(total_card, alignment=Qt.AlignmentFlag.AlignTop)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("HotwordSplitter")
        splitter.setChildrenCollapsible(False)

        left_panel = QFrame()
        left_panel.setObjectName("HotwordPanel")
        left_panel.setMinimumWidth(300)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(18, 18, 18, 14)
        left_layout.setSpacing(12)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.setContentsMargins(0, 0, 0, 0)
        self.add_hotword_set_button = QPushButton("新建")
        self.add_hotword_set_button.setObjectName("PrimaryButton")
        self.add_hotword_set_button.setIcon(_asset_icon("新建.svg"))
        self.add_hotword_set_button.setIconSize(QSize(15, 15))
        self.add_hotword_set_button.setMinimumWidth(74)
        self.add_hotword_set_button.clicked.connect(self._on_add_hotword_set)
        self.import_hotword_set_button = QPushButton("导入")
        self.import_hotword_set_button.setObjectName("SmallButton")
        self.import_hotword_set_button.setIcon(_asset_icon("导入.svg"))
        self.import_hotword_set_button.setIconSize(QSize(15, 15))
        self.import_hotword_set_button.setMinimumWidth(72)
        self.import_hotword_set_button.clicked.connect(self._on_import_hotword_sets)
        self.export_hotword_set_button = QPushButton("导出")
        self.export_hotword_set_button.setObjectName("SmallButton")
        self.export_hotword_set_button.setIcon(_asset_icon("导出.svg"))
        self.export_hotword_set_button.setIconSize(QSize(15, 15))
        self.export_hotword_set_button.setMinimumWidth(72)
        self.export_hotword_set_button.clicked.connect(self._on_export_hotword_sets)

        toolbar.addWidget(self.add_hotword_set_button)
        toolbar.addWidget(self.import_hotword_set_button)
        toolbar.addWidget(self.export_hotword_set_button)
        toolbar.addStretch(1)

        self.hotword_search = QLineEdit()
        self.hotword_search.setObjectName("HotwordSearchBox")
        self.hotword_search.setPlaceholderText("搜索热词表")
        self.hotword_search.textChanged.connect(self._refresh_hotword_list)

        self.hotword_set_list = QListWidget()
        self.hotword_set_list.setObjectName("HotwordSetList")
        self.hotword_set_list.setUniformItemSizes(True)
        self.hotword_set_list.setSpacing(8)
        self.hotword_set_list.itemChanged.connect(self._on_hotword_set_check_changed)
        self.hotword_set_list.currentItemChanged.connect(self._on_hotword_set_selected)

        list_footer = QHBoxLayout()
        list_footer.setContentsMargins(0, 0, 0, 0)
        self.hotword_list_count_label = QLabel("共 0 项")
        self.hotword_list_count_label.setObjectName("Muted")
        list_footer.addWidget(self.hotword_list_count_label)
        list_footer.addStretch(1)

        left_layout.addLayout(toolbar)
        left_layout.addWidget(self.hotword_search)
        left_layout.addWidget(self.hotword_set_list, stretch=1)
        left_layout.addLayout(list_footer)

        right_panel = QFrame()
        right_panel.setObjectName("HotwordPanel")
        right_panel.setMinimumWidth(480)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(14)

        self.hotword_detail_title = QLabel("未选择热词表")
        self.hotword_detail_title.hide()
        self.hotword_detail_subtitle = QLabel("从左侧选择一个热词表进行编辑")
        self.hotword_detail_subtitle.hide()
        self.word_count_label = QLabel("0/50")
        self.word_count_label.hide()

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(12)
        form.setColumnMinimumWidth(0, 52)
        form.setColumnStretch(1, 1)

        self.hotword_set_name = QLineEdit()
        self.hotword_set_name.setPlaceholderText("输入热词表名称")

        self.hotword_set_description = QLineEdit()
        self.hotword_set_description.setPlaceholderText("输入描述（可选）")

        self.hotword_words = QPlainTextEdit()
        self.hotword_words.setObjectName("HotwordWordsEditor")
        self.hotword_words.setPlaceholderText("每行一个热词，支持回车或粘贴批量导入")
        self.hotword_words.setMinimumHeight(230)
        self.hotword_words.textChanged.connect(self._update_word_count)

        word_editor_layout = QVBoxLayout()
        word_editor_layout.setContentsMargins(0, 0, 0, 0)
        word_editor_layout.setSpacing(4)
        word_tools = QHBoxLayout()
        word_tools.setContentsMargins(0, 0, 0, 0)
        word_tools.setSpacing(8)
        word_tools.addStretch(1)
        self.dedupe_hotword_button = QPushButton("去重")
        self.dedupe_hotword_button.setObjectName("SmallButton")
        self.dedupe_hotword_button.clicked.connect(self._on_dedupe_hotwords)
        word_tools.addWidget(self.dedupe_hotword_button)
        word_editor_layout.addLayout(word_tools)
        word_editor_layout.addWidget(self.hotword_words)
        word_editor_widget = QWidget()
        word_editor_widget.setLayout(word_editor_layout)

        form.addWidget(self._make_label("名称"), 0, 0)
        form.addWidget(self.hotword_set_name, 0, 1)
        form.addWidget(self._make_label("描述"), 1, 0)
        form.addWidget(self.hotword_set_description, 1, 1)
        form.addWidget(self._make_label("热词"), 2, 0, Qt.AlignmentFlag.AlignTop)
        form.addWidget(word_editor_widget, 2, 1)

        detail_actions = QHBoxLayout()
        detail_actions.setContentsMargins(0, 6, 0, 2)
        detail_actions.setSpacing(8)
        self.save_hotword_set_button = QPushButton("保存")
        self.save_hotword_set_button.setObjectName("PrimaryButton")
        self.save_hotword_set_button.setMinimumWidth(72)
        self.save_hotword_set_button.clicked.connect(self._on_save_hotword_set)
        self.delete_hotword_set_button = QPushButton("删除")
        self.delete_hotword_set_button.setObjectName("DangerSmallButton")
        self.delete_hotword_set_button.setMinimumWidth(72)
        self.delete_hotword_set_button.clicked.connect(self._on_delete_hotword_set)

        detail_actions.addStretch(1)
        detail_actions.addWidget(self.delete_hotword_set_button)
        detail_actions.addWidget(self.save_hotword_set_button)

        right_layout.addLayout(form)
        right_layout.addLayout(detail_actions)
        right_layout.addStretch(1)

        self._set_hotword_detail_enabled(False)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(header_widget, stretch=0)
        layout.addWidget(splitter, stretch=1)

        self._refresh_hotword_list()

        return page

    def _make_hotword_metric_card(self, title: str, icon_name: str) -> tuple[QFrame, QLabel, QLabel]:
        """创建热词统计卡片。"""
        card = QFrame()
        card.setObjectName("HotwordMetricCard")
        card.setFixedSize(150, 70)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        icon = QLabel()
        icon.setObjectName("HotwordMetricIcon")
        icon.setFixedSize(34, 34)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_pixmap = _asset_icon(icon_name).pixmap(QSize(18, 18))
        if icon_pixmap.isNull():
            icon.setText(title[:1])
        else:
            icon.setPixmap(icon_pixmap)

        text_block = QVBoxLayout()
        text_block.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("HotwordMetricTitle")
        value_row = QHBoxLayout()
        value_row.setSpacing(3)
        value_label = QLabel("0")
        value_label.setObjectName("HotwordMetricValue")
        suffix_label = QLabel("/0")
        suffix_label.setObjectName("HotwordMetricSuffix")
        value_row.addWidget(value_label)
        value_row.addWidget(suffix_label)
        value_row.addStretch(1)
        text_block.addWidget(title_label)
        text_block.addLayout(value_row)

        layout.addWidget(icon)
        layout.addLayout(text_block, stretch=1)
        return card, value_label, suffix_label

    def _refresh_hotword_list(self) -> None:
        """刷新热词表列表。"""
        if not hasattr(self, "hotword_set_list"):
            return

        self._sync_hotword_service()
        self.hotword_set_list.blockSignals(True)
        self.hotword_set_list.clear()

        active_ids = set(self.config.get("active_hotword_set_ids", []))
        selected_id = self.current_hotword_set_id
        selected_item: QListWidgetItem | None = None
        query = ""
        if hasattr(self, "hotword_search"):
            query = self.hotword_search.text().strip().lower()
        all_sets = self.hotword_service.get_hotword_sets()
        visible_count = 0

        for item_data in all_sets:
            name = item_data.get("name", "未命名")
            description = item_data.get("description", "").strip()
            words = item_data.get("words", [])
            haystack = " ".join([name, description, *words]).lower()
            if query and query not in haystack:
                continue

            list_item = QListWidgetItem()
            item_id = item_data.get("id")
            list_item.setData(Qt.ItemDataRole.UserRole, item_id)

            # 显示文本
            word_count = len(words)
            suffix = f"{word_count} 个热词"
            is_active = item_id in active_ids
            list_item.setText("")
            list_item.setToolTip(description or suffix)
            list_item.setSizeHint(QSize(0, 58))

            self.hotword_set_list.addItem(list_item)
            self.hotword_set_list.setItemWidget(
                list_item,
                self._make_hotword_list_item_widget(list_item, name, suffix, is_active),
            )
            visible_count += 1
            if item_id == selected_id:
                selected_item = list_item

        self.hotword_set_list.blockSignals(False)
        if hasattr(self, "hotword_list_count_label"):
            if query:
                self.hotword_list_count_label.setText(f"共 {len(all_sets)} 项，显示 {visible_count} 项")
            else:
                self.hotword_list_count_label.setText(f"共 {len(all_sets)} 项")
        if selected_item is not None:
            self.hotword_set_list.setCurrentItem(selected_item)
        elif selected_id:
            self.current_hotword_set_id = None
            self._set_hotword_detail_enabled(False)
        self._update_active_status()

    def _make_hotword_list_item_widget(
        self,
        item: QListWidgetItem,
        name: str,
        count_text: str,
        checked: bool,
    ) -> QWidget:
        """创建热词表列表项内容。"""
        widget = QWidget()
        widget.setObjectName("HotwordSetItemContent")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        checkbox = QCheckBox()
        checkbox.setObjectName("HotwordActiveCheckBox")
        checkbox.setChecked(checked)
        checkbox.toggled.connect(
            lambda is_checked, list_item=item: list_item.setCheckState(
                Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked
            )
        )

        text_block = QVBoxLayout()
        text_block.setSpacing(1)
        title = QLabel(name)
        title.setObjectName("HotwordSetItemTitle")
        title.setWordWrap(False)
        count = QLabel(count_text)
        count.setObjectName("HotwordSetItemCount")
        text_block.addWidget(title)
        text_block.addWidget(count)

        layout.addWidget(checkbox, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(text_block, stretch=1)
        return widget

    def _update_active_status(self) -> None:
        """更新激活状态显示。"""
        if not hasattr(self, "active_metric_value"):
            return

        active_ids = self.config.get("active_hotword_set_ids", [])
        active_count = len(active_ids)

        all_sets = self.config.get("hotword_sets", [])
        total_words = 0
        for item_data in all_sets:
            if item_data.get("id") in active_ids:
                total_words += len(item_data.get("words", []))

        from ..hotwords import MAX_ACTIVE_SETS, HARD_LIMIT_TOTAL_WORDS

        self.active_metric_value.setText(str(active_count))
        self.active_metric_suffix.setText(f"/{MAX_ACTIVE_SETS}")
        self.total_metric_value.setText(str(total_words))
        self.total_metric_suffix.setText(f"/{HARD_LIMIT_TOTAL_WORDS}")

    def _on_hotword_set_check_changed(self, item: QListWidgetItem) -> None:
        """处理热词表激活状态变更。"""
        active_ids = list(self.config.get("active_hotword_set_ids", []))
        set_id = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            if set_id not in active_ids:
                active_ids.append(set_id)
        else:
            active_ids = [active_id for active_id in active_ids if active_id != set_id]

        try:
            self.hotword_service.set_active_sets(active_ids)
            self._emit_hotwords_changed()
            self._update_active_status()
            self._refresh_hotword_list()
        except Exception as e:
            # 恢复原状态
            self._refresh_hotword_list()
            alert_without_icon(self, "设置失败", f"{e}")

    def _on_hotword_set_selected(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        """处理热词表选择。"""
        if current is None:
            self._set_hotword_detail_enabled(False)
            self.current_hotword_set_id = None
            return

        set_id = current.data(Qt.ItemDataRole.UserRole)
        hotword_set = self.hotword_service.get_hotword_set(set_id)
        if hotword_set:
            self._set_hotword_detail_enabled(True)
            self.hotword_detail_title.setText(hotword_set.get("name", "未命名"))
            word_count = len(hotword_set.get("words", []))
            self.hotword_detail_subtitle.setText(f"{word_count} 个热词")
            self.hotword_set_name.setText(hotword_set.get("name", ""))
            self.hotword_set_description.setText(hotword_set.get("description", ""))
            self.hotword_words.setPlainText("\n".join(hotword_set.get("words", [])))
            self._update_word_count()
            self.current_hotword_set_id = set_id

    def _on_save_hotword_set(self) -> None:
        """保存热词表详情。"""
        if not self.current_hotword_set_id:
            return

        name = self.hotword_set_name.text().strip()
        description = self.hotword_set_description.text().strip()
        words = [line.strip() for line in self.hotword_words.toPlainText().split("\n") if line.strip()]

        try:
            self.hotword_service.update_hotword_set(
                self.current_hotword_set_id,
                {"name": name, "description": description, "words": words}
            )
            self._emit_hotwords_changed()
            self._refresh_hotword_list()
            self.hotword_detail_title.setText(name or "未命名")
            self.hotword_detail_subtitle.setText(f"{len(words)} 个热词")
        except Exception as e:
            alert_without_icon(self, "保存失败", f"{e}")

    def _on_delete_hotword_set(self) -> None:
        """删除当前热词表。"""
        if not self.current_hotword_set_id:
            return

        confirmed = confirm_without_icon(
            self,
            "删除热词表",
            "删除后无法恢复，确定要删除吗？",
        )
        if confirmed:
            self.hotword_service.delete_hotword_set(self.current_hotword_set_id)
            self._emit_hotwords_changed()
            self._refresh_hotword_list()
            self.current_hotword_set_id = None
            self._set_hotword_detail_enabled(False)

    def _on_add_hotword_set(self) -> None:
        """添加新热词表。"""
        try:
            new_set = self.hotword_service.create_hotword_set("新建热词表", "", [])
            self._emit_hotwords_changed()
            self._refresh_hotword_list()
            # 选中新创建的项
            for i in range(self.hotword_set_list.count()):
                item = self.hotword_set_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == new_set.get("id"):
                    self.hotword_set_list.setCurrentItem(item)
                    break
        except Exception as e:
            alert_without_icon(self, "创建失败", f"{e}")

    def _on_import_hotword_sets(self) -> None:
        """导入热词表。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入热词表",
            "",
            "JSON 文件 (*.json)",
        )
        if not file_path:
            return

        try:
            json_text = Path(file_path).read_text(encoding="utf-8")
            existing_sets = self.config.get("hotword_sets", [])
            imported_sets, errors = import_hotword_sets(json_text, existing_sets)

            if imported_sets:
                self.config["hotword_sets"] = existing_sets + imported_sets
                self._emit_hotwords_changed()
                self._refresh_hotword_list()

            # 显示结果
            if errors:
                error_msg = "\n".join(errors)
                alert_without_icon(self, "导入结果", f"成功导入 {len(imported_sets)} 个热词表\n\n错误：\n{error_msg}")
            else:
                alert_without_icon(self, "导入结果", f"成功导入 {len(imported_sets)} 个热词表")

        except Exception as e:
            alert_without_icon(self, "导入失败", f"无法读取文件：{e}")

    def _on_export_hotword_sets(self) -> None:
        """导出选中的热词表。"""
        active_ids = list(self.config.get("active_hotword_set_ids", []))

        if not active_ids:
            alert_without_icon(self, "导出", "请先勾选要导出的热词表")
            return

        sets_to_export = [
            s for s in self.config.get("hotword_sets", [])
            if s.get("id") in active_ids
        ]

        json_text = export_hotword_sets(sets_to_export)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出热词表",
            "hotwords.json",
            "JSON 文件 (*.json)",
        )
        if file_path:
            Path(file_path).write_text(json_text, encoding="utf-8")

    def _set_hotword_detail_enabled(self, enabled: bool) -> None:
        """启用/禁用详情编辑。"""
        self.hotword_set_name.setEnabled(enabled)
        self.hotword_set_description.setEnabled(enabled)
        self.hotword_words.setEnabled(enabled)
        self.save_hotword_set_button.setEnabled(enabled)
        self.delete_hotword_set_button.setEnabled(enabled)
        if hasattr(self, "dedupe_hotword_button"):
            self.dedupe_hotword_button.setEnabled(enabled)
        if not enabled:
            self.hotword_detail_title.setText("未选择热词表")
            self.hotword_detail_subtitle.setText("从左侧选择一个热词表进行编辑")
            self.hotword_set_name.clear()
            self.hotword_set_description.clear()
            self.hotword_words.clear()
            self._update_word_count()

    def _update_word_count(self) -> None:
        """更新热词数量显示。"""
        count = len([line for line in self.hotword_words.toPlainText().split("\n") if line.strip()])
        self.word_count_label.setText(f"{count}/50")

    def _on_dedupe_hotwords(self) -> None:
        """去除当前热词编辑框中的重复项。"""
        seen = set()
        unique_words = []
        for line in self.hotword_words.toPlainText().splitlines():
            word = line.strip()
            if not word or word in seen:
                continue
            seen.add(word)
            unique_words.append(word)
        self.hotword_words.setPlainText("\n".join(unique_words))
