"""历史记录相关 Qt 控件。"""
from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...history.service import HistoryRecord
from ..core.icons import make_action_icon, make_history_icon


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

    ROW_HEIGHT = 56

    def __init__(self, record: HistoryRecord, index: int, window: HistoryActions, subtitle: str = ""):
        super().__init__()
        self.record = record
        self.index = index
        self.window = window
        self._selected = False
        self._hovered = False
        self.setObjectName("HistoryItem")
        self.setMouseTracking(True)
        self.setFixedHeight(self.ROW_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.setSpacing(8)

        icon = QLabel()
        icon.setObjectName("HistoryIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(22, 22)
        icon.setPixmap(make_history_icon().pixmap(22, 22))

        self.title_label = ElidedLabel(record.display_name)
        self.title_label.setObjectName("HistoryTitle")

        self.subtitle_label = ElidedLabel(subtitle)
        self.subtitle_label.setObjectName("HistorySubtitle")
        self.subtitle_label.setVisible(bool(subtitle))

        text_container = QWidget()
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)

        self.more_button = QToolButton()
        self.more_button.setObjectName("HistoryMoreButton")
        self.more_button.setIcon(make_action_icon("more"))
        self.more_button.setIconSize(QSize(16, 16))
        self.more_button.setFixedSize(28, 28)
        self.more_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.more_button.setToolTip("更多操作")
        self.more_button.hide()
        self.more_button.clicked.connect(self._show_menu)

        layout.addWidget(icon, alignment=Qt.AlignVCenter)
        layout.addWidget(text_container, stretch=1, alignment=Qt.AlignVCenter)
        layout.addWidget(self.more_button, alignment=Qt.AlignVCenter)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(hint.width(), self.ROW_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(hint.width(), self.ROW_HEIGHT)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._sync_more_button()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._sync_more_button()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self.window.select_history_index(self.index)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setProperty("selected", selected)
        self.title_label.setProperty("selected", selected)
        self.subtitle_label.setProperty("selected", selected)
        self._sync_more_button()
        self.style().unpolish(self)
        self.style().polish(self)
        self.title_label.style().unpolish(self.title_label)
        self.title_label.style().polish(self.title_label)
        self.subtitle_label.style().unpolish(self.subtitle_label)
        self.subtitle_label.style().polish(self.subtitle_label)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label._full_text = text
        self.subtitle_label.setToolTip(text)
        self.subtitle_label.setVisible(bool(text))
        self.subtitle_label._update_elided_text()

    def _sync_more_button(self) -> None:
        if self._hovered or self.more_button.underMouse():
            self.more_button.show()
            return
        self.more_button.hide()

    def _show_menu(self) -> None:
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
