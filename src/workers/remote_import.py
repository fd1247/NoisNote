"""远程链接导入后台线程。"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..remote_import import RemoteImportError, RemoteImportOptions, RemoteImportService, RemoteMediaInfo
from ..remote_import.errors import remote_error_from_exception
from ..history.service import HistoryRecord, HistoryService


class RemoteProbeWorker(QThread):
    """在后台线程中解析远程链接元数据。"""

    progress = Signal(str, object)
    completed = Signal(object)
    failed = Signal(object)

    def __init__(
        self,
        history_service: HistoryService,
        url: str,
        parent=None,
        service: RemoteImportService | None = None,
        config: dict | None = None,
    ):
        super().__init__(parent)
        self.history_service = history_service
        self.url = url
        self.service = service
        self.config = config

    def run(self) -> None:
        try:
            self.progress.emit("正在解析链接", 0)
            service = self.service or RemoteImportService(self.history_service, config=self.config)
            self.completed.emit(service.probe(self.url))
        except RemoteImportError as exc:
            self.failed.emit(exc)
        except Exception as exc:
            self.failed.emit(remote_error_from_exception(exc))


class RemoteImportWorker(QThread):
    """在后台线程中执行远程字幕或音频导入。"""

    progress = Signal(str, object)
    completed = Signal(object)
    failed = Signal(object)

    def __init__(
        self,
        history_service: HistoryService,
        record: HistoryRecord,
        info: RemoteMediaInfo,
        options: RemoteImportOptions,
        parent=None,
        service: RemoteImportService | None = None,
        config: dict | None = None,
    ):
        super().__init__(parent)
        self.history_service = history_service
        self.record = record
        self.info = info
        self.options = options
        self.service = service
        self.config = config

    def run(self) -> None:
        try:
            service = self.service or RemoteImportService(self.history_service, config=self.config)
            result = service.import_url(self.record, self.info, self.options, progress_callback=self.progress.emit)
            self.completed.emit(result)
        except RemoteImportError as exc:
            self.failed.emit(exc)
        except Exception as exc:
            self.failed.emit(remote_error_from_exception(exc))
