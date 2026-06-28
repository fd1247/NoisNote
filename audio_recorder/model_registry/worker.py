"""模型下载后台线程。"""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .types import ModelCatalogEntry
from .download import Downloader, default_gguf_downloader

class ModelDownloadWorker(QThread):
    """在后台线程中下载 GGUF 模型文件。"""

    progress = Signal(str, int, str)
    completed = Signal(str, str)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(
        self,
        entry: ModelCatalogEntry,
        download_dir: Path,
        downloader: Downloader | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.entry = entry
        self.download_dir = download_dir
        self.downloader = downloader or default_gguf_downloader
        self._cancel_requested = False

    def request_cancel(self) -> None:
        """请求在安全点取消下载。"""
        self._cancel_requested = True

    def run(self) -> None:
        """执行下载并发送状态信号。"""
        try:
            self._emit_progress(None, "准备下载")
            if self._cancel_requested:
                self._cleanup_download_dir()
                self.cancelled.emit(self.entry.name)
                return

            result_dir = self.downloader(
                self.entry,
                self.download_dir,
                self._emit_progress,
                lambda: self._cancel_requested,
            )

            if self._cancel_requested:
                self._cleanup_download_dir()
                self.cancelled.emit(self.entry.name)
                return

            self._emit_progress(100, "下载完成，正在校验")
            self.completed.emit(self.entry.name, str(result_dir))
        except Exception as exc:
            if self._cancel_requested:
                self._cleanup_download_dir()
                self.cancelled.emit(self.entry.name)
            else:
                self.failed.emit(self.entry.name, str(exc))

    def _emit_progress(self, percent: int | None, text: str) -> None:
        value = -1 if percent is None else max(0, min(100, percent))
        self.progress.emit(self.entry.name, value, text)

    def _cleanup_download_dir(self) -> None:
        if self.download_dir.exists() and self.download_dir.is_dir():
            shutil.rmtree(self.download_dir)


