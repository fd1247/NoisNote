"""设置页模型管理控件。"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..app.config import save_config
from ..utils.logging import log_event
from .widgets.dialogs import confirm_without_icon
from ..model_registry.downloader import ModelDownloadManager
from ..model_registry.service import (
    DownloadTaskState,
    LocalModelInfo,
    ModelCatalogEntry,
    ModelService,
    format_size,
)


class DownloadingModelWidget(QWidget):
    """下载中模型列表项。"""

    def __init__(self, state: DownloadTaskState, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(4)

        header = QHBoxLayout()
        name_label = QLabel(state.name)
        name_label.setObjectName("ModelItemTitle")
        status_label = QLabel(state.status_text)
        status_label.setObjectName("Muted")
        header.addWidget(name_label)
        header.addItem(QSpacerItem(12, 12, QSizePolicy.Expanding, QSizePolicy.Minimum))
        header.addWidget(status_label)

        progress = QProgressBar()
        if state.progress_percent is None:
            progress.setRange(0, 0)
        else:
            progress.setRange(0, 100)
            progress.setValue(int(state.progress_percent))
        progress.setTextVisible(False)

        layout.addLayout(header)
        layout.addWidget(progress)


class ModelListItemWidget(QFrame):
    """模型列表中的两行信息项。"""

    def __init__(self, title: str, subtitle: str, alternate: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("ModelListItem")
        self.setProperty("alternate", alternate)
        self.setProperty("selected", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(3)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("ModelItemTitle")
        self.title_label.setProperty("selected", False)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("ModelItemSubtitle")
        self.subtitle_label.setProperty("selected", False)
        self.subtitle_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)

    def set_selected(self, selected: bool) -> None:
        """同步树项选中态到自定义控件背景。"""
        self.setProperty("selected", selected)
        self.title_label.setProperty("selected", selected)
        self.subtitle_label.setProperty("selected", selected)
        for widget in (self, self.title_label, self.subtitle_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class ModelTreeWidget(QTreeWidget):
    """让模型子项的缩进区和内容区使用同一行背景。"""

    MODEL_ROW_COLORS = ("#ffffff", "#f6f7f8")
    MODEL_SELECTED_COLOR = "#dbeafe"

    def _row_color(self, index) -> QColor | None:
        item = self.itemFromIndex(index)
        if item is None:
            return None
        data = item.data(0, Qt.UserRole)
        if not data or data[0] not in {"downloaded", "available"}:
            return None
        parent = item.parent()
        row = parent.indexOfChild(item) if parent else 0
        color = self.MODEL_SELECTED_COLOR if item is self.currentItem() else self.MODEL_ROW_COLORS[row % 2]
        return QColor(color)

    def drawRow(self, painter: QPainter, options, index) -> None:
        color = self._row_color(index)
        if color is not None:
            rect = QRect(0, options.rect.y(), self.viewport().width(), options.rect.height())
            painter.fillRect(rect, color)
        super().drawRow(painter, options, index)

    def drawBranches(self, painter: QPainter, rect: QRect, index) -> None:
        color = self._row_color(index)
        if color is not None:
            painter.fillRect(rect, color)
        super().drawBranches(painter, rect, index)


class ModelManagerWidget(QWidget):
    """设置页中的模型管理区域。"""

    models_changed = Signal()
    MODEL_ROW_COLORS = ModelTreeWidget.MODEL_ROW_COLORS
    MODEL_SELECTED_COLOR = ModelTreeWidget.MODEL_SELECTED_COLOR

    def __init__(self, config: dict, download_manager: ModelDownloadManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.service = ModelService(self.config)
        self.download_manager = download_manager
        self.selected_kind: str | None = None
        self.selected_name: str | None = None
        self.downloaded_group: QTreeWidgetItem | None = None
        self.available_group: QTreeWidgetItem | None = None
        self.downloading_group: QTreeWidgetItem | None = None
        self._updating_selection = False

        self._build_ui()
        self.download_manager.tasks_changed.connect(self.refresh_lists)
        self.download_manager.models_changed.connect(self.refresh_lists)
        self.download_manager.models_changed.connect(self.models_changed)
        self.refresh_lists()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        group_row = QHBoxLayout()
        group_row.addWidget(QLabel("组"))
        self.group_combo = QComboBox()
        self.group_combo.addItem("Qwen3-ASR GGUF")
        group_row.addWidget(self.group_combo, stretch=1)
        layout.addLayout(group_row)

        self.model_tree = ModelTreeWidget()
        self.model_tree.setIndentation(20)
        self.model_tree.setObjectName("ModelTree")
        self.model_tree.setHeaderHidden(True)
        self.model_tree.setColumnCount(1)
        self.model_tree.setAlternatingRowColors(False)
        self.model_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.model_tree.itemSelectionChanged.connect(self._on_tree_selection)
        layout.addWidget(self.model_tree, stretch=1)

        footer = QHBoxLayout()
        self.model_action_button = QPushButton("选择模型")
        self.model_action_button.setObjectName("PrimaryButton")
        self.model_action_button.clicked.connect(self._run_selected_action)
        footer.addWidget(self.model_action_button)
        footer.addItem(QSpacerItem(12, 12, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.delete_model_button = QPushButton("删除")
        self.delete_model_button.setObjectName("DangerSmallButton")
        self.delete_model_button.clicked.connect(self._delete_selected_model)
        self.delete_model_button.hide()
        footer.addWidget(self.delete_model_button)
        layout.addLayout(footer)

    def refresh_lists(self) -> None:
        """刷新三类模型列表。"""
        expanded_state = self._capture_group_expanded_state()
        self._updating_selection = True
        self.model_tree.clear()
        self.downloaded_group = self._add_group_item("已下载")
        self.available_group = self._add_group_item("可下载")
        self.downloading_group = None

        active_names = set(self.download_manager.get_download_tasks())
        downloaded_models = [
            info for info in self.service.get_downloaded_models() if info.entry.name not in active_names
        ]
        available_models = self.service.get_available_models(active_names)
        download_tasks = list(self.download_manager.get_download_tasks().values())

        for info in downloaded_models:
            if info.entry.name not in active_names:
                self._add_downloaded_item(info)
        if not downloaded_models:
            self._add_empty_item(self.downloaded_group, "还没有下载模型")

        for entry in available_models:
            self._add_available_item(entry)
        if not available_models:
            self._add_empty_item(self.available_group, "没有可供下载的模型")

        if download_tasks:
            self.downloading_group = self._add_group_item("下载中")
        for state in download_tasks:
            self._add_downloading_item(state)

        self._apply_group_expanded_state(expanded_state)
        self._updating_selection = False
        self._sync_model_item_selection()
        self._update_action_button()

    def _capture_group_expanded_state(self) -> dict[str, bool]:
        if not hasattr(self, "model_tree"):
            return {}
        return {
            self.model_tree.topLevelItem(index).data(0, Qt.UserRole)[1]: self.model_tree.topLevelItem(index).isExpanded()
            for index in range(self.model_tree.topLevelItemCount())
        }

    def _apply_group_expanded_state(self, expanded_state: dict[str, bool]) -> None:
        for group in (self.downloaded_group, self.available_group, self.downloading_group):
            if group is None:
                continue
            title = group.data(0, Qt.UserRole)[1]
            group.setExpanded(expanded_state.get(title, True))

    def _add_group_item(self, title: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([title])
        item.setData(0, Qt.UserRole, ("group", title))
        self.model_tree.addTopLevelItem(item)
        return item

    def _add_downloaded_item(self, info: LocalModelInfo) -> None:
        subtitle = f"{info.entry.description} · {format_size(info.size_bytes)}"
        item = QTreeWidgetItem([info.entry.display_name])
        item.setData(0, Qt.UserRole, ("downloaded", info.entry.name))
        item.setToolTip(0, str(info.local_path))
        if self.downloaded_group is not None:
            self.downloaded_group.addChild(item)
            self._set_model_item_widget(item, info.entry.display_name, subtitle)

    def _add_available_item(self, entry: ModelCatalogEntry) -> None:
        item = QTreeWidgetItem([entry.display_name])
        item.setData(0, Qt.UserRole, ("available", entry.name))
        item.setToolTip(0, entry.primary_download_url())
        if self.available_group is not None:
            self.available_group.addChild(item)
            self._set_model_item_widget(item, entry.display_name, entry.description)

    def _set_model_item_widget(self, item: QTreeWidgetItem, title: str, subtitle: str) -> None:
        parent = item.parent()
        row = parent.indexOfChild(item) if parent else 0
        widget = ModelListItemWidget(title, subtitle, row % 2 == 1, self.model_tree)
        item.setBackground(0, QBrush(QColor(self.MODEL_ROW_COLORS[row % 2])))
        item.setSizeHint(0, widget.sizeHint())
        self.model_tree.setItemWidget(item, 0, widget)

    def _add_empty_item(self, group: QTreeWidgetItem | None, text: str) -> None:
        if group is None:
            return
        item = QTreeWidgetItem([text])
        item.setData(0, Qt.UserRole, ("empty", text))
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
        item.setForeground(0, QBrush(QColor("#9ca3af")))
        group.addChild(item)

    def _add_downloading_item(self, state: DownloadTaskState) -> None:
        item = QTreeWidgetItem()
        item.setData(0, Qt.UserRole, ("downloading", state.name))
        if self.downloading_group is None:
            return
        self.downloading_group.addChild(item)
        widget = DownloadingModelWidget(state, self.model_tree)
        item.setSizeHint(0, widget.sizeHint())
        self.model_tree.setItemWidget(item, 0, widget)

    def _on_tree_selection(self) -> None:
        if self._updating_selection:
            return
        item = self.model_tree.currentItem()
        if item:
            self.selected_kind, self.selected_name = item.data(0, Qt.UserRole)
            if self.selected_kind in {"group", "empty"}:
                self.selected_kind = None
                self.selected_name = None
        else:
            self.selected_kind = None
            self.selected_name = None
        self._sync_model_item_selection()
        self._update_action_button()

    def _sync_model_item_selection(self) -> None:
        for group in (self.downloaded_group, self.available_group):
            if group is None:
                continue
            for index in range(group.childCount()):
                item = group.child(index)
                widget = self.model_tree.itemWidget(item, 0)
                row = group.indexOfChild(item)
                color = self.MODEL_SELECTED_COLOR if item is self.model_tree.currentItem() else self.MODEL_ROW_COLORS[row % 2]
                item.setBackground(0, QBrush(QColor(color)))
                if hasattr(widget, "set_selected"):
                    widget.set_selected(item is self.model_tree.currentItem())

    def _update_action_button(self) -> None:
        if self.selected_kind == "downloaded":
            self.model_action_button.setText("查看文件位置")
            self.model_action_button.setEnabled(True)
            self.delete_model_button.setVisible(True)
            self.delete_model_button.setEnabled(True)
        elif self.selected_kind == "available":
            self.model_action_button.setText("下载")
            self.model_action_button.setEnabled(True)
            self.delete_model_button.hide()
        elif self.selected_kind == "downloading":
            self.model_action_button.setText("取消下载")
            self.model_action_button.setEnabled(True)
            self.delete_model_button.hide()
        else:
            self.model_action_button.setText("选择模型")
            self.model_action_button.setEnabled(False)
            self.delete_model_button.hide()

    def _run_selected_action(self) -> None:
        if not self.selected_kind or not self.selected_name:
            return
        if self.selected_kind == "downloaded":
            self._open_selected_model_dir(self.selected_name)
        elif self.selected_kind == "available":
            self.download_manager.start_download(self.selected_name)
        elif self.selected_kind == "downloading":
            self.download_manager.cancel_download(self.selected_name)
            self.selected_kind = None
            self.selected_name = None

    def _open_selected_model_dir(self, name: str) -> None:
        entry = self.service.get_entry(name)
        if not entry:
            QMessageBox.warning(self, "模型不存在", "模型清单中找不到该模型。")
            return
        info = self.service.validate_model_dir(entry)
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(info.local_path)))
        if not opened:
            QMessageBox.warning(self, "打开失败", "无法打开模型目录。")

    def _delete_selected_model(self) -> None:
        """删除当前选中的已下载模型目录。"""
        if self.selected_kind != "downloaded" or not self.selected_name:
            return
        entry = self.service.get_entry(self.selected_name)
        if not entry:
            QMessageBox.warning(self, "模型不存在", "模型清单中找不到该模型。")
            return

        confirmed = confirm_without_icon(
            self,
            "删除模型",
            "您确定要删除所选模型吗?",
        )
        if not confirmed:
            return

        log_event(
            "model.delete.started",
            module="model",
            message="开始删除已下载模型",
            context={"model": entry.name, "display_name": entry.display_name},
        )
        try:
            result = self.service.delete_downloaded_model(entry)
            save_config(self.config)
        except Exception as exc:
            log_event(
                "model.delete.failed",
                level="ERROR",
                module="model",
                message="删除已下载模型失败",
                context={"model": entry.name, "error": str(exc)},
                error_code="MOD-001",
                error_type=type(exc).__name__,
            )
            QMessageBox.warning(self, "删除失败", str(exc))
            return

        self.selected_kind = None
        self.selected_name = None
        self.refresh_lists()
        self.models_changed.emit()
        log_event(
            "model.delete.completed",
            module="model",
            message="已下载模型删除完成",
            context={"model": entry.name, "success": result.success},
        )
        QMessageBox.information(self, "模型删除", result.message)


