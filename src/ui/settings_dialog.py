"""独立设置窗口。"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget


class SettingsDialog(QDialog):
    """承载 SettingsPanel 的独立设置窗口。"""

    def __init__(
        self,
        panel: QWidget,
        section_changed: Callable[[str], None],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(920, 640)
        self._panel = panel
        self._section_changed = section_changed
        self.nav_buttons: dict[str, QPushButton] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        nav = QFrame(self)
        nav.setObjectName("SettingsDialogNav")
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(12, 12, 12, 12)
        nav_layout.setSpacing(8)

        for section, label in (
            ("general", "通用"),
            ("notebooks", "笔记本"),
            ("models", "模型"),
            ("hotwords", "热词"),
            ("shortcuts", "快捷键"),
        ):
            button = QPushButton(label)
            button.setObjectName("SidebarNavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, key=section: self.show_section(key))
            self.nav_buttons[section] = button
            nav_layout.addWidget(button)
        nav_layout.addStretch(1)

        root.addWidget(nav)
        root.addWidget(panel, stretch=1)

    def show_section(self, section: str) -> None:
        """切换设置窗口内的设置分类。"""
        self._section_changed(section)
        self.set_active_section(section)

    def set_active_section(self, section: str) -> None:
        """同步左侧导航选中态。"""
        for key, button in self.nav_buttons.items():
            button.setChecked(key == section)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)
