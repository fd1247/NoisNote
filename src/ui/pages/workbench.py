"""主工作台菜单、工具栏和任务区。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QPoint, QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QMenu,
    QProgressBar,
    QScrollArea,
    QApplication,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QPushButton,
)

from ...tasks import AppTask
from ..widgets.history_item import ElidedLabel


_SVG_DIR = Path(__file__).resolve().parents[2] / "assets" / "svg"
_QUEUE_TASK_MIME = "application/x-noisnote-queued-task-id"


@dataclass(frozen=True)
class WorkbenchToolbarControls:
    """快捷工具栏控件引用。"""

    toolbar: QToolBar
    record_button: QToolButton
    import_audio_button: QToolButton
    remote_import_button: QToolButton
    export_button: QToolButton
    settings_button: QToolButton


@dataclass(frozen=True)
class TaskActionSpec:
    """任务项标题行中的操作按钮。"""

    text: str
    callback: Callable[[], None]
    tooltip: str = ""
    icon_name: str = ""
    danger: bool = False
    prominent: bool = False


class TaskSectionWidget(QFrame):
    """任务面板中的可折叠分组。"""

    def __init__(self, title: str):
        super().__init__()
        self._base_title = title
        self.setObjectName("TaskSection")

        section_layout = QVBoxLayout(self)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(6)

        self.title_button = QToolButton()
        self.title_button.setObjectName("TaskSectionTitle")
        self.title_button.setCheckable(True)
        self.title_button.setChecked(True)
        self.title_button.setArrowType(Qt.ArrowType.DownArrow)
        self.title_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.title_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.title_button.setText(f"{title}（0）")
        self.title_button.toggled.connect(self._set_expanded)
        self.header_layout = QHBoxLayout()
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(4)
        self.header_layout.addWidget(self.title_button)
        section_layout.addLayout(self.header_layout)

        self.body = QFrame(self)
        self.body.setObjectName("TaskSectionBody")
        self.list_layout = QVBoxLayout(self.body)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        _add_empty_task_hint(self.list_layout)
        section_layout.addWidget(self.body)

    def set_count(self, count: int) -> None:
        self.title_button.setText(f"{self._base_title}（{count}）")

    def _set_expanded(self, expanded: bool) -> None:
        self.title_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.body.setVisible(expanded)


class TaskItemWidget(QFrame):
    """任务列表项，负责标题省略、双击查看和排队拖放。"""

    def __init__(
        self,
        task: AppTask,
        *,
        message: str,
        actions: tuple[TaskActionSpec, ...],
        view_callback: Callable[[], None],
        queued_drop_callback: Callable[[str, str, bool], None] | None = None,
        reserve_message_space: bool = False,
        status_icon_name: str = "",
        progress_percent: int | None = None,
    ):
        super().__init__()
        self.task_id = task.task_id
        self._view_callback = view_callback
        self._queued_drop_callback = queued_drop_callback
        self._drag_start_pos: QPoint | None = None
        self._dragging = False
        self._pending_drop: tuple[str, bool] | None = None
        self._title_text = task.title or task.record_id or task.record_key or "任务"
        self._actions = actions
        self._reserve_message_space = reserve_message_space
        self._status_icon_name = status_icon_name
        self._has_progress_row = progress_percent is not None
        self.drag_handle_button: QToolButton | None = None
        self.message_label: QLabel | None = None
        self.progress_bar: QProgressBar | None = None
        self.progress_percent_label: QLabel | None = None
        self._drag_preview_widget: QFrame | None = None
        self._drop_placeholder_widget: QFrame | None = None
        self.setObjectName("TaskItem")
        self.setAcceptDrops(queued_drop_callback is not None)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        box = QVBoxLayout(self)
        box.setContentsMargins(8, 7, 8, 7)
        box.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        prominent_actions = tuple(action for action in actions if action.prominent)
        regular_actions = tuple(action for action in actions if not action.prominent)

        if queued_drop_callback is not None:
            self.drag_handle_button = _make_task_drag_handle_button()
            self.drag_handle_button.installEventFilter(self)
            title_row.addWidget(self.drag_handle_button)

        self.title_label = ElidedLabel(self._title_text)
        self.title_label.setObjectName("TaskItemTitle")
        self.title_label.installEventFilter(self)
        title_row.addWidget(self.title_label, stretch=1)

        if status_icon_name:
            title_row.addWidget(_make_task_status_icon_label(status_icon_name))

        for spec in regular_actions:
            if spec.icon_name:
                title_row.addWidget(_make_task_icon_button(spec))
            else:
                title_row.addWidget(_make_task_text_button(spec))

        if message or reserve_message_space:
            self.message_label = QLabel(message or " ")
            self.message_label.setObjectName("Muted")
            self.message_label.setWordWrap(True)
            self.message_label.setTextFormat(Qt.TextFormat.PlainText)
            self.message_label.setMinimumWidth(0)
            self.message_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.message_label.installEventFilter(self)
            if prominent_actions:
                content_row = QHBoxLayout()
                content_row.setContentsMargins(0, 0, 0, 0)
                content_row.setSpacing(4)
                text_column = QVBoxLayout()
                text_column.setContentsMargins(0, 0, 0, 0)
                text_column.setSpacing(4)
                text_column.addLayout(title_row)
                text_column.addWidget(self.message_label)
                if progress_percent is not None:
                    text_column.addLayout(self._make_progress_row(progress_percent))
                content_row.addLayout(text_column, stretch=1)

                action_row = QHBoxLayout()
                action_row.setContentsMargins(0, 0, 0, 0)
                action_row.setSpacing(4)
                for spec in prominent_actions:
                    action_row.addWidget(_make_task_icon_button(spec))
                content_row.addLayout(action_row)
                box.addLayout(content_row)
            else:
                box.addLayout(title_row)
                box.addWidget(self.message_label)
                if progress_percent is not None:
                    box.addLayout(self._make_progress_row(progress_percent))
        else:
            for spec in prominent_actions:
                title_row.addWidget(_make_task_icon_button(spec))
            box.addLayout(title_row)
            if progress_percent is not None:
                box.addLayout(self._make_progress_row(progress_percent))

    def _make_progress_row(self, percent: int) -> QHBoxLayout:
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(6)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("TaskProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(max(0, min(100, int(percent))))
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.progress_bar.installEventFilter(self)
        self.progress_percent_label = QLabel(f"{self.progress_bar.value()}%")
        self.progress_percent_label.setObjectName("TaskProgressPercent")
        self.progress_percent_label.setMinimumWidth(32)
        self.progress_percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.progress_percent_label.installEventFilter(self)
        progress_row.addWidget(self.progress_bar, stretch=1)
        progress_row.addWidget(self.progress_percent_label)
        return progress_row

    def can_update_in_place(
        self,
        task: AppTask,
        *,
        actions: tuple[TaskActionSpec, ...],
        message: str,
        queued_drop_enabled: bool,
        reserve_message_space: bool,
        status_icon_name: str,
        progress_percent: int | None,
    ) -> bool:
        message_row_needed = bool(message or reserve_message_space)
        return (
            self.task_id == task.task_id
            and self._action_signature(self._actions) == self._action_signature(actions)
            and (self._queued_drop_callback is not None) == queued_drop_enabled
            and self._reserve_message_space == reserve_message_space
            and self._status_icon_name == status_icon_name
            and self._has_progress_row == (progress_percent is not None)
            and (self.message_label is not None) == message_row_needed
        )

    def update_content(
        self,
        task: AppTask,
        *,
        message: str,
        progress_percent: int | None,
        view_callback: Callable[[], None],
    ) -> None:
        title = task.title or task.record_id or task.record_key or "任务"
        if title != self._title_text:
            self._title_text = title
            self.title_label.set_full_text(title)
        self._view_callback = view_callback
        if self.message_label is not None:
            self.message_label.setText(message or " ")
        if self.progress_bar is not None and self.progress_percent_label is not None and progress_percent is not None:
            value = max(0, min(100, int(progress_percent)))
            self.progress_bar.setValue(value)
            self.progress_percent_label.setText(f"{value}%")

    @staticmethod
    def _action_signature(actions: tuple[TaskActionSpec, ...]) -> tuple[tuple[str, str, str, bool], ...]:
        return tuple((action.text, action.tooltip, action.icon_name, action.prominent) for action in actions)

    def eventFilter(self, watched, event) -> bool:
        if watched is not self.drag_handle_button:
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self._view_task()
                return True
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self._view_task()
                return True
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.MouseButtonDblClick:
            self._view_task()
            return True
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._clear_other_drag_previews()
            self._drag_start_pos = event.globalPosition().toPoint()
            self.drag_handle_button.grabMouse()
            return True
        if event.type() == QEvent.Type.MouseMove and self._start_drag_if_ready(
            event.globalPosition().toPoint(),
            event.buttons(),
        ):
            return True
        if event.type() == QEvent.Type.MouseButtonRelease:
            if self._dragging:
                self._commit_drag_reorder()
            else:
                self._clear_drag_preview()
            self._drag_start_pos = None
            return True
        return super().eventFilter(watched, event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._view_task()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._view_task()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)

    def _start_drag_if_ready(self, current_pos: QPoint, buttons: Qt.MouseButton) -> bool:
        if self._queued_drop_callback is None or self._drag_start_pos is None:
            return False
        if not buttons & Qt.MouseButton.LeftButton:
            return False
        if self._dragging:
            self._preview_drag_position(current_pos)
            return True
        distance = (current_pos - self._drag_start_pos).manhattanLength()
        if distance < QApplication.startDragDistance():
            return False
        self._clear_other_drag_previews()
        self._dragging = True
        self._sync_dragging_state()
        self._show_drag_preview(current_pos)
        self.hide()
        self._preview_drag_position(current_pos)
        return True

    def _preview_drag_position(self, global_pos: QPoint) -> bool:
        self._move_drag_preview(global_pos)
        target_info = self._drop_target_at_global_position(global_pos)
        if target_info is None:
            self._pending_drop = None
            self._hide_drop_placeholder()
            return False
        target, insert_after = target_info
        self._pending_drop = (target.task_id, insert_after)
        self._show_drop_placeholder(target, insert_after)
        return True

    def _commit_drag_reorder(self) -> bool:
        pending = self._pending_drop
        self._clear_drag_preview()
        if self._queued_drop_callback is None or pending is None:
            return False
        target_task_id, insert_after = pending
        self._queued_drop_callback(self.task_id, target_task_id, insert_after)
        return True

    def is_dragging(self) -> bool:
        return self._dragging

    def _clear_drag_preview(self) -> None:
        self._pending_drop = None
        self._dragging = False
        self.show()
        self._sync_dragging_state()
        self._hide_drag_preview()
        self._hide_drop_placeholder()
        self._release_drag_mouse()

    def _release_drag_mouse(self) -> None:
        if self.drag_handle_button is not None and QWidget.mouseGrabber() is self.drag_handle_button:
            self.drag_handle_button.releaseMouse()

    def _clear_other_drag_previews(self) -> None:
        window = self.window()
        if window is not None:
            for preview in window.findChildren(QFrame, "TaskDragPreview"):
                if preview is not self._drag_preview_widget:
                    preview.hide()
        parent = self.parentWidget()
        if parent is not None:
            for item in parent.findChildren(TaskItemWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
                if item is self:
                    continue
                item._pending_drop = None
                item._dragging = False
                item.show()
                item._sync_dragging_state()
                item._hide_drag_preview()
                item._hide_drop_placeholder()
                item._release_drag_mouse()

    def _sync_dragging_state(self) -> None:
        self.setProperty("dragging", self._dragging)
        self.style().unpolish(self)
        self.style().polish(self)

    def _show_drag_preview(self, global_pos: QPoint) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        preview = self._drag_preview()
        preview.setFixedSize(min(self.width(), parent.width()), self.height())
        preview.show()
        preview.raise_()
        self._move_drag_preview(global_pos)

    def _move_drag_preview(self, global_pos: QPoint) -> None:
        preview = self._drag_preview_widget
        parent = preview.parentWidget() if preview is not None else None
        if preview is None or parent is None or preview.isHidden():
            return
        list_parent = self.parentWidget()
        if list_parent is None:
            return
        local_pos = parent.mapFromGlobal(global_pos)
        list_x = parent.mapFromGlobal(list_parent.mapToGlobal(QPoint(0, 0))).x()
        x = max(0, list_x - 16)
        y = local_pos.y() - preview.height() // 2
        preview.move(x, y)
        preview.raise_()

    def _hide_drag_preview(self) -> None:
        if self._drag_preview_widget is not None:
            self._drag_preview_widget.hide()

    def _drag_preview(self) -> QFrame:
        if self._drag_preview_widget is not None:
            return self._drag_preview_widget
        list_parent = self.parentWidget()
        parent = list_parent.window() if list_parent is not None else None
        preview = QFrame(parent)
        preview.setObjectName("TaskDragPreview")
        preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(preview)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(4)
        drag_icon = QLabel(preview)
        drag_icon.setObjectName("TaskDragPreviewIcon")
        drag_icon.setFixedSize(22, 22)
        drag_icon.setPixmap(_asset_icon("拖动.svg").pixmap(14, 14))
        drag_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(drag_icon)
        title = ElidedLabel(self._title_text)
        title.setObjectName("TaskItemTitle")
        layout.addWidget(title, stretch=1)
        for spec in self._actions:
            if not spec.icon_name:
                continue
            icon = QLabel(preview)
            icon.setObjectName("TaskDragPreviewIcon")
            icon.setFixedSize(22, 22)
            icon.setPixmap(_asset_icon(spec.icon_name).pixmap(14, 14))
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon)
        shadow = QGraphicsDropShadowEffect(preview)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(15, 23, 42, 70))
        preview.setGraphicsEffect(shadow)
        preview.hide()
        self._drag_preview_widget = preview
        return preview

    def _show_drop_placeholder(self, target: TaskItemWidget, insert_after: bool) -> None:
        parent = self.parentWidget()
        if parent is None or parent.layout() is None:
            return
        placeholder = self._drop_placeholder()
        layout = parent.layout()
        current_index = layout.indexOf(placeholder)
        if current_index >= 0:
            layout.takeAt(current_index)
        target_index = layout.indexOf(target)
        if target_index < 0:
            return
        insert_index = target_index + (1 if insert_after else 0)
        placeholder.setFixedHeight(max(self.height(), 1))
        layout.insertWidget(insert_index, placeholder)
        placeholder.show()

    def _hide_drop_placeholder(self) -> None:
        placeholder = self._drop_placeholder(create=False)
        if placeholder is not None:
            parent = placeholder.parentWidget()
            layout = parent.layout() if parent is not None else None
            if layout is not None:
                index = layout.indexOf(placeholder)
                if index >= 0:
                    layout.takeAt(index)
            placeholder.hide()

    def _drop_placeholder(self, *, create: bool = True) -> QFrame | None:
        parent = self.parentWidget()
        if parent is None:
            return None
        if self._drop_placeholder_widget is not None:
            return self._drop_placeholder_widget
        for widget in parent.findChildren(QFrame, "TaskDropPlaceholder", Qt.FindChildOption.FindDirectChildrenOnly):
            self._drop_placeholder_widget = widget
            return widget
        if not create:
            return None
        placeholder = QFrame(parent)
        placeholder.setObjectName("TaskDropPlaceholder")
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.setContentsMargins(0, 0, 0, 0)
        placeholder_layout.setSpacing(0)
        indicator = QFrame(placeholder)
        indicator.setObjectName("TaskDropIndicator")
        indicator.setFixedHeight(3)
        placeholder_layout.addWidget(indicator)
        placeholder_layout.addStretch(1)
        placeholder.hide()
        self._drop_placeholder_widget = placeholder
        return placeholder

    def _drop_target_at_global_position(self, global_pos: QPoint) -> tuple[TaskItemWidget, bool] | None:
        parent = self.parentWidget()
        layout = parent.layout() if parent is not None else None
        if parent is None or layout is None:
            return None
        local_y = parent.mapFromGlobal(global_pos).y()
        last_task: TaskItemWidget | None = None
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is self or not isinstance(widget, TaskItemWidget) or widget.isHidden():
                continue
            last_task = widget
            if local_y <= widget.y() + widget.height() / 2:
                return widget, False
        if last_task is None:
            return None
        return last_task, True

    def dragEnterEvent(self, event) -> None:
        if self._can_accept_queue_drop(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._can_accept_queue_drop(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if not self._can_accept_queue_drop(event.mimeData()):
            super().dropEvent(event)
            return
        source_id = bytes(event.mimeData().data(_QUEUE_TASK_MIME)).decode("utf-8")
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        insert_after = position.y() > self.height() / 2
        self._queued_drop_callback(source_id, self.task_id, insert_after)
        event.acceptProposedAction()

    def _can_accept_queue_drop(self, mime: QMimeData) -> bool:
        if self._queued_drop_callback is None or not mime.hasFormat(_QUEUE_TASK_MIME):
            return False
        source_id = bytes(mime.data(_QUEUE_TASK_MIME)).decode("utf-8")
        return bool(source_id and source_id != self.task_id)

    def _view_task(self) -> None:
        self._view_callback()


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
    """创建三段式任务管理面板。"""
    panel = QFrame(parent)
    panel.setObjectName("TaskPanel")
    panel.setMinimumWidth(260)

    layout = QVBoxLayout(panel)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)

    parent.task_panel_title = QLabel("任务管理")
    parent.task_panel_title.setObjectName("NotebookSectionTitle")
    layout.addWidget(parent.task_panel_title)

    scroll_area = QScrollArea(panel)
    scroll_area.setObjectName("TaskPanelScroll")
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QFrame.Shape.NoFrame)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    content = QWidget(scroll_area)
    content.setObjectName("TaskPanelContent")
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(12)

    parent.running_task_section = _add_task_section(content_layout, "处理中")
    parent.queued_task_section = _add_task_section(content_layout, "排队中")
    parent.completed_task_section = _add_task_section(content_layout, "已处理")
    parent.task_queue_resume_button = QToolButton()
    parent.task_queue_resume_button.setObjectName("TaskSectionActionButton")
    parent.task_queue_resume_button.setText("恢复队列")
    parent.task_queue_resume_button.setToolTip("恢复队列")
    parent.task_queue_resume_button.setIcon(_asset_icon("重试.svg"))
    parent.task_queue_resume_button.setIconSize(QSize(16, 16))
    parent.task_queue_resume_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    parent.task_queue_resume_button.clicked.connect(parent.resume_task_queue)
    parent.task_queue_resume_button.hide()
    parent.queued_task_section.header_layout.addWidget(parent.task_queue_resume_button)
    parent.running_task_title = parent.running_task_section.title_button
    parent.queued_task_title = parent.queued_task_section.title_button
    parent.completed_task_title = parent.completed_task_section.title_button
    parent.running_task_body = parent.running_task_section.body
    parent.queued_task_body = parent.queued_task_section.body
    parent.completed_task_body = parent.completed_task_section.body
    parent.running_task_list = parent.running_task_section.list_layout
    parent.queued_task_list = parent.queued_task_section.list_layout
    parent.completed_task_list = parent.completed_task_section.list_layout
    content_layout.addStretch(1)

    scroll_area.setWidget(content)
    layout.addWidget(scroll_area, stretch=1)
    return panel


def _add_task_section(layout: QVBoxLayout, title: str) -> TaskSectionWidget:
    """创建任务区段并返回标题与列表布局引用。"""
    section = TaskSectionWidget(title)
    layout.addWidget(section)
    return section


def _add_empty_task_hint(layout: QVBoxLayout) -> None:
    """为任务列表填充默认空态。"""
    layout.addStretch(1)


def _make_toolbar_button(icon: QIcon, tooltip: str, callback: Callable[[], None]) -> QToolButton:
    button = QToolButton()
    button.setObjectName("ToolbarIconButton")
    button.setIcon(icon)
    button.setIconSize(QSize(18, 18))
    button.setToolTip(tooltip)
    button.setText("")
    button.clicked.connect(callback)
    return button


def _asset_icon(svg_name: str) -> QIcon:
    svg_path = _SVG_DIR / svg_name
    return QIcon(str(svg_path)) if svg_path.exists() else QIcon()


def _make_task_icon_button(spec: TaskActionSpec) -> QToolButton:
    button = QToolButton()
    button.setObjectName("TaskIconButton")
    button.setIcon(_asset_icon(spec.icon_name))
    size = 30 if spec.prominent else 22
    icon_size = 18 if spec.prominent else 14
    button.setIconSize(QSize(icon_size, icon_size))
    button.setFixedSize(size, size)
    button.setProperty("prominent", spec.prominent)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    button.setToolTip(spec.tooltip or spec.text)
    button.clicked.connect(lambda _checked=False, callback=spec.callback: callback())
    return button


def _make_task_drag_handle_button() -> QToolButton:
    button = QToolButton()
    button.setObjectName("TaskDragHandleButton")
    button.setIcon(_asset_icon("拖动.svg"))
    button.setIconSize(QSize(14, 14))
    button.setFixedSize(22, 22)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    button.setToolTip("拖动排序")
    return button


def _make_task_status_icon_label(icon_name: str) -> QLabel:
    label = QLabel()
    label.setObjectName("TaskStatusIcon")
    label.setFixedSize(18, 18)
    label.setPixmap(_asset_icon(icon_name).pixmap(QSize(16, 16)))
    label.setToolTip("已完成")
    return label


def _make_task_text_button(spec: TaskActionSpec) -> QPushButton:
    button = QPushButton(spec.text)
    button.setObjectName("TaskMiniButton")
    button.setToolTip(spec.tooltip)
    button.clicked.connect(lambda _checked=False, callback=spec.callback: callback())
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
