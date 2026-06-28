"""Qt 通用弹框辅助函数。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class _ConfirmDialog(QDialog):
    """无图标确认弹框，左右方向键可在确认/取消按钮间切换焦点。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.confirm_button: QPushButton | None = None
        self.cancel_button: QPushButton | None = None

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._toggle_button_focus()
            event.accept()
            return
        super().keyPressEvent(event)

    def _toggle_button_focus(self) -> None:
        if not self.confirm_button or not self.cancel_button:
            return
        if self.confirm_button.hasFocus():
            self.cancel_button.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.confirm_button.setFocus(Qt.FocusReason.OtherFocusReason)


def confirm_without_icon(
    parent: QWidget | None,
    title: str,
    text: str,
    confirm_text: str = "确认",
    cancel_text: str = "取消",
) -> bool:
    """显示不带内容区图标的确认弹框。"""
    dialog = _ConfirmDialog(parent)
    dialog.setObjectName("ConfirmDialog")
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    if parent is not None:
        dialog.setWindowIcon(parent.windowIcon())

    content = QVBoxLayout(dialog)
    content.setContentsMargins(34, 18, 34, 14)
    content.setSpacing(18)

    message_label = QLabel(text)
    message_label.setObjectName("ConfirmDialogMessage")
    message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    message_label.setWordWrap(True)
    content.addWidget(message_label)

    buttons = QHBoxLayout()
    buttons.setContentsMargins(0, 0, 0, 0)
    buttons.setSpacing(10)
    buttons.addStretch(1)

    confirm_button = QPushButton(confirm_text)
    confirm_button.setObjectName("ConfirmDialogPrimaryButton")
    confirm_button.setFixedSize(82, 38)
    confirm_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    confirm_button.setAutoDefault(False)
    confirm_button.setDefault(False)
    confirm_button.clicked.connect(dialog.accept)
    buttons.addWidget(confirm_button)

    cancel_button = QPushButton(cancel_text)
    cancel_button.setObjectName("ConfirmDialogCancelButton")
    cancel_button.setFixedSize(82, 38)
    cancel_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    cancel_button.setAutoDefault(False)
    cancel_button.setDefault(False)
    cancel_button.clicked.connect(dialog.reject)
    buttons.addWidget(cancel_button)
    buttons.addStretch(1)

    dialog.confirm_button = confirm_button
    dialog.cancel_button = cancel_button
    content.addLayout(buttons)
    dialog.setMinimumWidth(292)
    dialog.adjustSize()
    confirm_button.setFocus(Qt.FocusReason.OtherFocusReason)
    return dialog.exec() == QDialog.DialogCode.Accepted
