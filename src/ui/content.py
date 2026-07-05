"""历史详情内容标签页 UI 构造。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QAction, QIcon, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpacerItem,
    QStackedWidget,
    QStyle,
    QStyleOptionComboBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


_SVG_DIR = Path(__file__).resolve().parents[1] / "assets" / "svg"


class SeekSlider(QSlider):
    """支持点击轨道直接跳转的播放进度条。"""

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            ratio = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            value = self.minimum() + round((self.maximum() - self.minimum()) * ratio)
            self.setValue(value)
            self.sliderMoved.emit(value)
            event.accept()
            return
        super().mousePressEvent(event)


class PlaybackRateCombo(QComboBox):
    """紧凑倍速按钮，弹出列表保持正常宽度并显示在按钮左上方。"""

    popup_width = 72

    def paintEvent(self, event) -> None:
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""

        painter = QPainter(self)
        self.style().drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option, painter, self)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.currentText())

    def showPopup(self) -> None:
        menu = QMenu(self)
        menu.setObjectName("PlayerRateMenu")
        menu.setMinimumWidth(self.popup_width)
        for index in range(self.count()):
            action = QAction(self.itemText(index), menu)
            action.setCheckable(True)
            action.setChecked(index == self.currentIndex())
            action.triggered.connect(lambda checked=False, row=index: self._set_popup_index(row))
            menu.addAction(action)

        popup_size = menu.sizeHint()
        popup_width = max(self.popup_width, popup_size.width())
        menu.setFixedWidth(popup_width)
        pos = self.mapToGlobal(QPoint(self.width() - popup_width, -popup_size.height()))
        self._rate_menu = menu
        menu.aboutToHide.connect(lambda: setattr(self, "_rate_menu", None))
        menu.popup(pos)

    def _set_popup_index(self, index: int) -> None:
        if 0 <= index < self.count():
            self.setCurrentIndex(index)


@dataclass(frozen=True)
class HistoryPageCallbacks:
    """历史详情页依赖的动作回调。"""

    set_result_tab: Callable[[str], None]
    manual_summarize: Callable[[], None]
    retry_transcription: Callable[[], None]
    copy_panel_text: Callable[[str], None]
    export_result: Callable[[str], None]
    seek_backward: Callable[[], None]
    toggle_playback: Callable[[], None]
    seek_forward: Callable[[], None]
    seek_playback: Callable[[int], None]
    set_playback_rate: Callable[[str], None]
    switch_to_timeline: Callable[[], None]


@dataclass(frozen=True)
class ContentTabsControls:
    """详情区标签页控件引用。"""

    result_stack: QStackedWidget
    transcript_tab_button: QPushButton
    timeline_tab_button: QPushButton
    summary_tab_button: QPushButton
    detail_title_label: QLabel
    detail_duration_label: QLabel
    detail_size_label: QLabel
    detail_status_label: QLabel
    detail_time_label: QLabel
    detail_processing_status_label: QLabel
    transcript_status: QLabel
    transcript_text: QPlainTextEdit
    transcript_copy_button: QPushButton
    retry_transcription_button: QPushButton
    timeline_status: QLabel
    timeline_text: QTextBrowser
    timeline_copy_button: QPushButton
    summary_status: QLabel
    summary_text: QTextBrowser
    summary_copy_button: QPushButton
    manual_summary_button: QPushButton
    export_button: QPushButton
    playback_widget: QFrame
    playback_back_button: QPushButton
    playback_play_button: QPushButton
    playback_forward_button: QPushButton
    playback_position_label: QLabel
    playback_duration_label: QLabel
    playback_slider: QSlider
    playback_rate_combo: QComboBox
    playback_cc_button: QPushButton


def build_history_page(
    parent: QWidget,
    callbacks: HistoryPageCallbacks,
) -> tuple[QWidget, ContentTabsControls]:
    """创建历史记录详情页。"""
    page = QWidget(parent)
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    detail_header = QFrame()
    detail_header.setObjectName("DetailHeader")
    detail_header_layout = QHBoxLayout(detail_header)
    detail_header_layout.setContentsMargins(0, 0, 0, 0)
    detail_header_layout.setSpacing(12)

    title_meta = QVBoxLayout()
    title_meta.setContentsMargins(0, 0, 0, 0)
    title_meta.setSpacing(8)
    detail_title_label = QLabel("请选择历史记录")
    detail_title_label.setObjectName("DetailTitle")

    meta_row = QHBoxLayout()
    meta_row.setContentsMargins(0, 0, 0, 0)
    meta_row.setSpacing(8)
    detail_duration_label = _build_meta_label("--:--")
    detail_size_label = _build_meta_label("--")
    detail_status_label = _build_meta_label("状态 --")
    detail_status_label.setObjectName("DetailStatusPill")
    detail_time_label = _build_meta_label("--")
    detail_processing_status_label = QLabel("")
    detail_processing_status_label.setObjectName("DetailProcessingStatus")
    detail_processing_status_label.setTextFormat(Qt.RichText)
    detail_processing_status_label.hide()
    meta_row.addWidget(detail_duration_label)
    meta_row.addWidget(_build_meta_separator())
    meta_row.addWidget(detail_size_label)
    meta_row.addWidget(_build_meta_separator())
    meta_row.addWidget(detail_time_label)
    meta_row.addWidget(detail_status_label)
    meta_row.addStretch(1)
    meta_row.addWidget(detail_processing_status_label)

    title_meta.addWidget(detail_title_label)
    title_meta.addLayout(meta_row)
    detail_header_layout.addLayout(title_meta, stretch=1)

    export_button = QPushButton("导出")
    export_button.setObjectName("SmallButton")
    export_button.setMenu(_build_export_menu(page, callbacks.export_result))
    detail_header_layout.addWidget(export_button, alignment=Qt.AlignmentFlag.AlignTop)

    panel = QFrame()
    panel.setObjectName("Panel")
    panel_layout = QVBoxLayout(panel)
    panel_layout.setContentsMargins(16, 12, 16, 16)
    panel_layout.setSpacing(10)

    tab_row = QHBoxLayout()
    tab_row.setContentsMargins(0, 0, 0, 0)
    tab_row.setSpacing(22)
    transcript_tab_button = _build_result_tab_button("转录文本", "transcript", callbacks.set_result_tab)
    timeline_tab_button = _build_result_tab_button("逐句时间轴", "timeline", callbacks.set_result_tab)
    summary_tab_button = _build_result_tab_button("总结内容", "summary", callbacks.set_result_tab)
    tab_row.addWidget(transcript_tab_button)
    tab_row.addWidget(timeline_tab_button)
    tab_row.addWidget(summary_tab_button)
    tab_row.addStretch(1)

    divider = QFrame()
    divider.setObjectName("ResultTabDivider")
    divider.setFrameShape(QFrame.Shape.HLine)
    divider.setFixedHeight(1)

    result_stack = QStackedWidget()
    transcript_page, transcript_controls = _build_result_page(
        "transcript",
        callbacks.manual_summarize,
        callbacks.retry_transcription,
        callbacks.copy_panel_text,
    )
    summary_page, summary_controls = _build_result_page(
        "summary",
        callbacks.manual_summarize,
        callbacks.retry_transcription,
        callbacks.copy_panel_text,
    )
    timeline_page, timeline_controls = _build_result_page(
        "timeline",
        callbacks.manual_summarize,
        callbacks.retry_transcription,
        callbacks.copy_panel_text,
    )
    result_stack.addWidget(transcript_page)
    result_stack.addWidget(timeline_page)
    result_stack.addWidget(summary_page)

    tab_section = QWidget()
    tab_section_layout = QVBoxLayout(tab_section)
    tab_section_layout.setContentsMargins(0, 0, 0, 0)
    tab_section_layout.setSpacing(0)
    tab_section_layout.addLayout(tab_row)
    tab_section_layout.addWidget(divider)

    panel_layout.addWidget(tab_section)
    panel_layout.addWidget(result_stack, stretch=1)
    playback_bar = _build_playback_bar(
        callbacks.seek_backward,
        callbacks.toggle_playback,
        callbacks.seek_forward,
        callbacks.seek_playback,
        callbacks.set_playback_rate,
        callbacks.switch_to_timeline,
    )
    (
        playback_widget,
        playback_back_button,
        playback_play_button,
        playback_forward_button,
        playback_position_label,
        playback_slider,
        playback_duration_label,
        playback_rate_combo,
        playback_cc_button,
    ) = playback_bar
    layout.addWidget(detail_header)
    layout.addWidget(panel, stretch=1)
    layout.addWidget(playback_widget)

    controls = ContentTabsControls(
        result_stack=result_stack,
        transcript_tab_button=transcript_tab_button,
        timeline_tab_button=timeline_tab_button,
        summary_tab_button=summary_tab_button,
        detail_title_label=detail_title_label,
        detail_duration_label=detail_duration_label,
        detail_size_label=detail_size_label,
        detail_status_label=detail_status_label,
        detail_time_label=detail_time_label,
        detail_processing_status_label=detail_processing_status_label,
        transcript_status=transcript_controls.status_label,
        transcript_text=cast(QPlainTextEdit, transcript_controls.text_edit),
        transcript_copy_button=transcript_controls.copy_button,
        retry_transcription_button=transcript_controls.action_button,
        timeline_status=timeline_controls.status_label,
        timeline_text=cast(QTextBrowser, timeline_controls.text_edit),
        timeline_copy_button=timeline_controls.copy_button,
        summary_status=summary_controls.status_label,
        summary_text=cast(QTextBrowser, summary_controls.text_edit),
        summary_copy_button=summary_controls.copy_button,
        manual_summary_button=summary_controls.action_button,
        export_button=export_button,
        playback_widget=playback_widget,
        playback_back_button=playback_back_button,
        playback_play_button=playback_play_button,
        playback_forward_button=playback_forward_button,
        playback_position_label=playback_position_label,
        playback_duration_label=playback_duration_label,
        playback_slider=playback_slider,
        playback_rate_combo=playback_rate_combo,
        playback_cc_button=playback_cc_button,
    )
    return page, controls


@dataclass(frozen=True)
class _ResultPageControls:
    """单个结果页控件引用。"""

    status_label: QLabel
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
    header.addWidget(status_label)
    header.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

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
    elif kind == "timeline":
        timeline_text = QTextBrowser()
        timeline_text.setObjectName("TimelineView")
        text_edit = timeline_text
    else:
        text_edit = QPlainTextEdit()
    text_edit.setReadOnly(True)
    text_edit.setPlaceholderText("内容会显示在这里")

    layout.addLayout(header)
    layout.addWidget(text_edit)

    return page, _ResultPageControls(
        status_label=status_label,
        text_edit=text_edit,
        copy_button=copy_button,
        action_button=action_button,
    )


def _build_meta_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("DetailMetaLabel")
    return label


def _build_meta_separator() -> QLabel:
    label = QLabel("|")
    label.setObjectName("DetailMetaSeparator")
    return label


def _build_playback_bar(
    seek_backward: Callable[[], None],
    toggle_playback: Callable[[], None],
    seek_forward: Callable[[], None],
    seek_playback: Callable[[int], None],
    set_playback_rate: Callable[[str], None],
    switch_to_timeline: Callable[[], None],
) -> tuple[QFrame, QPushButton, QPushButton, QPushButton, QLabel, QSlider, QLabel, QComboBox, QPushButton]:
    bar = QFrame()
    bar.setObjectName("PlayerBar")
    bar.setFixedHeight(62)
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(14, 8, 14, 8)
    layout.setSpacing(6)

    back_button = QPushButton()
    back_button.setObjectName("PlayerIconButton")
    back_button.setIcon(_asset_icon("快退15s.svg"))
    back_button.setIconSize(QSize(22, 22))
    back_button.setToolTip("后退 15 秒")
    back_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    back_button.setFixedSize(28, 28)
    back_button.clicked.connect(seek_backward)

    play_button = QPushButton()
    play_button.setObjectName("PlayerPlayButton")
    play_button.setIcon(_asset_icon("播放.svg"))
    play_button.setIconSize(QSize(18, 18))
    play_button.setToolTip("播放/暂停")
    play_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    play_button.setFixedSize(28, 28)
    play_button.clicked.connect(toggle_playback)

    forward_button = QPushButton()
    forward_button.setObjectName("PlayerIconButton")
    forward_button.setIcon(_asset_icon("快进15s.svg"))
    forward_button.setIconSize(QSize(22, 22))
    forward_button.setToolTip("前进 15 秒")
    forward_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    forward_button.setFixedSize(28, 28)
    forward_button.clicked.connect(seek_forward)

    position_label = QLabel("00:00")
    position_label.setObjectName("PlayerTime")
    duration_label = QLabel("00:00")
    duration_label.setObjectName("PlayerTime")

    slider = SeekSlider(Qt.Orientation.Horizontal)
    slider.setObjectName("PlayerSlider")
    slider.setRange(0, 0)
    slider.sliderMoved.connect(seek_playback)

    rate_combo = PlaybackRateCombo()
    rate_combo.setObjectName("PlayerRateCombo")
    rate_combo.setFixedWidth(38)
    rate_combo.setMinimumContentsLength(4)
    rate_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    rate_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    for value in ("0.5x", "1x", "1.5x", "2x"):
        rate_combo.addItem(value)
    rate_combo.setCurrentText("1x")
    rate_combo.currentTextChanged.connect(set_playback_rate)

    cc_button = QPushButton()
    cc_button.setObjectName("PlayerIconButton")
    cc_button.setIcon(_asset_icon("cc.svg"))
    cc_button.setIconSize(QSize(18, 18))
    cc_button.setToolTip("逐句时间轴")
    cc_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    cc_button.setFixedSize(28, 28)
    cc_button.clicked.connect(switch_to_timeline)

    transport_controls = QWidget()
    transport_controls.setObjectName("PlaybackTransport")
    transport_layout = QHBoxLayout(transport_controls)
    transport_layout.setContentsMargins(0, 0, 0, 0)
    transport_layout.setSpacing(6)
    transport_layout.addWidget(back_button)
    transport_layout.addWidget(play_button)
    transport_layout.addWidget(forward_button)

    playback_options = QWidget()
    playback_options.setObjectName("PlaybackOptions")
    playback_options_layout = QHBoxLayout(playback_options)
    playback_options_layout.setContentsMargins(0, 0, 0, 0)
    playback_options_layout.setSpacing(6)
    playback_options_layout.addWidget(rate_combo)
    playback_options_layout.addWidget(cc_button)

    layout.addWidget(transport_controls)
    layout.addSpacing(6)
    layout.addWidget(position_label)
    layout.addWidget(slider, stretch=1)
    layout.addWidget(duration_label)
    layout.addWidget(playback_options)
    return bar, back_button, play_button, forward_button, position_label, slider, duration_label, rate_combo, cc_button


def _asset_icon(name: str) -> QIcon:
    path = _SVG_DIR / name
    return QIcon(str(path)) if path.exists() else QIcon()


def _build_export_menu(parent: QWidget, export_callback: Callable[[str], None]) -> QMenu:
    """创建导出格式菜单。"""
    from PySide6.QtWidgets import QMenu

    menu = QMenu(parent)
    menu.setObjectName("ExportMenu")

    txt_action = QAction("导出为 TXT（原始转录文字）", parent)
    txt_action.setData("txt")
    txt_action.triggered.connect(lambda: export_callback("txt"))

    srt_action = QAction("导出为 SRT（字幕文件）", parent)
    srt_action.setData("srt")
    srt_action.triggered.connect(lambda: export_callback("srt"))

    md_action = QAction("导出为 Markdown（总结内容）", parent)
    md_action.setData("markdown")
    md_action.triggered.connect(lambda: export_callback("markdown"))

    menu.addAction(txt_action)
    menu.addAction(srt_action)
    menu.addAction(md_action)

    return menu
