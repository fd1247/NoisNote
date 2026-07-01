"""Qt 通用弹框辅助函数。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget


@dataclass(frozen=True)
class DialogButtonSpec:
    """通用弹框按钮配置。"""

    text: str
    object_name: str
    callback: Callable[[], None]
    active: bool = False


class _ConfirmDialog(QDialog):
    """无图标确认弹框，左右方向键可在确认/取消按钮间切换焦点。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.confirm_button: QPushButton | None = None
        self.cancel_button: QPushButton | None = None
        self._focus_buttons: list[QPushButton] = []

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Left:
            self._move_button_focus(-1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Right:
            self._move_button_focus(1)
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.FocusIn and watched in self._focus_buttons:
            self._set_active_button(watched)
        return super().eventFilter(watched, event)

    def _register_focus_buttons(self, buttons: list[QPushButton]) -> None:
        self._focus_buttons = buttons
        for button in self._focus_buttons:
            button.installEventFilter(self)
        active_button = next((button for button in self._focus_buttons if button.property("active") is True), None)
        if active_button is not None:
            active_button.setFocus(Qt.FocusReason.OtherFocusReason)
            self._set_active_button(active_button)

    def _move_button_focus(self, step: int) -> None:
        if not self._focus_buttons and self.confirm_button and self.cancel_button:
            self._register_focus_buttons([self.confirm_button, self.cancel_button])
        if not self._focus_buttons:
            return
        active_index = 0
        for index, button in enumerate(self._focus_buttons):
            if button.hasFocus() or button.property("active") is True:
                active_index = index
                break
        target = self._focus_buttons[(active_index + step) % len(self._focus_buttons)]
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        self._set_active_button(target)

    def _set_active_button(self, button: QPushButton) -> None:
        for candidate in self._focus_buttons:
            candidate.setProperty("active", candidate is button)
            candidate.style().unpolish(candidate)
            candidate.style().polish(candidate)


def _prepare_dialog(dialog: QDialog, parent: QWidget | None, title: str) -> QVBoxLayout:
    dialog.setObjectName("ConfirmDialog")
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    if parent is not None:
        dialog.setWindowIcon(parent.windowIcon())

    content = QVBoxLayout(dialog)
    content.setContentsMargins(34, 18, 34, 14)
    content.setSpacing(18)
    return content


def _make_message_label(text: str) -> QLabel:
    message_label = QLabel(text)
    message_label.setObjectName("ConfirmDialogMessage")
    message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    message_label.setWordWrap(True)
    return message_label


def _make_field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("ConfirmDialogFieldLabel")
    label.setAlignment(Qt.AlignmentFlag.AlignLeft)
    return label


def _add_field(content: QVBoxLayout, label_text: str, field: QWidget) -> None:
    field_layout = QVBoxLayout()
    field_layout.setContentsMargins(0, 0, 0, 0)
    field_layout.setSpacing(6)
    field_layout.addWidget(_make_field_label(label_text))
    field_layout.addWidget(field)
    content.addLayout(field_layout)


def primary_button_spec(text: str, callback: Callable[[], None], active: bool = False) -> DialogButtonSpec:
    """创建主按钮配置。"""
    return DialogButtonSpec(text, "ConfirmDialogPrimaryButton", callback, active)


def secondary_button_spec(text: str, callback: Callable[[], None], active: bool = False) -> DialogButtonSpec:
    """创建次按钮配置。"""
    return DialogButtonSpec(text, "ConfirmDialogCancelButton", callback, active)


def _make_dialog_button(spec: DialogButtonSpec) -> QPushButton:
    button = QPushButton(spec.text)
    button.setObjectName(spec.object_name)
    button.setFixedSize(92, 38)
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    button.setAutoDefault(False)
    button.setDefault(False)
    button.setProperty("active", spec.active)
    button.clicked.connect(spec.callback)
    return button


def add_dialog_buttons(
    dialog: _ConfirmDialog,
    content: QVBoxLayout,
    specs: list[DialogButtonSpec],
) -> list[QPushButton]:
    """向对话框添加居中按钮行，并注册统一的焦点切换。"""
    buttons = QHBoxLayout()
    buttons.setContentsMargins(0, 0, 0, 0)
    buttons.setSpacing(16)
    buttons.addStretch(1)

    created_buttons = [_make_dialog_button(spec) for spec in specs]
    for button in created_buttons:
        buttons.addWidget(button)
    buttons.addStretch(1)

    content.addLayout(buttons)
    dialog._register_focus_buttons(created_buttons)
    if created_buttons:
        dialog.confirm_button = created_buttons[0]
    if len(created_buttons) > 1:
        dialog.cancel_button = created_buttons[1]
    return created_buttons


def _add_confirm_buttons(
    dialog: _ConfirmDialog,
    content: QVBoxLayout,
    confirm_text: str,
    cancel_text: str,
) -> tuple[QPushButton, QPushButton]:
    confirm_button, cancel_button = add_dialog_buttons(
        dialog,
        content,
        [
            primary_button_spec(confirm_text, dialog.accept, active=True),
            secondary_button_spec(cancel_text, dialog.reject),
        ],
    )
    return confirm_button, cancel_button


def confirm_without_icon(
    parent: QWidget | None,
    title: str,
    text: str,
    confirm_text: str = "确认",
    cancel_text: str = "取消",
) -> bool:
    """显示不带内容区图标的确认弹框。"""
    dialog = _ConfirmDialog(parent)
    content = _prepare_dialog(dialog, parent, title)
    content.addWidget(_make_message_label(text))
    _add_confirm_buttons(dialog, content, confirm_text, cancel_text)
    dialog.setMinimumWidth(292)
    dialog.adjustSize()
    return dialog.exec() == QDialog.DialogCode.Accepted


def alert_without_icon(
    parent: QWidget | None,
    title: str,
    text: str,
    confirm_text: str = "确认",
) -> None:
    """显示不带内容区图标的提示弹框。"""
    dialog = _ConfirmDialog(parent)
    content = _prepare_dialog(dialog, parent, title)
    content.addWidget(_make_message_label(text))

    confirm_button = add_dialog_buttons(
        dialog,
        content,
        [primary_button_spec(confirm_text, dialog.accept, active=True)],
    )[0]
    dialog.setMinimumWidth(292)
    dialog.adjustSize()
    dialog.exec()


def prompt_text_without_icon(
    parent: QWidget | None,
    title: str,
    text: str,
    value: str = "",
    confirm_text: str = "确认",
    cancel_text: str = "取消",
) -> tuple[str, bool]:
    """显示不带内容区图标的文本输入弹框。"""
    dialog = _ConfirmDialog(parent)
    content = _prepare_dialog(dialog, parent, title)

    line_edit = QLineEdit(value)
    line_edit.setObjectName("ConfirmDialogInput")
    line_edit.setMinimumWidth(260)
    line_edit.selectAll()
    _add_field(content, text, line_edit)

    _add_confirm_buttons(dialog, content, confirm_text, cancel_text)
    dialog.setMinimumWidth(330)
    dialog.adjustSize()
    line_edit.setFocus(Qt.FocusReason.OtherFocusReason)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return line_edit.text(), accepted


def prompt_choice_without_icon(
    parent: QWidget | None,
    title: str,
    text: str,
    options: list[str],
    current: int = 0,
    confirm_text: str = "确认",
    cancel_text: str = "取消",
) -> tuple[str, bool]:
    """显示不带内容区图标的选项弹框。"""
    dialog = _ConfirmDialog(parent)
    content = _prepare_dialog(dialog, parent, title)

    combo = QComboBox()
    combo.setObjectName("ConfirmDialogCombo")
    combo.addItems(options)
    if options:
        combo.setCurrentIndex(max(0, min(current, len(options) - 1)))
    combo.setMinimumWidth(260)
    _add_field(content, text, combo)

    _add_confirm_buttons(dialog, content, confirm_text, cancel_text)
    dialog.setMinimumWidth(330)
    dialog.adjustSize()
    combo.setFocus(Qt.FocusReason.OtherFocusReason)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return combo.currentText(), accepted
