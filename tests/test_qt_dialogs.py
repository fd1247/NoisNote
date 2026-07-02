from __future__ import annotations

import inspect
from datetime import datetime, timezone

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QPushButton, QWidget

from src.app.update import UpdateInfo
from src.ui.widgets.dialogs import (
    _ConfirmDialog,
    _add_confirm_buttons,
    _add_field,
    _make_message_label,
    _prepare_dialog,
    confirm_without_icon,
)
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
        dialog._register_focus_buttons([confirm, cancel])
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

        right_on_button = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(confirm, right_on_button)
        app.processEvents()
        assert cancel.hasFocus()
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


def test_confirm_dialog_is_positioned_before_show() -> None:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    dialog = _ConfirmDialog(parent)
    try:
        parent.setGeometry(120, 90, 520, 360)
        parent.show()
        app.processEvents()

        content = _prepare_dialog(dialog, parent, "删除")
        content.addWidget(_make_message_label("确定删除吗?"))
        _add_confirm_buttons(dialog, content, "确认", "取消")
        dialog.setMinimumWidth(292)
        dialog.prepare_for_display(parent)

        assert dialog.pos() != QPoint(0, 0)
        assert abs(dialog.frameGeometry().center().x() - parent.frameGeometry().center().x()) <= 2
        assert abs(dialog.frameGeometry().center().y() - parent.frameGeometry().center().y()) <= 2

        dialog.show()
        app.processEvents()
    finally:
        dialog.close()
        parent.close()
        app.processEvents()


def test_confirm_dialog_uses_native_dialog_backend(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    captured: dict[str, object] = {}

    def fake_run_modal(self, parent=None):
        captured["dialog"] = self
        self.prepare_for_display(parent)
        captured["pos"] = self.pos()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_ConfirmDialog, "run_modal", fake_run_modal)

    parent = QWidget()
    try:
        parent.setGeometry(120, 90, 520, 360)
        parent.show()
        app.processEvents()

        assert confirm_without_icon(parent, "删除", "确定删除吗?", confirm_text="确认", cancel_text="取消")
        dialog = captured["dialog"]
        assert isinstance(dialog, _ConfirmDialog)
        assert dialog.isWindow()
        assert captured["pos"] != QPoint(0, 0)
    finally:
        parent.close()
        app.processEvents()


def test_confirm_dialog_run_modal_uses_open_instead_of_exec(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = _ConfirmDialog()
    content = _prepare_dialog(dialog, None, "删除")
    content.addWidget(_make_message_label("确定删除吗?"))
    _add_confirm_buttons(dialog, content, "确认", "取消")
    opened = {"value": False}

    def forbidden_exec(self):
        raise AssertionError("run_modal should not call exec()")

    def fake_open():
        opened["value"] = True
        dialog.accept()

    monkeypatch.setattr(_ConfirmDialog, "exec", forbidden_exec)
    monkeypatch.setattr(dialog, "open", fake_open)

    try:
        result = dialog.run_modal(None)
        app.processEvents()
        assert result == QDialog.DialogCode.Accepted
        assert opened["value"] is True
    finally:
        dialog.close()
        app.processEvents()
