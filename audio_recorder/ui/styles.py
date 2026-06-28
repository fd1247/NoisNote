"""Qt 样式定义。"""

from pathlib import Path


_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
_COMBO_ARROW_PATH = (_ASSET_DIR / "svg" / "下拉.svg").as_posix()


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
QFrame#MainArea {
    background: #ffffff;
}
QStackedWidget {
    background: #ffffff;
    border: none;
}
QFrame#Panel {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
}
QFrame#ModelListPanel {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
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
    color: #6b7280;
    border: 1px solid #d1d5db;
    border-radius: 11px;
    background: #ffffff;
}
QLabel#HistoryTitle {
    color: #111827;
    font-size: 13px;
    font-weight: 600;
}
QLabel#HistorySubtitle {
    color: #6b7280;
    font-size: 11px;
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
    font-weight: 600;
}
QLabel#Muted {
    color: #6b7280;
}
QLabel#ConfirmDialogMessage {
    color: #111827;
    font-size: 14px;
    line-height: 20px;
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
}
QPushButton#ConfirmDialogPrimaryButton:hover {
    background: #eff6ff;
}
QPushButton#ConfirmDialogPrimaryButton:focus {
    border: 2px solid #2563eb;
}
QPushButton#ConfirmDialogCancelButton {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    color: #111827;
    padding: 0;
}
QPushButton#ConfirmDialogCancelButton:hover {
    background: #f3f4f6;
}
QPushButton#ConfirmDialogCancelButton:focus {
    border: 2px solid #2563eb;
}
QPushButton#SidebarPrimaryButton {
    background: #111827;
    border-color: #111827;
    color: #ffffff;
    font-weight: 600;
    text-align: left;
    padding: 10px 12px;
}
QPushButton#SidebarPrimaryButton:hover {
    background: #1f2937;
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
    font-weight: 600;
    text-align: left;
    padding: 10px 12px;
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
    font-weight: 700;
    text-align: left;
    padding: 10px 12px;
}
QPushButton#SidebarRecordingTaskButton:hover {
    background: #ffedd5;
    border-color: #f97316;
}
QPushButton#SidebarProcessingTaskButton {
    background: #ecfdf3;
    border-color: #86efac;
    color: #166534;
    font-weight: 700;
    text-align: left;
    padding: 10px 12px;
}
QPushButton#SidebarProcessingTaskButton:hover {
    background: #dcfce7;
    border-color: #4ade80;
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
QPushButton#HistoryMoreButton {
    background: #e5e7eb;
    border: none;
    border-radius: 7px;
    color: #374151;
    font-weight: 700;
    padding: 0;
}
QPushButton#HistoryMoreButton:hover {
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
QTextBrowser#MarkdownView {
    line-height: 1.45;
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
""".replace("__COMBO_ARROW_PATH__", _COMBO_ARROW_PATH)
