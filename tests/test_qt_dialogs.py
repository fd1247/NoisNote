from __future__ import annotations

import inspect

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QPushButton

from src.ui.widgets.dialogs import _ConfirmDialog, confirm_without_icon


def test_confirm_dialog_default_button_texts_are_confirm_and_cancel() -> None:
    signature = inspect.signature(confirm_without_icon)

    assert signature.parameters["confirm_text"].default == "确认"
    assert signature.parameters["cancel_text"].default == "取消"


def test_confirm_dialog_arrow_keys_move_focus_between_buttons() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = _ConfirmDialog()
    try:
        confirm = QPushButton("确认", dialog)
        cancel = QPushButton("取消", dialog)
        confirm.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        cancel.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        dialog.confirm_button = confirm
        dialog.cancel_button = cancel
        dialog.show()
        confirm.setFocus(Qt.FocusReason.OtherFocusReason)
        app.processEvents()

        right = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        dialog.keyPressEvent(right)
        app.processEvents()
        assert cancel.hasFocus()

        left = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
        dialog.keyPressEvent(left)
        app.processEvents()
        assert confirm.hasFocus()
    finally:
        dialog.close()
        app.processEvents()
