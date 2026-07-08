"""Qt 样式定义。"""

from pathlib import Path


_ASSET_DIR = Path(__file__).resolve().parents[2] / "assets"
_COMBO_ARROW_PATH = (_ASSET_DIR / "svg" / "下拉.svg").as_posix()
_CHECK_MARK_PATH = (_ASSET_DIR / "svg" / "check-white.svg").as_posix()


APP_STYLESHEET = """
QMainWindow {
    background: #ffffff;
    color: #111827;
}
QDialog {
    background: #f7f7f4;
    color: #111827;
}
QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #111827;
}
QFrame#Sidebar {
    background: #f4f4ef;
    border-right: 1px solid #e3e3dc;
}
QFrame#AppHeader {
    background: #ffffff;
    border-bottom: 1px solid #e5e7eb;
}
QLabel#AppHeaderTitle {
    color: #111827;
    font-size: 16px;
    font-weight: 600;
}
QFrame#MainArea {
    background: #ffffff;
}
QStackedWidget {
    background: #ffffff;
    border: none;
}
QFrame#Panel {
    background: #ffffff;
    border: none;
    border-radius: 0;
}
QFrame#DetailHeader {
    background: #ffffff;
}
QFrame#DetailMetadataPanel {
    background: #ffffff;
    border-top: 1px solid #e5e7eb;
    border-bottom: 1px solid #e5e7eb;
    margin-top: 10px;
    padding-bottom: 12px;
}
QFrame#PlayerBar {
    background: #ffffff;
    border: none;
    border-radius: 0;
}
QFrame#PlaybackSeparator {
    background: #e5e7eb;
    border: none;
    min-height: 1px;
    max-height: 1px;
}
QFrame#ModelListPanel {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
}
QFrame#HotwordPanel {
    background: #ffffff;
    border: 1px solid #dfe5ee;
    border-radius: 8px;
}
QFrame#HotwordMetricCard {
    background: #ffffff;
    border: 1px solid #dfe5ee;
    border-radius: 8px;
}
QFrame#HistoryItem {
    background: transparent;
    border-radius: 8px;
}
QFrame#HistoryItem:hover {
    background: #ecece6;
}
QFrame#HistoryItem[selected="true"] {
    background: #e8eefc;
}
QLabel#HistoryIcon {
    border: none;
    background: transparent;
}
QLabel#HistoryTitle {
    color: #111827;
    font-size: 13px;
    font-weight: 400;
}
QLabel#HistoryTitle[selected="true"] {
    color: #111827;
    font-weight: 700;
}
QLabel#HistorySubtitle {
    color: #6b7280;
    font-size: 11px;
}
QLabel#HistorySubtitle[selected="true"] {
    color: #6b7280;
}
QLabel#ModelItemTitle {
    color: #111827;
    font-size: 13px;
    font-weight: 600;
}
QLabel#ModelItemSubtitle {
    color: #6b7280;
    font-size: 12px;
}
QLabel#Title {
    font-size: 20px;
    font-weight: 600;
}
QLabel#SectionTitle {
    font-size: 15px;
    font-weight: 400;
    color: #6b7280;
}
QLabel#NotebookSectionTitle {
    font-size: 13px;
    font-weight: 400;
    color: #111827;
}
QLabel#Muted {
    color: #6b7280;
}
QLabel#DetailTitle {
    color: #111827;
    font-size: 22px;
    font-weight: 700;
    max-height: 32px;
}
QLabel#DetailMetaLabel {
    color: #7a8496;
    font-size: 13px;
}
QLabel#DetailMetaSeparator {
    color: #7a8496;
    font-size: 13px;
}
QLabel#DetailProcessingStatus {
    color: #6b7280;
    font-size: 12px;
    font-weight: 600;
}
QLabel#DetailMetadataLabel {
    color: #6b7280;
    font-size: 13px;
    min-width: 88px;
}
QLabel#DetailMetadataValue {
    color: #111827;
    font-size: 13px;
    max-height: 20px;
}
QLabel#PlayerTime {
    color: #6b7280;
    min-width: 42px;
}
QLabel#PlayerNotice {
    color: #b45309;
    font-size: 12px;
    min-width: 112px;
}
QLabel#CopyNotice {
    color: #15803d;
    font-size: 12px;
    min-width: 96px;
}
QLabel#HotwordHeroTitle {
    color: #111827;
    font-size: 22px;
    font-weight: 700;
}
QLabel#HotwordHeroIcon {
    background: #eff6ff;
    border-radius: 15px;
    color: #2563eb;
    font-size: 13px;
    font-weight: 700;
}
QLabel#HotwordMetricIcon {
    background: #eff6ff;
    border-radius: 17px;
    color: #2563eb;
    font-size: 13px;
    font-weight: 700;
}
QLabel#HotwordMetricTitle {
    color: #374151;
    font-size: 12px;
    font-weight: 600;
}
QLabel#HotwordMetricValue {
    color: #2563eb;
    font-size: 24px;
    font-weight: 700;
}
QLabel#HotwordMetricSuffix {
    color: #4b5563;
    font-size: 14px;
    font-weight: 600;
}
QLabel#HotwordStatusPill,
QLabel#HotwordCountPill {
    background: #f8fafc;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    color: #374151;
    font-weight: 600;
    padding: 6px 10px;
}
QLabel#ConfirmDialogMessage {
    color: #111827;
    font-size: 14px;
    line-height: 20px;
}
QLabel#ConfirmDialogFieldLabel {
    color: #374151;
    font-size: 13px;
}
QLabel#SettingsLabel {
    color: #374151;
    font-weight: 500;
}
QLabel#TimerLabel {
    color: #111827;
    font-size: 42px;
    font-weight: 700;
}
QCheckBox {
    color: #374151;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #b8c1d0;
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #2563eb;
}
QCheckBox::indicator:checked {
    background: #2563eb;
    border-color: #2563eb;
    image: url("__CHECK_MARK_PATH__");
}
QCheckBox::indicator:disabled {
    background: #f3f4f6;
    border-color: #d1d5db;
}
QTabWidget::pane {
    border: 1px solid #d1d5db;
    border-radius: 6px;
    top: -1px;
}
QTabBar::tab {
    background: #f3f4f6;
    border: 1px solid #d1d5db;
    border-bottom-color: #d1d5db;
    padding: 7px 18px;
    min-width: 64px;
}
QTabBar::tab:selected {
    background: #ffffff;
    border-bottom-color: #ffffff;
    color: #111827;
}
QTabBar::tab:hover {
    background: #e5e7eb;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 8px 14px;
    outline: none;
}
QPushButton:hover {
    background: #f3f4f6;
}
QPushButton:disabled {
    color: #9ca3af;
    background: #f3f4f6;
}
QPushButton#ConfirmDialogPrimaryButton {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    color: #111827;
    padding: 0;
    outline: none;
}
QPushButton#ConfirmDialogPrimaryButton:hover {
    background: #eff6ff;
}
QPushButton#ConfirmDialogPrimaryButton:focus,
QPushButton#ConfirmDialogPrimaryButton[active="true"] {
    border: 2px solid #2563eb;
}
QPushButton#ConfirmDialogCancelButton {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    color: #111827;
    padding: 0;
    outline: none;
}
QPushButton#ConfirmDialogCancelButton:hover {
    background: #f3f4f6;
}
QPushButton#ConfirmDialogCancelButton:focus,
QPushButton#ConfirmDialogCancelButton[active="true"] {
    border: 2px solid #2563eb;
}
QLineEdit#ConfirmDialogInput,
QComboBox#ConfirmDialogCombo {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px 8px;
    min-height: 26px;
}
QPushButton#SidebarPrimaryButton {
    background: #2563eb;
    border-color: #2563eb;
    color: #ffffff;
    font-weight: 400;
    text-align: center;
    padding: 10px 12px;
    min-height: 30px;
}
QPushButton#SidebarPrimaryButton:hover {
    background: #1d4ed8;
}
QPushButton#SidebarPrimaryButton:disabled {
    background: #d1d5db;
    border-color: #d1d5db;
    color: #6b7280;
}
QPushButton#SidebarSecondaryButton {
    background: #ffffff;
    border-color: #e5e7eb;
    color: #111827;
    font-weight: 400;
    text-align: center;
    padding: 10px 12px;
    min-height: 30px;
}
QPushButton#SidebarSecondaryButton:hover {
    background: #f8fafc;
}
QPushButton#SidebarSecondaryButton:disabled {
    color: #9ca3af;
    background: #f3f4f6;
}
QPushButton#SidebarRecordingTaskButton {
    background: #fff7ed;
    border-color: #fb923c;
    color: #9a3412;
    font-weight: 400;
    text-align: center;
    padding: 10px 12px;
    min-height: 30px;
}
QPushButton#SidebarRecordingTaskButton:hover {
    background: #ffedd5;
    border-color: #f97316;
}
QPushButton#SidebarRecordingButton {
    background: #fff7ed;
    border-color: #fed7aa;
    color: #9a3412;
    font-weight: 600;
    text-align: left;
    padding: 9px 12px;
}
QPushButton#SidebarRecordingButton:hover {
    background: #ffedd5;
}
QPushButton#SidebarSettingsButton {
    background: transparent;
    border: none;
    text-align: left;
    padding: 9px 10px;
}
QPushButton#SidebarSettingsButton:hover {
    background: #ecece6;
}
QPushButton#SidebarNavButton {
    background: transparent;
    border: none;
    color: #374151;
    text-align: left;
    padding: 10px 12px;
    border-radius: 8px;
}
QPushButton#SidebarNavButton:hover {
    background: #ecece6;
}
QPushButton#SidebarNavButton:checked {
    background: #e8e5ec;
    color: #111827;
    font-weight: 600;
}
QPushButton#RecordButton {
    background: #111827;
    border-color: #111827;
    color: #ffffff;
    font-weight: 600;
    padding: 10px 18px;
}
QPushButton#RecordButton:hover {
    background: #1f2937;
}
QPushButton#PrimaryButton {
    background: #2563eb;
    border-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover {
    background: #1d4ed8;
}
QPushButton#DangerButton {
    background: #dc2626;
    border-color: #dc2626;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#DangerButton:hover {
    background: #b91c1c;
}
QPushButton#DangerSmallButton {
    background: #ffffff;
    border-color: #fecaca;
    color: #b91c1c;
    font-weight: 600;
    padding: 5px 10px;
    min-width: 52px;
}
QPushButton#DangerSmallButton:hover {
    background: #fef2f2;
}
QPushButton#SuccessButton {
    background: #e8f5ee;
    border-color: #b7e2ca;
    color: #166534;
    font-weight: 600;
}
QPushButton#SmallButton {
    padding: 5px 10px;
    min-width: 52px;
}
QToolButton#DetailMetadataToggle {
    background: transparent;
    border: none;
    border-radius: 4px;
    color: #6b7280;
    padding: 3px 6px;
    font-size: 13px;
}
QToolButton#DetailMetadataToggle:hover {
    background: #f3f4f6;
    color: #111827;
}
QToolButton#DetailMetadataToggle:checked {
    color: #111827;
}
QToolButton#DetailMoreButton {
    background: #ffffff;
    border: 1px solid #d8dee8;
    border-radius: 6px;
    padding: 0;
}
QToolButton#DetailMoreButton:hover {
    background: #f3f4f6;
}
QToolButton#DetailTabToolButton,
QToolButton#DetailSearchPrevButton,
QToolButton#DetailSearchNextButton,
QToolButton#DetailSearchClearButton {
    background: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 0;
}
QToolButton#DetailTabToolButton:hover,
QToolButton#DetailSearchPrevButton:hover,
QToolButton#DetailSearchNextButton:hover,
QToolButton#DetailSearchClearButton:hover {
    background: #f3f4f6;
}
QFrame#DetailSearchBar {
    background: #ffffff;
    border: 1px solid #d8dee8;
    border-radius: 9px;
    margin-top: 12px;
    margin-bottom: 10px;
}
QLineEdit#DetailSearchInput {
    background: transparent;
    border: none;
    padding: 0;
    font-size: 14px;
}
QLabel#DetailSearchCount {
    color: #6b7280;
    font-size: 13px;
    min-width: 42px;
}
QPushButton#PlayerIconButton,
QPushButton#PlayerPlayButton {
    background: #ffffff;
    border: none;
    border-radius: 6px;
    color: #111827;
    padding: 0;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
}
QPushButton#PlayerIconButton:hover,
QPushButton#PlayerPlayButton:hover {
    background: #f3f4f6;
}
QPushButton#HotwordIconButton {
    padding: 4px 8px;
    min-width: 34px;
}
QPushButton#ResultTabButton {
    background: transparent;
    border: none;
    border-bottom: 3px solid transparent;
    border-radius: 0;
    color: #6b7280;
    font-size: 15px;
    font-weight: 500;
    padding: 4px 0 9px 0;
    min-width: 72px;
}
QPushButton#ResultTabButton:hover {
    background: transparent;
    color: #374151;
}
QPushButton#ResultTabButton:checked {
    color: #111827;
    font-weight: 700;
    border-bottom-color: #2563eb;
}
QFrame#ResultTabDivider {
    background: #e5e7eb;
    border: none;
}
QToolButton#HistoryMoreButton {
    background: #e5e7eb;
    border: none;
    border-radius: 7px;
    color: #374151;
    padding: 0;
    qproperty-toolButtonStyle: ToolButtonIconOnly;
}
QToolButton#HistoryMoreButton:hover {
    background: #d1d5db;
}
QMenu {
    background: #ffffff;
    color: #111827;
    border: 1px solid #d9d9d9;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    padding: 8px 28px 8px 12px;
    border-radius: 5px;
}
QMenu::item:selected {
    background: #eef2ff;
}
QMenu::separator {
    height: 1px;
    background: #e5e7eb;
    margin: 5px 8px;
}
QMenuBar#WorkbenchMenuBar {
    background: #ffffff;
    border: none;
    border-bottom: 1px solid #eef2f7;
    padding: 2px 12px 0 0;
    spacing: 8px;
}
QMenuBar#WorkbenchMenuBar::item {
    background: transparent;
    border: none;
    border-radius: 4px;
    color: #111827;
    margin: 0;
    padding: 5px 12px 6px 12px;
}
QMenuBar#WorkbenchMenuBar::item:selected,
QMenuBar#WorkbenchMenuBar::item:pressed {
    background: #f3f4f6;
    border: none;
    color: #111827;
}
QPlainTextEdit,
QTextBrowser,
QLineEdit {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px;
    color: #111827;
    selection-background-color: #bfdbfe;
}
QComboBox {
    background: #f7f7f7;
    border: 1px solid #a9a9a9;
    border-radius: 2px;
    padding: 2px 28px 2px 6px;
    min-height: 24px;
    color: #111827;
    selection-background-color: #dbeafe;
}
QComboBox:hover {
    background: #ffffff;
    border-color: #8f8f8f;
}
QComboBox:focus {
    border: 1px solid #8f8f8f;
}
QComboBox:disabled {
    background: #eeeeee;
    color: #9ca3af;
    border-color: #c7c7c7;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: none;
}
QComboBox::down-arrow {
    image: url("__COMBO_ARROW_PATH__");
    width: 10px;
    height: 10px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #a9a9a9;
    selection-background-color: #dbeafe;
    selection-color: #111827;
    outline: none;
}
QPlainTextEdit {
    line-height: 1.4;
}
QPlainTextEdit#HotwordWordsEditor {
    background: #ffffff;
    border-color: #d8dee8;
    border-radius: 7px;
    padding: 10px;
}
QTextBrowser#MarkdownView {
    line-height: 1.45;
}
QTextBrowser#TimelineView {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px;
    font-size: 12px;
}
QLineEdit#HotwordSearchBox {
    background: #ffffff;
    border: 1px solid #d8dee8;
    border-radius: 7px;
    min-height: 28px;
    padding: 7px 10px;
}
QComboBox#NotebookSelector {
    background: #ffffff;
    border: 1px solid #d8dee8;
    border-radius: 4px;
    min-height: 24px;
    padding: 5px 28px 5px 8px;
}
QComboBox#NotebookSelector:hover,
QComboBox#NotebookSelector:focus,
QComboBox#NotebookSelector:on {
    border: 2px solid #2563eb;
}
QLabel#NotebookDialogTitle {
    color: #111827;
    font-size: 18px;
    font-weight: 700;
}
QLabel#NotebookDialogCount {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 4px;
    color: #1d4ed8;
    font-size: 12px;
    padding: 2px 7px;
}
QScrollArea#NotebookManageScroll {
    background: transparent;
    border: none;
}
QScrollArea#NotebookManageScroll QWidget {
    background: transparent;
}
QFrame#NotebookManageRow {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
}
QFrame#NotebookManageRow:hover {
    border-color: #bfdbfe;
    background: #f8fbff;
}
QLabel#NotebookManageName {
    color: #111827;
    font-size: 14px;
    font-weight: 600;
}
QLabel#NotebookManagePath {
    color: #6b7280;
    font-size: 12px;
}
QLabel#NotebookDefaultBadge {
    background: #ecfdf5;
    border: 1px solid #bbf7d0;
    border-radius: 4px;
    color: #166534;
    font-size: 11px;
    padding: 1px 6px;
}
QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget#ModelList {
    background: #ffffff;
    border: none;
}
QListWidget#HotwordSetList {
    background: #f8fafc;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 8px;
}
QListWidget::item {
    padding: 2px;
    border-radius: 6px;
}
QListWidget::item:hover {
    background: transparent;
}
QListWidget::item:selected {
    background: transparent;
}
QListWidget#ModelList::item {
    padding: 6px;
    border-radius: 6px;
}
QListWidget#ModelList::item:hover {
    background: #f3f4f6;
}
QListWidget#ModelList::item:selected {
    background: #e8eefc;
    color: #111827;
}
QListWidget#HotwordSetList::item {
    background: #ffffff;
    border: 1px solid #e6ebf2;
    border-radius: 7px;
    color: #111827;
    padding: 0;
}
QListWidget#HotwordSetList::item:hover {
    background: #f9fbff;
    border-color: #cddaf0;
}
QListWidget#HotwordSetList::item:selected {
    background: #edf4ff;
    border-color: #76a9ff;
    color: #111827;
}
QWidget#HotwordSetItemContent {
    background: transparent;
}
QLabel#HotwordSetItemTitle {
    color: #111827;
    font-size: 13px;
    font-weight: 700;
}
QLabel#HotwordSetItemCount {
    color: #6b7280;
    font-size: 12px;
    font-weight: 400;
}
QTreeWidget#ModelTree {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    outline: none;
    color: #111827;
    alternate-background-color: #f3f4f6;
}
QTreeWidget#ModelTree::item {
    min-height: 24px;
    padding: 2px 4px;
}
QTreeWidget#ModelTree::item:hover {
    background: transparent;
    border: none;
}
QTreeWidget#ModelTree::item:selected {
    background: #dbeafe;
    color: #111827;
}
QFrame#ModelListItem {
    background: #ffffff;
}
QFrame#ModelListItem[alternate="true"] {
    background: #f6f7f8;
}
QFrame#ModelListItem[selected="true"] {
    background: #dbeafe;
}
QLabel#ModelItemTitle[selected="true"] {
    color: #111827;
}
QLabel#ModelItemSubtitle[selected="true"] {
    color: #4b5563;
}
QProgressBar {
    background: #f3f4f6;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background: #22c55e;
    border-radius: 4px;
}
QToolBar#QuickToolbar {
    spacing: 6px;
    padding: 6px 10px;
    border: 0;
    border-bottom: 1px solid #e5e7eb;
    background: #f8fafc;
}
QToolBar#QuickToolbar::separator {
    width: 0;
    background: transparent;
}
QToolButton#ToolbarIconButton, QToolButton#ToolbarRecordingButton {
    min-width: 34px;
    min-height: 34px;
    max-width: 34px;
    max-height: 34px;
    border-radius: 6px;
    border: 1px solid transparent;
    background: transparent;
}
QToolButton#ToolbarIconButton::menu-indicator,
QToolButton#ToolbarRecordingButton::menu-indicator {
    image: none;
    width: 0;
}
QToolButton#ToolbarIconButton:hover {
    background: #eef2f7;
    border-color: #d6dde8;
}
QToolButton#ToolbarRecordingButton {
    background: #fee2e2;
    border-color: #fecaca;
}
QSplitter#WorkbenchSplitter::handle {
    background: #e5e7eb;
    width: 2px;
}
QFrame#TaskPanel {
    background: #f8fafc;
    border-left: 1px solid #e5e7eb;
}
QTreeWidget#HistoryTree {
    border: 0;
    background: transparent;
    outline: 0;
}
QTreeWidget#HistoryTree::item {
    min-height: 28px;
    padding: 0;
}
QTreeWidget#HistoryTree::item:hover {
    background: #ececec;
}
QTreeWidget#HistoryTree::item:selected {
    background: #dbeafe;
    color: #111827;
}
QLabel#RecordingWave {
    color: #2563eb;
    font-size: 24px;
}
QSlider#PlayerSlider::groove:horizontal {
    height: 5px;
    background: #e5e7eb;
    border-radius: 2px;
}
QSlider#PlayerSlider::sub-page:horizontal {
    background: #2563eb;
    border-radius: 2px;
}
QSlider#PlayerSlider::handle:horizontal {
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
    background: #2563eb;
}
QComboBox#PlayerRateCombo {
    background: #ffffff;
    border: none;
    padding: 2px 0;
    min-height: 24px;
    min-width: 38px;
    max-width: 38px;
    font-weight: 700;
    text-align: center;
}
QComboBox#PlayerRateCombo::drop-down {
    width: 0;
    border: none;
}
QComboBox#PlayerRateCombo::down-arrow {
    image: none;
    width: 0;
    height: 0;
}
""".replace("__COMBO_ARROW_PATH__", _COMBO_ARROW_PATH).replace("__CHECK_MARK_PATH__", _CHECK_MARK_PATH)
