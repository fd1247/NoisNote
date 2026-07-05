"""录音控制弹窗和状态浮层。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class RecordingDialog(QDialog):
    """主界面中间显示的录音控制窗口。"""

    def __init__(self, controls: dict[str, QWidget], parent=None):
        super().__init__(parent)
        self.setWindowTitle("录音")
        self.setMinimumSize(440, 360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("录音")
        title.setObjectName("DetailTitle")
        layout.addWidget(title)

        for key in (
            "capture_mode",
            "system_device",
            "microphone_device",
            "device_label",
            "duration",
            "level",
        ):
            widget = controls.get(key)
            if widget is not None:
                layout.addWidget(widget)

        self.wave_label = QLabel("▁▃▆▇▆▃▁")
        self.wave_label.setObjectName("RecordingWave")
        self.wave_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.wave_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.start_stop_button = QPushButton("开始录音")
        self.start_stop_button.setObjectName("PrimaryButton")
        actions.addWidget(self.start_stop_button)
        layout.addLayout(actions)

    def sync_recording_state(self, is_recording: bool) -> None:
        self.start_stop_button.setText("结束录音" if is_recording else "开始录音")
        self.start_stop_button.setObjectName("DangerButton" if is_recording else "PrimaryButton")
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
