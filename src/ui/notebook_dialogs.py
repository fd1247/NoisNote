"""笔记本新建和管理对话框。"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class NewNotebookDialog(QDialog):
    """新建笔记本输入框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建笔记本")
        self.setModal(True)
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(14)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(12)
        form.setColumnStretch(1, 1)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("输入笔记本名称")
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择根文件夹")
        self.browse_button = QPushButton("浏览")
        self.browse_button.setObjectName("SmallButton")
        self.browse_button.clicked.connect(self._browse)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(8)
        path_row.addWidget(self.path_edit, stretch=1)
        path_row.addWidget(self.browse_button)

        form.addWidget(QLabel("名称"), 0, 0)
        form.addWidget(self.name_edit, 0, 1)
        form.addWidget(QLabel("根文件夹"), 1, 0)
        form.addLayout(path_row, 1, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("SmallButton")
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button = QPushButton("新建")
        self.ok_button.setObjectName("PrimaryButton")
        self.ok_button.clicked.connect(self.accept)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.ok_button)

        root.addLayout(form)
        root.addLayout(actions)

    def values(self) -> tuple[str, Path]:
        """返回名称和根目录。"""
        return self.name_edit.text().strip(), Path(self.path_edit.text().strip()).expanduser()

    def _browse(self) -> None:
        path_text = QFileDialog.getExistingDirectory(self, "选择笔记本根文件夹")
        if path_text:
            self.path_edit.setText(path_text)
            if not self.name_edit.text().strip():
                self.name_edit.setText(Path(path_text).name or "笔记本")


class ManageNotebooksDialog(QDialog):
    """笔记本列表管理窗口，只允许修改名称。"""

    def __init__(self, notebooks: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理笔记本")
        self.setModal(True)
        self.setMinimumSize(760, 520)
        self._notebooks = [dict(item) for item in notebooks]
        self._original_names = {
            str(item.get("id") or ""): str(item.get("name") or "")
            for item in self._notebooks
        }
        self._name_labels: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        title = QLabel("笔记本")
        title.setObjectName("NotebookDialogTitle")
        count = QLabel(f"共 {len(self._notebooks)} 个")
        count.setObjectName("NotebookDialogCount")
        title_row.addWidget(title)
        title_row.addWidget(count)
        title_row.addStretch(1)

        subtitle = QLabel("管理笔记本名称和存储位置。根文件夹只读，可从这里打开查看。")
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)

        scroll = QScrollArea()
        scroll.setObjectName("NotebookManageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        list_host = QWidget()
        self.list_layout = QVBoxLayout(list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        for notebook in self._notebooks:
            self.list_layout.addWidget(self._make_row(notebook))
        self.list_layout.addStretch(1)
        scroll.setWidget(list_host)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("SmallButton")
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button = QPushButton("保存")
        self.ok_button.setObjectName("PrimaryButton")
        self.ok_button.setEnabled(False)
        self.ok_button.clicked.connect(self.accept)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.ok_button)

        root.addLayout(title_row)
        root.addWidget(subtitle)
        root.addWidget(scroll, stretch=1)
        root.addLayout(actions)

    def notebooks(self) -> list[dict]:
        """返回更新名称后的笔记本配置。"""
        return [dict(item) for item in self._notebooks]

    def _make_row(self, notebook: dict) -> QFrame:
        notebook_id = str(notebook.get("id") or "")
        name = str(notebook.get("name") or "笔记本")
        path = str(notebook.get("path") or "")

        row = QFrame()
        row.setObjectName("NotebookManageRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(14, 12, 12, 12)
        row_layout.setSpacing(12)

        text_block = QVBoxLayout()
        text_block.setContentsMargins(0, 0, 0, 0)
        text_block.setSpacing(5)
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(8)

        name_label = QLabel(name)
        name_label.setObjectName("NotebookManageName")
        name_label.setToolTip(name)
        self._name_labels[notebook_id] = name_label
        name_row.addWidget(name_label)
        if notebook_id == "default" or bool(notebook.get("is_default", False)):
            badge = QLabel("默认")
            badge.setObjectName("NotebookDefaultBadge")
            name_row.addWidget(badge)
        name_row.addStretch(1)

        path_label = QLabel(self._elide_path(path))
        path_label.setObjectName("NotebookManagePath")
        path_label.setToolTip(path)
        path_label.setMinimumHeight(20)

        text_block.addLayout(name_row)
        text_block.addWidget(path_label)

        open_button = QPushButton("打开")
        open_button.setObjectName("SmallButton")
        open_button.clicked.connect(lambda checked=False, target=path: self._open_path(target))
        rename_button = QPushButton("重命名")
        rename_button.setObjectName("SmallButton")
        rename_button.clicked.connect(lambda checked=False, item=notebook: self._rename_notebook(item))

        row_layout.addLayout(text_block, stretch=1)
        row_layout.addWidget(open_button)
        row_layout.addWidget(rename_button)
        return row

    def _rename_notebook(self, notebook: dict) -> None:
        current = str(notebook.get("name") or "笔记本")
        name, accepted = QInputDialog.getText(self, "重命名笔记本", "名称", text=current)
        if not accepted:
            return
        name = name.strip()
        if not name:
            return
        notebook["name"] = name
        notebook_id = str(notebook.get("id") or "")
        label = self._name_labels.get(notebook_id)
        if label is not None:
            label.setText(name)
            label.setToolTip(name)
        self._sync_dirty_state()

    def _sync_dirty_state(self) -> None:
        dirty = any(
            str(item.get("name") or "") != self._original_names.get(str(item.get("id") or ""), "")
            for item in self._notebooks
        )
        self.ok_button.setEnabled(dirty)

    def _open_path(self, path_text: str) -> None:
        path = Path(path_text).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))
        except OSError:
            QApplication.beep()

    def _elide_path(self, path_text: str) -> str:
        metrics = QFontMetrics(self.font())
        return metrics.elidedText(path_text, Qt.TextElideMode.ElideMiddle, 520)
