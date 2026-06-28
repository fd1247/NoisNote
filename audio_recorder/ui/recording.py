"""录音页 UI 构造。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ..audio import CaptureMode


@dataclass(frozen=True)
class RecordingPageControls:
    """录音页控件引用。"""

    record_button: QPushButton
    capture_mode_combo: QComboBox
    system_device_combo: QComboBox
    microphone_device_combo: QComboBox
    system_device_widget: QWidget
    microphone_device_widget: QWidget
    duration_label: QLabel
    level_bar: QProgressBar
    level_text_label: QLabel
    record_device_label: QLabel
    recording_hint_label: QLabel


def build_recording_page(
    parent: QWidget,
    make_icon: Callable[[str], QIcon],
    toggle_recording: Callable[[], None],
    capture_mode_changed: Callable[[], None],
    device_selection_changed: Callable[[], None],
) -> tuple[QWidget, RecordingPageControls]:
    """创建录音页。"""
    page = QWidget(parent)
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 20, 0, 20)
    layout.setSpacing(16)
    layout.addStretch(1)

    record_button = QPushButton("开始录音")
    record_button.setObjectName("RecordButton")
    record_button.setIcon(make_icon("record_light"))
    record_button.setMinimumWidth(150)
    record_button.setAutoDefault(False)
    record_button.setDefault(False)
    record_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    record_button.clicked.connect(toggle_recording)

    # 录音源选择行
    capture_row = QHBoxLayout()
    capture_row.setSpacing(8)
    capture_label = QLabel("录音源")
    capture_label.setObjectName("Muted")
    capture_mode_combo = QComboBox()
    capture_mode_combo.addItem("系统声音", CaptureMode.SYSTEM.value)
    capture_mode_combo.addItem("麦克风", CaptureMode.MICROPHONE.value)
    capture_mode_combo.currentIndexChanged.connect(lambda _index=0: capture_mode_changed())
    capture_row.addStretch(1)
    capture_row.addWidget(capture_label)
    capture_row.addWidget(capture_mode_combo)
    capture_row.addStretch(1)

    # 系统声设备选择行（包装在 QWidget 中以便整行隐藏）
    system_device_widget = QWidget()
    system_device_row = QHBoxLayout(system_device_widget)
    system_device_row.setContentsMargins(0, 0, 0, 0)
    system_device_row.setSpacing(8)
    system_device_label = QLabel("系统声：")
    system_device_label.setObjectName("Muted")
    system_device_combo = QComboBox()
    system_device_combo.setMinimumWidth(200)
    system_device_combo.currentIndexChanged.connect(lambda _index=0: device_selection_changed())
    system_device_row.addStretch(1)
    system_device_row.addWidget(system_device_label)
    system_device_row.addWidget(system_device_combo)
    system_device_row.addStretch(1)

    # 麦克风设备选择行（包装在 QWidget 中以便整行隐藏）
    microphone_device_widget = QWidget()
    mic_device_row = QHBoxLayout(microphone_device_widget)
    mic_device_row.setContentsMargins(0, 0, 0, 0)
    mic_device_row.setSpacing(8)
    mic_device_label = QLabel("麦克风声：")
    mic_device_label.setObjectName("Muted")
    microphone_device_combo = QComboBox()
    microphone_device_combo.setMinimumWidth(200)
    microphone_device_combo.currentIndexChanged.connect(lambda _index=0: device_selection_changed())
    mic_device_row.addStretch(1)
    mic_device_row.addWidget(mic_device_label)
    mic_device_row.addWidget(microphone_device_combo)
    mic_device_row.addStretch(1)

    duration_label = QLabel("00:00:00")
    duration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    duration_label.setObjectName("TimerLabel")

    level_bar = QProgressBar()
    level_bar.setRange(0, 100)
    level_bar.setValue(0)
    level_bar.setTextVisible(False)
    level_bar.setMaximumWidth(360)

    level_text_label = QLabel("")
    level_text_label.setObjectName("Muted")
    level_text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    record_device_label = QLabel("录音设备：初始化中")
    record_device_label.setObjectName("Muted")
    record_device_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    recording_hint_label = QLabel("准备捕获系统声音")
    recording_hint_label.setObjectName("Muted")
    recording_hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    layout.addWidget(record_button, alignment=Qt.AlignmentFlag.AlignCenter)
    layout.addLayout(capture_row)
    layout.addWidget(system_device_widget)
    layout.addWidget(microphone_device_widget)
    layout.addWidget(duration_label)
    layout.addWidget(level_bar, alignment=Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(level_text_label)
    layout.addWidget(record_device_label)
    layout.addWidget(recording_hint_label)
    layout.addStretch(2)

    controls = RecordingPageControls(
        record_button=record_button,
        capture_mode_combo=capture_mode_combo,
        system_device_combo=system_device_combo,
        microphone_device_combo=microphone_device_combo,
        system_device_widget=system_device_widget,
        microphone_device_widget=microphone_device_widget,
        duration_label=duration_label,
        level_bar=level_bar,
        level_text_label=level_text_label,
        record_device_label=record_device_label,
        recording_hint_label=recording_hint_label,
    )
    return page, controls
