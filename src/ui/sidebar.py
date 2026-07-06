"""主窗口侧边栏 UI 构造。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .widgets.history_tree import HistoryTreeWidget


@dataclass(frozen=True)
class HistorySidebarControls:
    """历史侧边栏控件引用。"""

    notebook_selector: QComboBox
    history_tree: HistoryTreeWidget
    empty_history_label: QLabel


def build_history_sidebar(
    parent: QWidget,
    select_history_item: Callable[[object], None],
) -> tuple[QFrame, HistorySidebarControls]:
    """创建主界面历史侧边栏。"""
    sidebar = QFrame(parent)
    sidebar.setObjectName("Sidebar")
    sidebar.setMinimumWidth(220)
    layout = QVBoxLayout(sidebar)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    title = QLabel("笔记本")
    title.setObjectName("NotebookSectionTitle")

    notebook_selector = QComboBox()
    notebook_selector.setObjectName("NotebookSelector")
    notebook_selector.setToolTip("选择笔记本")
    notebook_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    notebook_selector.setMinimumContentsLength(8)
    notebook_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    history_tree = HistoryTreeWidget()
    history_tree.record_selected.connect(lambda record_key: select_history_item(record_key))

    empty_history_label = QLabel("暂无录音")
    empty_history_label.setObjectName("Muted")
    empty_history_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    layout.addWidget(title)
    layout.addWidget(notebook_selector)
    layout.addWidget(history_tree, stretch=1)
    layout.addWidget(empty_history_label)

    controls = HistorySidebarControls(
        notebook_selector=notebook_selector,
        history_tree=history_tree,
        empty_history_label=empty_history_label,
    )
    return sidebar, controls
