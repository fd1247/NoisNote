"""当前笔记本下的历史记录树。"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QItemSelectionModel, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QMenu,
    QSizePolicy,
    QStyledItemDelegate,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
)

from ...history.types import HistoryRecord
from ..icons import make_history_icon

_ROLE_KIND = Qt.ItemDataRole.UserRole
_ROLE_VALUE = Qt.ItemDataRole.UserRole + 1
_ROLE_SUBTITLE = Qt.ItemDataRole.UserRole + 2
_KIND_RECORD = "record"


class HistoryTreeItemDelegate(QStyledItemDelegate):
    """绘制 VNote 风格的历史记录行。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon = make_history_icon()
        self._row_height = 28
        self._line_x = 12
        self._icon_size = 16
        self._h_padding = 8

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, widget)

        rect = option.rect
        center_y = rect.center().y()
        line_x = rect.left() + self._line_x
        icon_left = rect.left() + 28
        icon_rect = rect.adjusted(0, 0, 0, 0)
        icon_rect.setLeft(icon_left)
        icon_rect.setWidth(self._icon_size)
        icon_rect.setTop(rect.top() + (rect.height() - self._icon_size) // 2)
        icon_rect.setHeight(self._icon_size)

        pen = QPen(Qt.GlobalColor.gray)
        pen.setWidthF(1.0)
        pen.setDashPattern([1.0, 2.0])
        painter.setPen(pen)
        is_last = index.row() == index.model().rowCount(index.parent()) - 1
        vertical_bottom = center_y if is_last else rect.bottom()
        painter.drawLine(line_x, rect.top(), line_x, vertical_bottom)
        painter.drawLine(line_x, center_y, icon_rect.left() - 4, center_y)

        if not self._icon.isNull():
            mode = QIcon.Mode.Selected if option.state & QStyle.StateFlag.State_Selected else QIcon.Mode.Normal
            self._icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter, mode)

        text_rect = rect
        text_rect.setLeft(icon_rect.right() + self._h_padding)
        text_rect.setRight(rect.right() - self._h_padding)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        elided = option.fontMetrics.elidedText(str(text), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.setPen(option.palette.text().color())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        hint = super().sizeHint(option, index)
        return QSize(min(hint.width(), 220), self._row_height)


class HistoryTreeWidget(QTreeWidget):
    """紧凑显示当前笔记本记录的树形控件。"""

    record_selected = Signal(str)
    rename_requested = Signal(str)
    move_requested = Signal(list, str)
    open_folder_requested = Signal(str)
    delete_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HistoryTree")
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(16)
        self.setUniformRowHeights(True)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setItemDelegate(HistoryTreeItemDelegate(self))
        self._notebooks: list[dict] = []
        self._records_by_key: dict[str, HistoryRecord] = {}
        self.itemClicked.connect(self._on_item_clicked)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def render(
        self,
        notebooks: list[dict],
        records: list[HistoryRecord],
        subtitle_for_record: Callable[[HistoryRecord], str],
    ) -> None:
        """渲染当前笔记本下的历史记录。"""
        self.clear()
        self._notebooks = [dict(item) for item in notebooks]
        self._records_by_key = {record.record_key: record for record in records}
        for record in records:
            subtitle = subtitle_for_record(record)
            item = QTreeWidgetItem([record.display_name])
            item.setToolTip(0, record.display_name)
            item.setData(0, _ROLE_KIND, _KIND_RECORD)
            item.setData(0, _ROLE_VALUE, record.record_key)
            item.setData(0, _ROLE_SUBTITLE, subtitle)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled & ~Qt.ItemFlag.ItemIsDropEnabled)
            self.addTopLevelItem(item)

    def select_record(self, record_key: str) -> bool:
        """按 record_key 选中树中的记录。"""
        item = self._item_for_record_key(record_key)
        if item is None:
            self.setCurrentItem(None)
            return False
        if item.isSelected():
            self.setCurrentItem(item, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
        else:
            self.setCurrentItem(item)
        return True

    def selected_record_keys(self) -> list[str]:
        """返回当前选中的记录键，顺序与列表一致。"""
        selected = [
            str(item.data(0, _ROLE_VALUE) or "")
            for item in self.selectedItems()
            if item.data(0, _ROLE_KIND) == _KIND_RECORD
        ]
        return [
            str(item.data(0, _ROLE_VALUE) or "")
            for item in self._record_items()
            if str(item.data(0, _ROLE_VALUE) or "") in selected
        ]

    def update_subtitles(self, subtitle_for_record: Callable[[HistoryRecord], str]) -> None:
        """刷新记录提示文本。"""
        for item in self._record_items():
            record_key = str(item.data(0, _ROLE_VALUE) or "")
            record = self._records_by_key.get(record_key)
            if record is not None:
                subtitle = subtitle_for_record(record)
                item.setToolTip(0, record.display_name)
                item.setData(0, _ROLE_SUBTITLE, subtitle)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item.data(0, _ROLE_KIND) == _KIND_RECORD:
            self.record_selected.emit(str(item.data(0, _ROLE_VALUE) or ""))

    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None or item.data(0, _ROLE_KIND) != _KIND_RECORD:
            return
        if not item.isSelected():
            self.clearSelection()
            item.setSelected(True)
            self.setCurrentItem(item, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
        record_keys = self.selected_record_keys()
        if not record_keys:
            return
        records = [self._records_by_key[key] for key in record_keys if key in self._records_by_key]
        if not records:
            return
        menu = QMenu(self)
        rename_action = None
        open_action = None
        if len(records) == 1:
            rename_action = menu.addAction("重命名")
        move_menu = menu.addMenu("移动")
        move_actions = {}
        for notebook in self._notebooks:
            notebook_id = str(notebook.get("id") or "")
            if notebook_id and any(record.notebook_id != notebook_id for record in records):
                action = move_menu.addAction(str(notebook.get("name") or notebook_id))
                move_actions[action] = notebook_id
        if len(records) == 1:
            open_action = menu.addAction("打开文件位置")
            menu.addSeparator()
        delete_action = menu.addAction("删除")
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if rename_action is not None and chosen == rename_action:
            self.rename_requested.emit(record_keys[0])
        elif open_action is not None and chosen == open_action:
            self.open_folder_requested.emit(record_keys[0])
        elif chosen == delete_action:
            self.delete_requested.emit(record_keys)
        elif chosen in move_actions:
            self.move_requested.emit(record_keys, move_actions[chosen])

    def _item_for_record_key(self, record_key: str) -> QTreeWidgetItem | None:
        for item in self._record_items():
            if item.data(0, _ROLE_VALUE) == record_key:
                return item
        return None

    def _record_items(self) -> list[QTreeWidgetItem]:
        items: list[QTreeWidgetItem] = []
        for index in range(self.topLevelItemCount()):
            items.append(self.topLevelItem(index))
        return items
