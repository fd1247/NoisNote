"""主窗口侧边栏 UI 构造。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget
from PySide6.QtWidgets import QHBoxLayout, QLineEdit

from .widgets.history_tree import HistoryTreeWidget


@dataclass(frozen=True)
class HistorySidebarControls:
    """历史侧边栏控件引用。"""

    history_search: QLineEdit
    history_filter_button: QPushButton
    history_tree: HistoryTreeWidget
    empty_history_label: QLabel


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
    select_history_item: Callable[[object], None],
) -> tuple[QFrame, HistorySidebarControls]:
    """创建主界面历史侧边栏。"""
    sidebar = QFrame(parent)
    sidebar.setObjectName("Sidebar")
    sidebar.setMinimumWidth(220)
    layout = QVBoxLayout(sidebar)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    title = QLabel("历史记录")
    title.setObjectName("SectionTitle")

    search_row = QHBoxLayout()
    search_row.setContentsMargins(0, 0, 0, 0)
    search_row.setSpacing(8)
    history_search = QLineEdit()
    history_search.setObjectName("HistorySearchBox")
    history_search.setPlaceholderText("搜索历史记录")
    history_filter_button = QPushButton()
    history_filter_button.setObjectName("HistoryFilterButton")
    history_filter_button.setIcon(make_icon("filter"))
    history_filter_button.setIconSize(QSize(17, 17))
    history_filter_button.setToolTip("筛选历史记录")
    history_filter_button.setFixedWidth(40)
    search_row.addWidget(history_search, stretch=1)
    search_row.addWidget(history_filter_button)

    history_tree = HistoryTreeWidget()
    history_tree.record_selected.connect(lambda record_key: select_history_item(record_key))

    empty_history_label = QLabel("暂无录音")
    empty_history_label.setObjectName("Muted")
    empty_history_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    layout.addWidget(title)
    layout.addLayout(search_row)
    layout.addWidget(history_tree, stretch=1)
    layout.addWidget(empty_history_label)

    controls = HistorySidebarControls(
        history_search=history_search,
        history_filter_button=history_filter_button,
        history_tree=history_tree,
        empty_history_label=empty_history_label,
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
