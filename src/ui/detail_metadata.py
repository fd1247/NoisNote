"""历史记录详细信息弹窗。"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class DetailMetadataDialog(QDialog):
    """只读展示当前历史记录的元数据字段。"""

    def __init__(self, parent: QWidget | None, fields: Sequence[dict[str, str]]) -> None:
        super().__init__(parent)
        self.setWindowTitle("详细信息")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(16)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        for row, field in enumerate(fields):
            label = QLabel(str(field.get("label") or ""))
            label.setObjectName("DetailMetadataLabel")
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

            value = QLabel(str(field.get("value") or "--"))
            value.setObjectName("DetailMetadataValue")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)

        layout.addLayout(grid)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button:
            close_button.setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
