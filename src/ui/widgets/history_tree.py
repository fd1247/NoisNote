"""按笔记本分组的历史记录树。"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QMenu, QTreeWidget, QTreeWidgetItem

from ...history.types import HistoryRecord

_ROLE_KIND = Qt.ItemDataRole.UserRole
_ROLE_VALUE = Qt.ItemDataRole.UserRole + 1
_ROLE_SUBTITLE = Qt.ItemDataRole.UserRole + 2
_KIND_NOTEBOOK = "notebook"
_KIND_RECORD = "record"


class HistoryTreeWidget(QTreeWidget):
    """紧凑显示笔记本和记录的树形控件。"""

    record_selected = Signal(str)
    rename_requested = Signal(str)
    move_requested = Signal(str, str)
    open_folder_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HistoryTree")
        self.setHeaderHidden(True)
        self.setIndentation(10)
        self.setUniformRowHeights(True)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
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
        """渲染笔记本和历史记录。"""
        self.clear()
        self._notebooks = [dict(item) for item in notebooks]
        self._records_by_key = {record.record_key: record for record in records}
        records_by_notebook: dict[str, list[HistoryRecord]] = {}
        for record in records:
            records_by_notebook.setdefault(record.notebook_id, []).append(record)

        for notebook in self._notebooks:
            notebook_id = str(notebook.get("id") or "")
            notebook_name = str(notebook.get("name") or "笔记本")
            root = QTreeWidgetItem([notebook_name])
            root.setData(0, _ROLE_KIND, _KIND_NOTEBOOK)
            root.setData(0, _ROLE_VALUE, notebook_id)
            root.setFlags(root.flags() | Qt.ItemFlag.ItemIsDropEnabled)
            self.addTopLevelItem(root)
            for record in records_by_notebook.get(notebook_id, []):
                subtitle = subtitle_for_record(record)
                child = QTreeWidgetItem([record.display_name])
                child.setToolTip(0, subtitle or str(record.record_dir))
                child.setData(0, _ROLE_KIND, _KIND_RECORD)
                child.setData(0, _ROLE_VALUE, record.record_key)
                child.setData(0, _ROLE_SUBTITLE, subtitle)
                child.setFlags(
                    (child.flags() | Qt.ItemFlag.ItemIsDragEnabled)
                    & ~Qt.ItemFlag.ItemIsDropEnabled
                )
                root.addChild(child)
            root.setExpanded(True)

    def select_record(self, record_key: str) -> bool:
        """按 record_key 选中树中的记录。"""
        item = self._item_for_record_key(record_key)
        if item is None:
            self.setCurrentItem(None)
            return False
        self.setCurrentItem(item)
        parent = item.parent()
        if parent is not None:
            parent.setExpanded(True)
        return True

    def update_subtitles(self, subtitle_for_record: Callable[[HistoryRecord], str]) -> None:
        """刷新记录提示文本。"""
        for item in self._record_items():
            record_key = str(item.data(0, _ROLE_VALUE) or "")
            record = self._records_by_key.get(record_key)
            if record is not None:
                subtitle = subtitle_for_record(record)
                item.setToolTip(0, subtitle or str(record.record_dir))
                item.setData(0, _ROLE_SUBTITLE, subtitle)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item.data(0, _ROLE_KIND) == _KIND_RECORD:
            self.record_selected.emit(str(item.data(0, _ROLE_VALUE) or ""))

    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None or item.data(0, _ROLE_KIND) != _KIND_RECORD:
            return
        record_key = str(item.data(0, _ROLE_VALUE) or "")
        record = self._records_by_key.get(record_key)
        menu = QMenu(self)
        rename_action = menu.addAction("重命名")
        move_menu = menu.addMenu("移动")
        move_actions = {}
        if record is not None:
            for notebook in self._notebooks:
                notebook_id = str(notebook.get("id") or "")
                if notebook_id and notebook_id != record.notebook_id:
                    action = move_menu.addAction(str(notebook.get("name") or notebook_id))
                    move_actions[action] = notebook_id
        open_action = menu.addAction("打开文件位置")
        menu.addSeparator()
        delete_action = menu.addAction("删除")
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen == rename_action:
            self.rename_requested.emit(record_key)
        elif chosen == open_action:
            self.open_folder_requested.emit(record_key)
        elif chosen == delete_action:
            self.delete_requested.emit(record_key)
        elif chosen in move_actions:
            self.move_requested.emit(record_key, move_actions[chosen])

    def mimeData(self, items: list[QTreeWidgetItem]) -> QMimeData:
        mime = super().mimeData(items)
        if items:
            item = items[0]
            if item.data(0, _ROLE_KIND) == _KIND_RECORD:
                mime.setText(str(item.data(0, _ROLE_VALUE) or ""))
        return mime

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        target = self.itemAt(event.position().toPoint())
        if target is not None and target.data(0, _ROLE_KIND) == _KIND_RECORD:
            target = target.parent()
        if target is not None and target.data(0, _ROLE_KIND) == _KIND_NOTEBOOK:
            record_key = event.mimeData().text()
            notebook_id = str(target.data(0, _ROLE_VALUE) or "")
            if record_key and notebook_id:
                self.move_requested.emit(record_key, notebook_id)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def _item_for_record_key(self, record_key: str) -> QTreeWidgetItem | None:
        for item in self._record_items():
            if item.data(0, _ROLE_VALUE) == record_key:
                return item
        return None

    def _record_items(self) -> list[QTreeWidgetItem]:
        items: list[QTreeWidgetItem] = []
        for root_index in range(self.topLevelItemCount()):
            root = self.topLevelItem(root_index)
            for child_index in range(root.childCount()):
                items.append(root.child(child_index))
        return items
