"""
更新提示对话框

显示版本更新信息，提供下载链接。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ...app.update import UpdateInfo


class UpdateDialog(QDialog):
    """更新提示对话框"""

    def __init__(self, update_info: UpdateInfo, parent: QWidget | None = None):
        super().__init__(parent)
        self._update_info = update_info
        self._setup_ui()

    def _setup_ui(self):
        """设置对话框布局"""
        self.setWindowTitle("发现新版本")
        self.setMinimumWidth(400)
        self.setModal(False)

        # 如果有父窗口，使用其图标
        if self.parent() is not None:
            self.setWindowIcon(self.parent().windowIcon())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 24, 34, 20)
        layout.setSpacing(16)

        # 标题
        title_label = QLabel("发现新版本")
        title_label.setObjectName("UpdateDialogTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = title_label.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # 版本信息
        version_layout = QHBoxLayout()
        version_layout.setSpacing(8)

        current_label = QLabel(f"当前版本：{self._update_info.current_version}")
        current_label.setObjectName("UpdateDialogCurrentVersion")
        version_layout.addWidget(current_label)

        arrow_label = QLabel("→")
        arrow_label.setObjectName("UpdateDialogArrow")
        version_layout.addWidget(arrow_label)

        latest_label = QLabel(f"最新版本：{self._update_info.latest_version}")
        latest_label.setObjectName("UpdateDialogLatestVersion")
        latest_font = latest_label.font()
        latest_font.setBold(True)
        latest_label.setFont(latest_font)
        version_layout.addWidget(latest_label)

        version_layout.addStretch(1)
        layout.addLayout(version_layout)

        # 更新说明
        notes_label = QLabel("更新说明：")
        notes_label.setObjectName("UpdateDialogNotesLabel")
        layout.addWidget(notes_label)

        notes_browser = QTextBrowser()
        notes_browser.setObjectName("UpdateDialogNotes")
        notes_browser.setOpenExternalLinks(True)
        notes_browser.setPlainText(self._update_info.release_notes)
        notes_browser.setMinimumHeight(120)
        notes_browser.setMaximumHeight(200)
        layout.addWidget(notes_browser)

        # 按钮
        buttons_layout = QHBoxLayout()
        buttons_layout.setContentsMargins(0, 8, 0, 0)
        buttons_layout.setSpacing(10)
        buttons_layout.addStretch(1)

        download_button = QPushButton("下载更新")
        download_button.setObjectName("UpdateDialogDownloadButton")
        download_button.setFixedSize(100, 38)
        download_button.setDefault(True)
        download_button.clicked.connect(self._on_download_clicked)
        buttons_layout.addWidget(download_button)

        later_button = QPushButton("稍后提醒")
        later_button.setObjectName("UpdateDialogLaterButton")
        later_button.setFixedSize(100, 38)
        later_button.clicked.connect(self.close)
        buttons_layout.addWidget(later_button)

        buttons_layout.addStretch(1)
        layout.addLayout(buttons_layout)

    def _on_download_clicked(self):
        """点击下载按钮，跳转浏览器"""
        url = self._update_info.download_url
        if url:
            QDesktopServices.openUrl(QUrl(url))
        self.close()

    @staticmethod
    def show_update_dialog(
        parent: QWidget | None,
        update_info: UpdateInfo,
    ) -> UpdateDialog:
        """显示更新提示对话框

        Args:
            parent: 父窗口
            update_info: 更新信息

        Returns:
            UpdateDialog 对象
        """
        dialog = UpdateDialog(update_info, parent)
        dialog.show()
        return dialog
