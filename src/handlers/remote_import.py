"""主窗口远程链接导入处理逻辑。"""
from __future__ import annotations

from urllib.parse import urlparse

from ..remote_import import RemoteImportError, RemoteImportOptions, RemoteImportService
from ..remote_import.errors import RemoteImportErrorKind, message_for_kind
from ..ui.widgets.dialogs import confirm_without_icon, prompt_text_without_icon
from ..utils.logging import log_event, record_context
from ..workers.remote_import import RemoteImportWorker, RemoteProbeWorker


class RemoteImportHandlers:
    """远程公开视频链接导入。"""

    def import_remote_url(self) -> None:
        """弹出链接输入框并启动远程导入。"""
        url, accepted = prompt_text_without_icon(self, "从链接导入", "视频链接", confirm_text="导入")
        if not accepted:
            return
        url = url.strip()
        if not _is_http_url(url):
            self._show_error("请输入有效的视频链接")
            return
        self._start_remote_import(url)

    def _start_remote_import(self, url: str) -> None:
        active_remote_imports = self._active_remote_imports()
        if len(active_remote_imports) >= self._max_remote_imports():
            self._show_error("远程导入任务已达上限，请等待当前任务完成后再试")
            return

        task_id = self._new_task_id("remote")
        active_remote_imports[task_id] = {"url": url, "record": None, "phase": "probe"}
        options = RemoteImportOptions(url=url)
        service = RemoteImportService(self.history_service, config=self.config)
        self.recording_hint_label.setText("正在解析链接")
        self._set_status("正在解析链接")
        log_event(
            "remote.probe.started",
            module="remote_import",
            message="开始解析远程链接",
            task_id=task_id,
            context={"url": url},
        )
        worker = RemoteProbeWorker(self.history_service, url, self, service=service, config=self.config)
        active_remote_imports[task_id]["worker"] = worker
        worker.progress.connect(lambda text, percent=None, task=task_id: self._on_remote_import_progress(text, percent, task))
        worker.completed.connect(lambda info, opts=options, task=task_id: self._on_remote_probe_completed(info, opts, task))
        worker.failed.connect(lambda error, task=task_id: self._on_remote_probe_failed(error, task))
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self.active_workers.append(worker)
        worker.start()

    def _on_remote_probe_completed(self, info: object, options: RemoteImportOptions, task_id: str = "") -> None:
        remote_task = self._remote_task(task_id)
        if not hasattr(info, "duration_seconds"):
            self._on_remote_probe_failed(
                RemoteImportError(RemoteImportErrorKind.UNKNOWN, message_for_kind(RemoteImportErrorKind.UNKNOWN), "invalid probe result"),
                task_id,
            )
            return
        log_event(
            "remote.probe.completed",
            module="remote_import",
            message="远程链接解析完成",
            task_id=task_id,
            context={
                "url": options.url,
                "extractor": getattr(info, "extractor", ""),
                "duration_seconds": getattr(info, "duration_seconds", None),
            },
        )

        if info.duration_seconds is None:
            if not confirm_without_icon(self, "确认处理", "无法确认视频时长，是否继续处理?"):
                self._cancel_remote_import("已取消链接导入", task_id)
                return
        elif info.duration_seconds > options.max_duration_seconds:
            if not confirm_without_icon(self, "确认处理", "视频超过2h，是否确认处理?"):
                self._cancel_remote_import("已取消链接导入", task_id)
                return

        try:
            service = RemoteImportService(self.history_service, config=self.config)
            record = self.history_service.create_remote_record(info)
            if remote_task is not None:
                remote_task["record"] = record
                remote_task["phase"] = "import"
            self.current_record = record
            self.recording_hint_label.setText("正在导入链接")
            self.load_recordings()
            self._select_record_by_key(record.record_key)
            log_event(
                "remote.import.started",
                module="remote_import",
                message="开始从链接导入",
                task_id=task_id,
                record_id=record.record_id,
                context={"record": record_context(record), "url": options.url, "extractor": info.extractor},
            )
            worker = RemoteImportWorker(self.history_service, record, info, options, self, service=service, config=self.config)
            if remote_task is not None:
                remote_task["worker"] = worker
            worker.progress.connect(lambda text, percent=None, task=task_id: self._on_remote_import_progress(text, percent, task))
            worker.completed.connect(lambda result, task=task_id: self._on_remote_import_completed(result, task))
            worker.failed.connect(lambda error, task=task_id: self._on_remote_import_failed(error, task))
            worker.finished.connect(lambda: self._cleanup_worker(worker))
            self.active_workers.append(worker)
            worker.start()
        except Exception as exc:
            self._active_remote_imports().pop(task_id, None)
            error = RemoteImportError(RemoteImportErrorKind.UNKNOWN, message_for_kind(RemoteImportErrorKind.UNKNOWN), str(exc))
            log_event(
                "remote.import.start_failed",
                level="ERROR",
                module="remote_import",
                message="链接导入启动失败",
                task_id=task_id,
                context={"url": options.url, "extractor": getattr(info, "extractor", ""), "error": error.to_metadata()},
                error_code="REM-002",
                error_type=error.kind.value,
            )
            self._show_error(_remote_error_text(error))
            self._set_status(error.message)

    def _on_remote_probe_failed(self, error: object, task_id: str = "") -> None:
        self._active_remote_imports().pop(task_id, None)
        if not isinstance(error, RemoteImportError):
            error = RemoteImportError(RemoteImportErrorKind.UNKNOWN, message_for_kind(RemoteImportErrorKind.UNKNOWN), str(error))
        log_event(
            "remote.probe.failed",
            level="ERROR",
            module="remote_import",
            message="远程链接解析失败",
            task_id=task_id,
            context={"error": error.to_metadata()},
            error_code="REM-000",
            error_type=error.kind.value,
        )
        self.recording_hint_label.setText("链接解析失败")
        self._show_error(_remote_error_text(error))
        self._set_status(error.message)

    def _cancel_remote_import(self, status: str, task_id: str = "") -> None:
        self._active_remote_imports().pop(task_id, None)
        self.recording_hint_label.setText("准备捕获系统声音")
        self._set_status(status)

    def _on_remote_import_progress(self, text: str, percent: int | None = None, task_id: str = "") -> None:
        if task_id and task_id not in self._active_remote_imports():
            return
        self._set_status(text or "正在导入链接")
        self._refresh_history_status_indicators()

    def _on_remote_import_completed(self, result: object, task_id: str = "") -> None:
        remote_task = self._active_remote_imports().pop(task_id, None)
        record = getattr(result, "record", None) or (remote_task or {}).get("record")
        mode = getattr(result, "mode", "")
        log_event(
            "remote.import.completed",
            module="remote_import",
            message="链接导入完成",
            task_id=task_id,
            record_id=(record.record_id if record else None),
            context={"record": record_context(record), "mode": mode},
        )
        self.recording_hint_label.setText("链接导入完成")
        self.load_recordings()
        if record:
            self._select_record_by_key(record.record_key)
        if mode == "audio" and record:
            self._handle_audio_record_ready(record, "已导入链接音频", source="remote_import")
            return
        if record and self.config["audio"].get("auto_summarize", True) and getattr(result, "transcript_text", "").strip():
            self.start_summarization(getattr(result, "transcript_text"), record)
            return
        self._set_status("已导入链接字幕" if mode == "subtitle" else "链接导入完成")

    def _on_remote_import_failed(self, error: object, task_id: str = "") -> None:
        remote_task = self._active_remote_imports().pop(task_id, None)
        if not isinstance(error, RemoteImportError):
            error = RemoteImportError(RemoteImportErrorKind.UNKNOWN, message_for_kind(RemoteImportErrorKind.UNKNOWN), str(error))
        record = (remote_task or {}).get("record")
        log_event(
            "remote.import.failed",
            level="ERROR",
            module="remote_import",
            message="链接导入失败",
            task_id=task_id,
            record_id=(record.record_id if record else None),
            context={"record": record_context(record), "error": error.to_metadata()},
            error_code="REM-001",
            error_type=error.kind.value,
        )
        self.recording_hint_label.setText("链接导入失败")
        if record:
            record = self.history_service.mark_input_error(record, error)
            self._add_history_notice_if_unselected(record, "出现异常，点击查看详情")
            self.load_recordings()
            if self.current_record and self.current_record.record_key == record.record_key:
                self._select_record_by_key(record.record_key)
        self._show_error(_remote_error_text(error))
        self._set_status(error.message)

    def _active_remote_imports(self) -> dict[str, dict[str, object]]:
        if not hasattr(self, "active_remote_imports"):
            self.active_remote_imports = {}
        return self.active_remote_imports

    def _remote_task(self, task_id: str) -> dict[str, object] | None:
        if not task_id:
            return None
        return self._active_remote_imports().get(task_id)

    def _max_remote_imports(self) -> int:
        tasks_config = self.config.get("tasks", {})
        try:
            return max(1, int(tasks_config.get("max_remote_imports") or 2))
        except (TypeError, ValueError):
            return 2


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _remote_error_text(error: RemoteImportError) -> str:
    detail = (error.detail or "").strip()
    if detail and detail != error.message:
        return f"{error.message}\n\n{detail}"
    return error.message
