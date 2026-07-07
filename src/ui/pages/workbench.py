"""主工作台菜单、工具栏和任务区。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QLabel, QFrame, QMenu, QToolBar, QToolButton, QVBoxLayout, QWidget


@dataclass(frozen=True)
class WorkbenchToolbarControls:
    """快捷工具栏控件引用。"""

    toolbar: QToolBar
    record_button: QToolButton
    import_audio_button: QToolButton
    remote_import_button: QToolButton
    export_button: QToolButton
    settings_button: QToolButton


def build_quick_toolbar(
    parent: QWidget,
    make_icon: Callable[[str], QIcon],
    *,
    record: Callable[[], None],
    import_audio: Callable[[], None],
    remote_import: Callable[[], None],
    export_result: Callable[[str], None],
    settings: Callable[[], None],
) -> WorkbenchToolbarControls:
    """创建仅显示图标的快捷操作工具栏。"""
    toolbar = QToolBar(parent)
    toolbar.setObjectName("QuickToolbar")
    toolbar.setMovable(False)
    toolbar.setFloatable(False)
    toolbar.setIconSize(QSize(18, 18))

    record_button = _make_toolbar_button(make_icon("record"), "录音", record)
    import_audio_button = _make_toolbar_button(make_icon("import"), "导入音视频", import_audio)
    remote_import_button = _make_toolbar_button(make_icon("link"), "从链接导入", remote_import)
    export_button = _make_toolbar_button(make_icon("export"), "导出", lambda: None)
    export_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    export_button.setMenu(_build_export_menu(export_button, export_result))
    settings_button = _make_toolbar_button(make_icon("settings"), "设置", settings)

    for button in (
        record_button,
        import_audio_button,
        remote_import_button,
        export_button,
        settings_button,
    ):
        toolbar.addWidget(button)

    return WorkbenchToolbarControls(
        toolbar=toolbar,
        record_button=record_button,
        import_audio_button=import_audio_button,
        remote_import_button=remote_import_button,
        export_button=export_button,
        settings_button=settings_button,
    )


def install_workbench_menus(
    window,
    *,
    record: Callable[[], None],
    import_audio: Callable[[], None],
    remote_import: Callable[[], None],
    export_result: Callable[[str], None],
    new_notebook: Callable[[], None],
    manage_notebooks: Callable[[], None],
    settings: Callable[[], None],
    check_update: Callable[[], None],
    toggle_quick_toolbar: Callable[[bool], None],
    toggle_history: Callable[[bool], None],
    toggle_playback: Callable[[bool], None],
    toggle_tasks: Callable[[bool], None],
) -> dict[str, QAction]:
    """安装主菜单并返回视图菜单 action 引用。"""
    menu_bar = window.menuBar()
    menu_bar.setObjectName("WorkbenchMenuBar")
    menu_bar.clear()

    file_menu = menu_bar.addMenu("文件")
    file_menu.addAction("录音", record)
    file_menu.addAction("导入音视频", import_audio)
    file_menu.addAction("从链接导入", remote_import)

    notebook_menu = menu_bar.addMenu("笔记本")
    notebook_menu.addAction("新建笔记本", new_notebook)
    notebook_menu.addAction("管理笔记本", manage_notebooks)

    export_menu = menu_bar.addMenu("导出")
    _add_export_actions(export_menu, export_result)

    view_menu = menu_bar.addMenu("视图")
    quick_action = _add_toggle_action(view_menu, "快捷操作区域", toggle_quick_toolbar)
    history_action = _add_toggle_action(view_menu, "历史记录区域", toggle_history)
    playback_action = _add_toggle_action(view_menu, "音频播放区域", toggle_playback)
    task_action = _add_toggle_action(view_menu, "任务管理区域", toggle_tasks)

    help_menu = menu_bar.addMenu("帮助")
    help_menu.addAction("检查更新", check_update)
    help_menu.addAction("设置", settings)

    return {
        "quick_toolbar": quick_action,
        "history": history_action,
        "playback": playback_action,
        "tasks": task_action,
    }


def build_task_panel(parent: QWidget) -> QFrame:
    """创建任务管理占位区。"""
    panel = QFrame(parent)
    panel.setObjectName("TaskPanel")
    panel.setMinimumWidth(220)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(8)
    title = QLabel("任务")
    title.setObjectName("SectionTitle")
    empty = QLabel("暂无任务")
    empty.setObjectName("Muted")
    empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title)
    layout.addWidget(empty, stretch=1)
    return panel


def _make_toolbar_button(icon: QIcon, tooltip: str, callback: Callable[[], None]) -> QToolButton:
    button = QToolButton()
    button.setObjectName("ToolbarIconButton")
    button.setIcon(icon)
    button.setIconSize(QSize(18, 18))
    button.setToolTip(tooltip)
    button.setText("")
    button.clicked.connect(callback)
    return button


def _build_export_menu(parent: QWidget, export_result: Callable[[str], None]) -> QMenu:
    menu = QMenu(parent)
    _add_export_actions(menu, export_result)
    return menu


def _add_export_actions(menu: QMenu, export_result: Callable[[str], None]) -> None:
    menu.addAction("转录文本 (.txt)", lambda: export_result("txt"))
    menu.addAction("逐句时间轴 (.srt)", lambda: export_result("srt"))
    menu.addAction("总结内容 (.md)", lambda: export_result("markdown"))


def _add_toggle_action(menu: QMenu, text: str, callback: Callable[[bool], None]) -> QAction:
    action = QAction(text, menu)
    action.setCheckable(True)
    action.setChecked(True)
    action.toggled.connect(callback)
    menu.addAction(action)
    return action
