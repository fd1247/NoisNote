"""录音控制弹窗和状态浮层。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget


class RecordingDialog(QDialog):
    """承载原录音页布局的录音控制窗口。"""

    def __init__(self, recording_page: QWidget, start_stop_button: QPushButton, parent=None):
        super().__init__(parent)
        self.setWindowTitle("录音")
        self.setMinimumSize(440, 360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(recording_page)
        recording_page.show()
        self.recording_page = recording_page
        self.start_stop_button = start_stop_button

    def showEvent(self, event) -> None:
        self.recording_page.show()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.recording_page.hide()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self.recording_page.hide()
        super().closeEvent(event)

    def sync_recording_state(self, is_recording: bool) -> None:
        self.start_stop_button.setText("结束录音" if is_recording else "开始录音")
        self.start_stop_button.setObjectName("DangerButton" if is_recording else "RecordButton")
        self.start_stop_button.style().unpolish(self.start_stop_button)
        self.start_stop_button.style().polish(self.start_stop_button)


class RecordingStatusPopup(QFrame):
    """录音按钮 hover 时显示的轻量状态浮层。"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setObjectName("RecordingStatusPopup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        self.device_label = QLabel("")
        self.duration_label = QLabel("")
        layout.addWidget(self.device_label)
        layout.addWidget(self.duration_label)

    def update_status(self, device: str, duration: str) -> None:
        self.device_label.setText(device)
        self.duration_label.setText(duration)
