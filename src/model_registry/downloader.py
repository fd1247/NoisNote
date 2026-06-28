"""模型下载任务管理器。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..app.config import save_config
from .worker import ModelDownloadWorker
from .types import DownloadTaskState
from .service import ModelService
from ..utils.logging import log_event


class ModelDownloadManager(QObject):
    """在设置页面之外管理模型下载任务生命周期。"""

    tasks_changed = Signal()
    models_changed = Signal()
    download_failed = Signal(str, str)
    download_completed = Signal(str)
    download_cancelled = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.service = ModelService(self.config)
        self.max_concurrent_downloads = 1
        self.download_workers: dict[str, ModelDownloadWorker] = {}
        self.download_tasks: dict[str, DownloadTaskState] = {}
        self.cancelled_downloads: set[str] = set()

    def has_active_downloads(self) -> bool:
        """是否仍有下载任务在运行。"""
        return bool(self.download_workers)

    def get_download_tasks(self) -> dict[str, DownloadTaskState]:
        """返回当前下载状态。"""
        return self.download_tasks

    def start_download(self, name: str) -> None:
        """启动模型下载。"""
        entry = self.service.get_entry(name)
        if not entry:
            log_event(
                "model.download.failed",
                level="ERROR",
                module="model",
                message="模型清单中找不到该模型",
                context={"model": name},
                error_code="MOD-001",
                error_type="missing_catalog_entry",
            )
            self.download_failed.emit(name, "模型清单中找不到该模型。")
            return
        if entry.name in self.download_workers:
            return
        if len(self.download_workers) >= self.max_concurrent_downloads:
            log_event(
                "model.download.failed",
                level="WARNING",
                module="model",
                message="已有模型正在下载",
                context=self._model_log_context(entry),
                error_type="concurrent_download_limited",
            )
            self.download_failed.emit(name, "已有模型正在下载，请等待当前下载完成后再试。")
            self.tasks_changed.emit()
            return
        disk_check = self.service.check_download_disk_space(entry)
        if not disk_check.ok:
            log_event(
                "model.download.failed",
                level="ERROR",
                module="model",
                message="模型下载磁盘空间不足",
                context={
                    **self._model_log_context(entry),
                    "required_bytes": getattr(disk_check, "required_bytes", 0),
                    "available_bytes": getattr(disk_check, "available_bytes", 0),
                },
                error_code="MOD-004",
                error_type="insufficient_disk_space",
            )
            self.download_failed.emit(name, disk_check.message)
            self.tasks_changed.emit()
            return
        try:
            download_dir = self.service.prepare_download_dir(entry)
        except Exception as exc:
            log_event(
                "model.download.failed",
                level="ERROR",
                module="model",
                message="模型下载目录准备失败",
                context={**self._model_log_context(entry), "error": str(exc)},
                error_code="MOD-002",
                error_type=type(exc).__name__,
            )
            self.download_failed.emit(name, str(exc))
            return

        state = DownloadTaskState(
            name=entry.name,
            source_url=entry.primary_download_url(),
            target_dir=download_dir,
            progress_percent=None,
            status_text="准备下载",
        )
        self.cancelled_downloads.discard(entry.name)
        self.download_tasks[entry.name] = state

        worker = ModelDownloadWorker(entry, download_dir, parent=self)
        worker.progress.connect(self._on_download_progress)
        worker.completed.connect(self._on_download_completed)
        worker.failed.connect(self._on_download_failed)
        worker.cancelled.connect(self._on_download_cancelled)
        worker.finished.connect(worker.deleteLater)
        self.download_workers[entry.name] = worker

        log_event(
            "model.download.started",
            module="model",
            message="开始下载模型",
            context={
                **self._model_log_context(entry),
                "required_bytes": disk_check.required_bytes,
                "available_bytes": disk_check.available_bytes,
            },
        )
        self.tasks_changed.emit()
        worker.start()

    def cancel_download(self, name: str) -> None:
        """取消模型下载并立即更新界面状态。"""
        worker = self.download_workers.get(name)
        if not worker:
            return

        self.cancelled_downloads.add(name)
        worker.request_cancel()
        self.download_workers.pop(name, None)
        self.download_tasks.pop(name, None)

        if worker.isRunning():
            worker.wait(1200)
            if worker.isRunning():
                worker.terminate()
                worker.wait(1500)
        self._cleanup_cancelled_download(name)
        self.tasks_changed.emit()
        log_event(
            "model.download.cancelled",
            module="model",
            message="模型下载已取消",
            context={"model": name},
        )
        self.download_cancelled.emit(name)

    def cancel_all_downloads(self) -> None:
        """取消全部下载任务。"""
        for name in list(self.download_workers):
            self.cancel_download(name)

    def _on_download_progress(self, name: str, percent: int, text: str) -> None:
        task = self.download_tasks.get(name)
        if not task:
            return
        active_file = self._extract_active_file_name(text)
        if active_file:
            task.active_file_name = active_file
        task.progress_percent = None if percent < 0 else percent
        task.status_text = text
        task.progress_source = "worker"
        task.status = "downloading" if percent < 100 else "validating"
        self.tasks_changed.emit()

    def _on_download_completed(self, name: str, source_dir: str) -> None:
        if name in self.cancelled_downloads:
            self._cleanup_cancelled_download(name)
            self.tasks_changed.emit()
            return

        entry = self.service.get_entry(name)
        self.download_workers.pop(name, None)
        self.download_tasks.pop(name, None)

        if not entry:
            self.download_failed.emit(name, "下载完成，但模型清单不存在。")
            self.tasks_changed.emit()
            return
        try:
            target_dir = self.service.finalize_download(entry, Path(source_dir))
            self.service.mark_downloaded(entry, target_dir)
            save_config(self.config)
            self.models_changed.emit()
            log_event(
                "model.download.completed",
                module="model",
                message="模型下载完成",
                context=self._model_log_context(entry),
            )
            self.download_completed.emit(name)
        except Exception as exc:
            self.service.cleanup_temp_dir(entry)
            log_event(
                "model.download.failed",
                level="ERROR",
                module="model",
                message="模型下载完成后校验或落盘失败",
                context={**self._model_log_context(entry), "error": str(exc)},
                error_code="MOD-003",
                error_type=type(exc).__name__,
            )
            self.download_failed.emit(name, str(exc))
        self.tasks_changed.emit()

    def _on_download_failed(self, name: str, error: str) -> None:
        if name in self.cancelled_downloads:
            self._cleanup_cancelled_download(name)
            self.tasks_changed.emit()
            return

        entry = self.service.get_entry(name)
        self.download_workers.pop(name, None)
        self.download_tasks.pop(name, None)
        if entry:
            self.service.cleanup_temp_dir(entry)
        log_event(
            "model.download.failed",
            level="ERROR",
            module="model",
            message="模型下载失败",
            context={
                **(self._model_log_context(entry) if entry else {"model": name}),
                "error": error,
            },
            error_code="MOD-002",
            error_type="download_failed",
        )
        self.download_failed.emit(name, error)
        self.tasks_changed.emit()

    def _on_download_cancelled(self, name: str) -> None:
        self.download_workers.pop(name, None)
        self.download_tasks.pop(name, None)
        self._cleanup_cancelled_download(name)
        self.tasks_changed.emit()
        log_event(
            "model.download.cancelled",
            module="model",
            message="模型下载已取消",
            context={"model": name},
        )
        self.download_cancelled.emit(name)

    def _cleanup_cancelled_download(self, name: str) -> None:
        entry = self.service.get_entry(name)
        if entry:
            try:
                self.service.cleanup_temp_dir(entry)
            except Exception as exc:
                log_event(
                    "model.download.cleanup_failed",
                    level="WARNING",
                    module="model",
                    message="取消下载后的临时目录清理失败",
                    context={"model": name, "error": str(exc)},
                )

    def _extract_active_file_name(self, text: str) -> str:
        if not text.startswith("正在下载 "):
            return ""
        value = text.removeprefix("正在下载 ").strip()
        if not value:
            return ""
        return value.split("|", 1)[0].strip()

    def _model_log_context(self, entry) -> dict:
        return {
            "model": entry.name,
            "display_name": entry.display_name,
            "estimated_size_bytes": entry.estimated_size_bytes,
            "source_url": entry.primary_download_url(),
            "download_source_count": len(entry.download_sources or []),
        }
