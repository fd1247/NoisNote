"""录音控制对话框。"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QPushButton, QVBoxLayout, QWidget


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
