"""
更新提示对话框

显示版本更新信息，提供下载链接。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from ...app.update import GITHUB_REPO, GITHUB_OWNER, UpdateInfo
from .dialogs import _ConfirmDialog, add_dialog_buttons, primary_button_spec, secondary_button_spec


_RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"


class UpdateDialog(_ConfirmDialog):
    """更新提示对话框"""

    def __init__(self, update_info: UpdateInfo, parent: QWidget | None = None):
        super().__init__(parent)
        self._update_info = update_info
        self._current_version = update_info.current_version
        self._release_url = update_info.download_url or _RELEASES_URL
        self._setup_ui()
        self.set_update_info(update_info)

    def _setup_ui(self):
        """设置对话框布局"""
        self.setObjectName("ConfirmDialog")
        self.setWindowTitle("检查更新")
        self.setMinimumWidth(340)
        self.setModal(True)

        # 如果有父窗口，使用其图标
        if self.parent() is not None:
            self.setWindowIcon(self.parent().windowIcon())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(42, 28, 42, 22)
        layout.setSpacing(28)

        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(18)
        info_grid.setVerticalSpacing(10)

        self.current_title = QLabel("当前版本：")
        self.current_title.setObjectName("UpdateDialogInfoLabel")
        self.current_value = QLabel(self._current_version)
        self.current_value.setObjectName("UpdateDialogInfoValue")
        latest_title = QLabel("最新版本：")
        latest_title.setObjectName("UpdateDialogInfoLabel")
        self.latest_value = QLabel("正在获取信息...")
        self.latest_value.setObjectName("UpdateDialogInfoValue")

        info_grid.addWidget(self.current_title, 0, 0, alignment=Qt.AlignmentFlag.AlignRight)
        info_grid.addWidget(self.current_value, 0, 1)
        info_grid.addWidget(latest_title, 1, 0, alignment=Qt.AlignmentFlag.AlignRight)
        info_grid.addWidget(self.latest_value, 1, 1)
        layout.addLayout(info_grid)

        self.confirm_button, self.release_button = add_dialog_buttons(
            self,
            layout,
            [
                primary_button_spec("确认", self.close, active=True),
                secondary_button_spec("查看发布", self._on_release_clicked),
            ],
        )

    def set_update_info(self, update_info: UpdateInfo) -> None:
        """刷新检查结果。"""
        self._update_info = update_info
        self._current_version = update_info.current_version
        self.current_value.setText(update_info.current_version)
        if update_info.download_url or update_info.release_notes:
            self.latest_value.setText(update_info.latest_version)
            self._release_url = update_info.download_url or _RELEASES_URL
        else:
            self.latest_value.setText("获取最新版本信息失败")
            self._release_url = _RELEASES_URL

    def _on_release_clicked(self):
        """点击查看发布按钮，跳转浏览器。"""
        QDesktopServices.openUrl(QUrl(self._release_url))
        self.close()

    @classmethod
    def pending(cls, parent: QWidget | None, current_version: str) -> "UpdateDialog":
        """创建正在获取版本信息的对话框。"""
        from datetime import datetime, timezone

        return cls(
            UpdateInfo(
                has_update=False,
                latest_version="正在获取信息...",
                current_version=current_version,
                download_url="",
                release_notes="pending",
                check_time=datetime.now(timezone.utc),
            ),
            parent,
        )

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

    @staticmethod
    def show_pending_dialog(parent: QWidget | None, current_version: str) -> UpdateDialog:
        """显示检查中状态对话框。"""
        dialog = UpdateDialog.pending(parent, current_version)
        dialog.show()
        return dialog
