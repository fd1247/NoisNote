"""主窗口侧边栏 UI 构造。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget


@dataclass(frozen=True)
class HistorySidebarControls:
    """历史侧边栏控件引用。"""

    new_recording_button: QPushButton
    import_audio_button: QPushButton
    active_recording_button: QPushButton
    history_list: QListWidget
    empty_history_label: QLabel
    settings_button: QPushButton


@dataclass(frozen=True)
class SettingsSidebarControls:
    """设置侧边栏控件引用。"""

    back_button: QPushButton
    general_button: QPushButton
    models_button: QPushButton
    hotwords_button: QPushButton
    shortcuts_button: QPushButton


def build_history_sidebar(
    parent: QWidget,
    make_icon: Callable[[str], QIcon],
    new_recording: Callable[[], None],
    import_audio_recording: Callable[[], None],
    show_active_task: Callable[[], None],
    select_history_item: Callable[[object], None],
    show_settings: Callable[[], None],
) -> tuple[QFrame, HistorySidebarControls]:
    """创建主界面历史侧边栏。"""
    sidebar = QFrame(parent)
    sidebar.setObjectName("Sidebar")
    sidebar.setFixedWidth(240)
    layout = QVBoxLayout(sidebar)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    new_recording_button = QPushButton("创建新录音")
    new_recording_button.setObjectName("SidebarPrimaryButton")
    new_recording_button.setIcon(make_icon("record_light"))
    new_recording_button.clicked.connect(new_recording)

    import_audio_button = QPushButton("导入本地音视频")
    import_audio_button.setObjectName("SidebarSecondaryButton")
    import_audio_button.setIcon(make_icon("import"))
    import_audio_button.clicked.connect(import_audio_recording)

    active_recording_button = QPushButton("正在录音中")
    active_recording_button.setObjectName("SidebarRecordingButton")
    active_recording_button.setIcon(make_icon("record"))
    active_recording_button.clicked.connect(show_active_task)
    active_recording_button.hide()

    title = QLabel("历史记录")
    title.setObjectName("SectionTitle")

    history_list = QListWidget()
    history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    history_list.itemClicked.connect(select_history_item)

    empty_history_label = QLabel("暂无录音")
    empty_history_label.setObjectName("Muted")
    empty_history_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    settings_button = QPushButton("设置")
    settings_button.setObjectName("SidebarSettingsButton")
    settings_button.setIcon(make_icon("settings"))
    settings_button.clicked.connect(show_settings)

    layout.addWidget(new_recording_button)
    layout.addWidget(import_audio_button)
    layout.addWidget(active_recording_button)
    layout.addWidget(title)
    layout.addWidget(history_list, stretch=1)
    layout.addWidget(empty_history_label)
    layout.addWidget(settings_button)

    controls = HistorySidebarControls(
        new_recording_button=new_recording_button,
        import_audio_button=import_audio_button,
        active_recording_button=active_recording_button,
        history_list=history_list,
        empty_history_label=empty_history_label,
        settings_button=settings_button,
    )
    return sidebar, controls


def build_settings_sidebar(
    parent: QWidget,
    make_icon: Callable[[str], QIcon],
    hide_settings: Callable[[], None],
    show_settings_section: Callable[[str], None],
) -> tuple[QFrame, SettingsSidebarControls]:
    """创建设置页侧边栏。"""
    sidebar = QFrame(parent)
    sidebar.setObjectName("Sidebar")
    layout = QVBoxLayout(sidebar)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    back_button = QPushButton("返回应用")
    back_button.setObjectName("SidebarSettingsButton")
    back_button.setIcon(make_icon("back"))
    back_button.setIconSize(QSize(18, 18))
    back_button.clicked.connect(hide_settings)

    general_button = _make_settings_nav_button("通用", "general", make_icon, show_settings_section)
    models_button = _make_settings_nav_button("模型", "models", make_icon, show_settings_section)
    hotwords_button = _make_settings_nav_button("热词", "hotwords", make_icon, show_settings_section)
    shortcuts_button = _make_settings_nav_button("快捷键", "shortcuts", make_icon, show_settings_section)

    layout.addWidget(back_button)
    layout.addSpacing(8)
    layout.addWidget(general_button)
    layout.addWidget(models_button)
    layout.addWidget(hotwords_button)
    layout.addWidget(shortcuts_button)
    layout.addStretch(1)

    controls = SettingsSidebarControls(
        back_button=back_button,
        general_button=general_button,
        models_button=models_button,
        hotwords_button=hotwords_button,
        shortcuts_button=shortcuts_button,
    )
    return sidebar, controls


def _make_settings_nav_button(
    text: str,
    section: str,
    make_icon: Callable[[str], QIcon],
    show_settings_section: Callable[[str], None],
) -> QPushButton:
    """创建设置页导航按钮。"""
    button = QPushButton(text)
    button.setObjectName("SidebarNavButton")
    button.setCheckable(True)
    button.setIcon(make_icon(section))
    button.setIconSize(QSize(18, 18))
    button.clicked.connect(lambda checked=False, key=section: show_settings_section(key))
    return button
