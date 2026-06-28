"""历史记录相关 Qt 控件。"""
from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from ...history.service import HistoryRecord


class ElidedLabel(QLabel):
    """单行省略标签，避免长文件名撑开历史列表项。"""

    def __init__(self, text: str):
        super().__init__()
        self._full_text = text
        self.setTextFormat(Qt.PlainText)
        self.setToolTip(text)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._update_elided_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided_text()

    def _update_elided_text(self) -> None:
        width = max(0, self.width())
        metrics = self.fontMetrics()
        self.setText(metrics.elidedText(self._full_text, Qt.ElideRight, width))


class HistoryActions(Protocol):
    """历史记录列表项依赖的主窗口动作接口。"""

    def select_history_index(self, index: int) -> None:
        ...

    def rename_history_record(self, index: int) -> None:
        ...

    def open_history_record_folder(self, index: int) -> None:
        ...

    def delete_history_record(self, index: int) -> None:
        ...


class HistoryListItemWidget(QFrame):
    """历史记录列表项。"""

    def __init__(self, record: HistoryRecord, index: int, window: HistoryActions):
        super().__init__()
        self.record = record
        self.index = index
        self.window = window
        self._selected = False
        self.setObjectName("HistoryItem")
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.setSpacing(8)

        icon = QLabel("▢")
        icon.setObjectName("HistoryIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(22, 22)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        title = ElidedLabel(record.display_name)
        title.setObjectName("HistoryTitle")
        subtitle = ElidedLabel(record.display_subtitle)
        subtitle.setObjectName("HistorySubtitle")
        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)

        self.more_button = QPushButton("...")
        self.more_button.setObjectName("HistoryMoreButton")
        self.more_button.setFixedSize(30, 30)
        self.more_button.setToolTip("更多操作")
        self.more_button.hide()
        self.more_button.clicked.connect(self._show_menu)

        layout.addWidget(icon)
        layout.addLayout(text_layout, stretch=1)
        layout.addWidget(self.more_button)

    def enterEvent(self, event) -> None:
        self.more_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._sync_more_button()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self.window.select_history_index(self.index)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setProperty("selected", selected)
        self._sync_more_button()
        self.style().unpolish(self)
        self.style().polish(self)

    def _sync_more_button(self) -> None:
        if self._selected or self.underMouse() or self.more_button.underMouse():
            self.more_button.show()
            return
        self.more_button.hide()

    def _show_menu(self) -> None:
        self.window.select_history_index(self.index)
        self.more_button.show()

        menu = QMenu(self)
        rename_action = QAction("重命名", self)
        open_action = QAction("在文件夹中打开", self)
        delete_action = QAction("删除", self)
        delete_action.setObjectName("DangerMenuAction")

        rename_action.triggered.connect(lambda: self.window.rename_history_record(self.index))
        open_action.triggered.connect(lambda: self.window.open_history_record_folder(self.index))
        delete_action.triggered.connect(lambda: self.window.delete_history_record(self.index))

        menu.addAction(rename_action)
        menu.addAction(open_action)
        menu.addSeparator()
        menu.addAction(delete_action)
        menu.exec(self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))
