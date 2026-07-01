from __future__ import annotations

import inspect
from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

from src.app.update import UpdateInfo
from src.ui.widgets.dialogs import _ConfirmDialog, _add_confirm_buttons, _add_field, _prepare_dialog, confirm_without_icon
from src.ui.widgets.update_dialog import UpdateDialog


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


def test_update_dialog_pending_and_result_rows_are_aligned() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = UpdateDialog.pending(None, "1.0.0")
    try:
        assert dialog.windowTitle() == "检查更新"
        assert dialog.current_title.text() == "当前版本："
        assert dialog.current_value.text() == "1.0.0"
        assert dialog.latest_value.text() == "正在获取信息..."
        assert dialog.confirm_button.text() == "确认"
        assert dialog.release_button.text() == "查看发布"
        assert dialog.confirm_button.property("active") is True
        assert dialog.release_button.property("active") is False

        right = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        dialog.keyPressEvent(right)
        app.processEvents()
        assert dialog.confirm_button.property("active") is False
        assert dialog.release_button.property("active") is True

        dialog.set_update_info(
            UpdateInfo(
                has_update=True,
                latest_version="1.1.0",
                current_version="1.0.0",
                download_url="https://example.com/releases/1.1.0",
                release_notes="notes",
                check_time=datetime.now(timezone.utc),
            )
        )

        assert dialog.latest_value.text() == "1.1.0"

        dialog.set_update_info(
            UpdateInfo(
                has_update=False,
                latest_version="1.0.0",
                current_version="1.0.0",
                download_url="",
                release_notes="",
                check_time=datetime.now(timezone.utc),
            )
        )

        assert dialog.latest_value.text() == "获取最新版本信息失败"
    finally:
        dialog.close()
        app.processEvents()


def test_prompt_dialog_field_label_aligns_left_and_confirm_stays_active() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = _ConfirmDialog()
    try:
        content = _prepare_dialog(dialog, None, "重命名")
        line_edit = QLineEdit("meeting")
        _add_field(content, "记录名称：", line_edit)
        confirm, cancel = _add_confirm_buttons(dialog, content, "确认", "取消")
        dialog.show()
        line_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        app.processEvents()

        field_labels = [label for label in dialog.findChildren(QLabel) if label.objectName() == "ConfirmDialogFieldLabel"]
        assert len(field_labels) == 1
        assert field_labels[0].text() == "记录名称："
        assert field_labels[0].alignment() & Qt.AlignmentFlag.AlignLeft
        assert confirm.property("active") is True
        assert cancel.property("active") is False

        right = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        dialog.keyPressEvent(right)
        app.processEvents()
        assert confirm.property("active") is False
        assert cancel.property("active") is True
    finally:
        dialog.close()
        app.processEvents()
