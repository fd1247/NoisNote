"""历史详情内容标签页 UI 构造。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class ContentTabsControls:
    """详情区标签页控件引用。"""

    result_stack: QStackedWidget
    transcript_tab_button: QPushButton
    timeline_tab_button: QPushButton
    summary_tab_button: QPushButton
    transcript_status: QLabel
    transcript_progress: QProgressBar
    transcript_text: QPlainTextEdit
    transcript_copy_button: QPushButton
    retry_transcription_button: QPushButton
    timeline_status: QLabel
    timeline_text: QPlainTextEdit
    timeline_copy_button: QPushButton
    summary_status: QLabel
    summary_progress: QProgressBar
    summary_text: QTextBrowser
    summary_copy_button: QPushButton
    manual_summary_button: QPushButton
    export_button: QPushButton


def build_history_page(
    parent: QWidget,
    set_result_tab: Callable[[str], None],
    manual_summarize: Callable[[], None],
    retry_transcription: Callable[[], None],
    copy_panel_text: Callable[[str], None],
    export_result: Callable[[], None],
) -> tuple[QWidget, ContentTabsControls]:
    """创建历史记录详情页。"""
    page = QWidget(parent)
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    panel = QFrame()
    panel.setObjectName("Panel")
    panel_layout = QVBoxLayout(panel)
    panel_layout.setContentsMargins(16, 12, 16, 16)
    panel_layout.setSpacing(10)

    tab_row = QHBoxLayout()
    tab_row.setContentsMargins(0, 0, 0, 0)
    tab_row.setSpacing(22)
    transcript_tab_button = _build_result_tab_button("转录文本", "transcript", set_result_tab)
    timeline_tab_button = _build_result_tab_button("逐句时间轴", "timeline", set_result_tab)
    summary_tab_button = _build_result_tab_button("总结内容", "summary", set_result_tab)
    tab_row.addWidget(transcript_tab_button)
    tab_row.addWidget(timeline_tab_button)
    tab_row.addWidget(summary_tab_button)
    tab_row.addStretch(1)
    export_button = QPushButton("导出")
    export_button.setObjectName("SmallButton")
    export_button.clicked.connect(export_result)
    tab_row.addWidget(export_button)

    divider = QFrame()
    divider.setObjectName("ResultTabDivider")
    divider.setFrameShape(QFrame.Shape.HLine)
    divider.setFixedHeight(1)

    result_stack = QStackedWidget()
    transcript_page, transcript_controls = _build_result_page(
        "transcript",
        manual_summarize,
        retry_transcription,
        copy_panel_text,
    )
    summary_page, summary_controls = _build_result_page(
        "summary",
        manual_summarize,
        retry_transcription,
        copy_panel_text,
    )
    timeline_page, timeline_controls = _build_result_page(
        "timeline",
        manual_summarize,
        retry_transcription,
        copy_panel_text,
    )
    result_stack.addWidget(transcript_page)
    result_stack.addWidget(timeline_page)
    result_stack.addWidget(summary_page)

    panel_layout.addLayout(tab_row)
    panel_layout.addWidget(divider)
    panel_layout.addWidget(result_stack, stretch=1)
    layout.addWidget(panel, stretch=1)

    controls = ContentTabsControls(
        result_stack=result_stack,
        transcript_tab_button=transcript_tab_button,
        timeline_tab_button=timeline_tab_button,
        summary_tab_button=summary_tab_button,
        transcript_status=transcript_controls.status_label,
        transcript_progress=transcript_controls.progress,
        transcript_text=cast(QPlainTextEdit, transcript_controls.text_edit),
        transcript_copy_button=transcript_controls.copy_button,
        retry_transcription_button=transcript_controls.action_button,
        timeline_status=timeline_controls.status_label,
        timeline_text=cast(QPlainTextEdit, timeline_controls.text_edit),
        timeline_copy_button=timeline_controls.copy_button,
        summary_status=summary_controls.status_label,
        summary_progress=summary_controls.progress,
        summary_text=cast(QTextBrowser, summary_controls.text_edit),
        summary_copy_button=summary_controls.copy_button,
        manual_summary_button=summary_controls.action_button,
        export_button=export_button,
    )
    return page, controls


@dataclass(frozen=True)
class _ResultPageControls:
    """单个结果页控件引用。"""

    status_label: QLabel
    progress: QProgressBar
    text_edit: QPlainTextEdit | QTextBrowser
    copy_button: QPushButton
    action_button: QPushButton


def _build_result_tab_button(
    title: str,
    kind: str,
    set_result_tab: Callable[[str], None],
) -> QPushButton:
    """创建结果区标签按钮。"""
    button = QPushButton(title)
    button.setObjectName("ResultTabButton")
    button.setCheckable(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(lambda checked=False, key=kind: set_result_tab(key))
    return button


def _build_result_page(
    kind: str,
    manual_summarize: Callable[[], None],
    retry_transcription: Callable[[], None],
    copy_panel_text: Callable[[str], None],
) -> tuple[QWidget, _ResultPageControls]:
    """创建转录或总结结果页。"""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    header = QHBoxLayout()
    status_label = QLabel("等待内容")
    status_label.setObjectName("Muted")
    progress = QProgressBar()
    progress.setRange(0, 0)
    progress.setTextVisible(False)
    progress.setMaximumWidth(180)
    progress.hide()
    header.addWidget(status_label)
    header.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
    header.addWidget(progress)

    if kind == "summary":
        action_button = QPushButton("手动总结")
        action_button.setObjectName("SuccessButton")
        action_button.clicked.connect(manual_summarize)
    elif kind == "transcript":
        action_button = QPushButton("重新转录")
        action_button.setObjectName("SmallButton")
        action_button.clicked.connect(retry_transcription)
    else:
        action_button = QPushButton("")
        action_button.setObjectName("SmallButton")
    action_button.hide()
    header.addWidget(action_button)

    copy_button = QPushButton("复制")
    copy_button.setObjectName("SmallButton")
    copy_button.clicked.connect(lambda: copy_panel_text(kind))
    copy_button.hide()
    header.addWidget(copy_button)

    if kind == "summary":
        summary_text = QTextBrowser()
        summary_text.setOpenExternalLinks(True)
        summary_text.setObjectName("MarkdownView")
        text_edit: QPlainTextEdit | QTextBrowser = summary_text
    else:
        text_edit = QPlainTextEdit()
    text_edit.setReadOnly(True)
    text_edit.setPlaceholderText("内容会显示在这里")

    layout.addLayout(header)
    layout.addWidget(text_edit)

    return page, _ResultPageControls(
        status_label=status_label,
        progress=progress,
        text_edit=text_edit,
        copy_button=copy_button,
        action_button=action_button,
    )
