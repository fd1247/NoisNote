"""主窗口远程链接导入处理逻辑。"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from ..remote_import import RemoteImportError, RemoteImportOptions, RemoteImportService
from ..remote_import.errors import RemoteImportErrorKind, message_for_kind
from ..remote_import.subtitles import select_preferred_subtitle
from ..tasks import AppTask, TaskStage
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
        if not self.has_processing_queue_capacity():
            self._show_error("队列已满，请先移除任务或等待任务完成")
            return

        probe_id = self._new_task_id("remote-probe")
        active_remote_imports = self._active_remote_imports()
        active_remote_imports[probe_id] = {"url": url, "record": None, "phase": "admission_probe"}
        options = RemoteImportOptions(url=url)
        service = RemoteImportService(self.history_service, config=self.config)
        self.recording_hint_label.setText("正在解析链接")
        self._set_status("正在解析链接")
        log_event(
            "remote.probe.started",
            module="remote_import",
            message="开始解析远程链接",
            task_id=probe_id,
            context={"url": url},
        )
        worker = RemoteProbeWorker(self.history_service, url, self, service=service, config=self.config)
        active_remote_imports[probe_id]["worker"] = worker
        worker.progress.connect(lambda text, percent=None, task=probe_id: self._on_remote_import_progress(text, percent, task))
        worker.completed.connect(lambda info, opts=options, task=probe_id: self._on_remote_admission_probe_completed(info, opts, task))
        worker.failed.connect(lambda error, task=probe_id: self._on_remote_admission_probe_failed(error, task))
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self.active_workers.append(worker)
        worker.start()

    def _execute_remote_import_task(self, task: AppTask) -> None:
        url = task.input_url.strip()
        if not _is_http_url(url):
            self.task_manager.fail_running(task.task_id, "请输入有效的视频链接")
            self._start_next_processing_task()
            return
        record = self.history_service.get_record_by_key(task.record_key)
        if record is None:
            self.task_manager.fail_running(task.task_id, "历史记录不存在")
            self._start_next_processing_task()
            return
        self.current_processing_task = task
        self.processing_record = record
        self.processing_source = "remote_import"
        self.is_processing = True
        task_id = task.task_id
        active_remote_imports = self._active_remote_imports()
        attempt_id = self._new_task_id("remote-run")
        active_remote_imports[task_id] = {"url": url, "record": record, "phase": "probe", "attempt_id": attempt_id}
        options = RemoteImportOptions(url=url)
        service = RemoteImportService(self.history_service, config=self.config)
        self.task_manager.mark_running(task_id, TaskStage.PARSING_LINK, "解析链接中")
        self.recording_hint_label.setText("解析链接中")
        self._set_status("解析链接中")
        log_event(
            "remote.probe.started",
            module="remote_import",
            message="开始解析远程链接",
            task_id=task_id,
            context={"url": url},
        )
        worker = RemoteProbeWorker(self.history_service, url, self, service=service, config=self.config)
        active_remote_imports[task_id]["worker"] = worker
        worker.progress.connect(lambda text, percent=None, task=task_id, attempt=attempt_id: self._on_remote_import_progress(text, percent, task, attempt))
        worker.completed.connect(lambda info, opts=options, task=task_id, attempt=attempt_id: self._on_remote_probe_completed(info, opts, task, attempt))
        worker.failed.connect(lambda error, task=task_id, attempt=attempt_id: self._on_remote_probe_failed(error, task, attempt))
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self.active_workers.append(worker)
        worker.start()

    def _on_remote_admission_probe_completed(self, info: object, options: RemoteImportOptions, probe_id: str = "") -> None:
        if not hasattr(info, "duration_seconds"):
            self._on_remote_admission_probe_failed(
                RemoteImportError(RemoteImportErrorKind.UNKNOWN, message_for_kind(RemoteImportErrorKind.UNKNOWN), "invalid probe result"),
                probe_id,
            )
            return
        log_event(
            "remote.probe.completed",
            module="remote_import",
            message="远程链接解析完成",
            task_id=probe_id,
            context={
                "url": options.url,
                "extractor": getattr(info, "extractor", ""),
                "duration_seconds": getattr(info, "duration_seconds", None),
            },
        )
        if info.duration_seconds is None:
            if not confirm_without_icon(self, "确认处理", "无法确认视频时长，是否继续处理?"):
                self._cancel_remote_admission("已取消链接导入", probe_id)
                return
        elif info.duration_seconds > options.max_duration_seconds:
            if not confirm_without_icon(self, "确认处理", "视频超过2h，是否确认处理?"):
                self._cancel_remote_admission("已取消链接导入", probe_id)
                return
        if not self.has_processing_queue_capacity():
            self._active_remote_imports().pop(probe_id, None)
            self._show_error("队列已满，请先移除任务或等待任务完成")
            return
        try:
            record = self.history_service.create_remote_record(info)
            self.current_record = record
            self.load_recordings()
            self._select_record_by_key(record.record_key)
            self._active_remote_imports().pop(probe_id, None)
            task = self.enqueue_record_processing(record, source="remote_import", input_url=options.url)
            if task is None:
                self.history_service.delete_record(record)
                self.load_recordings()
        except Exception as exc:
            self._active_remote_imports().pop(probe_id, None)
            error = RemoteImportError(RemoteImportErrorKind.UNKNOWN, message_for_kind(RemoteImportErrorKind.UNKNOWN), str(exc))
            log_event(
                "remote.import.start_failed",
                level="ERROR",
                module="remote_import",
                message="链接导入启动失败",
                task_id=probe_id,
                context={"url": options.url, "extractor": getattr(info, "extractor", ""), "error": error.to_metadata()},
                error_code="REM-002",
                error_type=error.kind.value,
            )
            self._show_error(_remote_error_text(error))
            self._set_status(error.message)

    def _on_remote_admission_probe_failed(self, error: object, probe_id: str = "") -> None:
        self._active_remote_imports().pop(probe_id, None)
        if not isinstance(error, RemoteImportError):
            error = RemoteImportError(RemoteImportErrorKind.UNKNOWN, message_for_kind(RemoteImportErrorKind.UNKNOWN), str(error))
        log_event(
            "remote.probe.failed",
            level="ERROR",
            module="remote_import",
            message="远程链接解析失败",
            task_id=probe_id,
            context={"error": error.to_metadata()},
            error_code="REM-000",
            error_type=error.kind.value,
        )
        self.recording_hint_label.setText("链接解析失败")
        self._show_error(_remote_error_text(error))
        self._set_status(error.message)

    def _cancel_remote_admission(self, status: str, probe_id: str) -> None:
        remote_task = self._active_remote_imports().pop(probe_id, None)
        self._stop_remote_import_worker((remote_task or {}).get("worker"))
        self.recording_hint_label.setText("准备捕获系统声音")
        self._set_status(status)

    def _on_remote_probe_completed(self, info: object, options: RemoteImportOptions, task_id: str = "", attempt_id: str = "") -> None:
        if not self._is_current_remote_attempt(task_id, attempt_id):
            return
        remote_task = self._remote_task(task_id)
        record = (remote_task or {}).get("record")
        if record is None:
            self._on_remote_probe_failed(
                RemoteImportError(RemoteImportErrorKind.UNKNOWN, message_for_kind(RemoteImportErrorKind.UNKNOWN), "missing remote record"),
                task_id,
            )
            return
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

        try:
            service = RemoteImportService(self.history_service, config=self.config)
            if remote_task is not None:
                remote_task["phase"] = "import"
            self.current_record = record
            if select_preferred_subtitle(info, options.preferred_languages) is None:
                self.task_manager.mark_running(task_id, TaskStage.DOWNLOADING_AUDIO, "下载音频中")
                self.recording_hint_label.setText("下载音频中")
            else:
                self.task_manager.mark_running(task_id, TaskStage.PARSING_LINK, "解析链接中")
                self.recording_hint_label.setText("解析链接中")
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
            worker.progress.connect(lambda text, percent=None, task=task_id, attempt=attempt_id: self._on_remote_import_progress(text, percent, task, attempt))
            worker.completed.connect(lambda result, task=task_id, attempt=attempt_id: self._on_remote_import_completed(result, task, attempt))
            worker.failed.connect(lambda error, task=task_id, attempt=attempt_id: self._on_remote_import_failed(error, task, attempt))
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
            self.current_processing_task = None
            self.processing_record = None
            self.processing_source = None
            self.is_processing = False
            if self._running_remote_task_matches(task_id):
                self.task_manager.fail_running(task_id, error.message)
                self._persist_queued_tasks()
                self._start_next_processing_task()
            self._show_error(_remote_error_text(error))
            self._set_status(error.message)

    def _on_remote_probe_failed(self, error: object, task_id: str = "", attempt_id: str = "") -> None:
        if attempt_id and not self._is_current_remote_attempt(task_id, attempt_id):
            return
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
        self.current_processing_task = None
        self.processing_record = None
        self.processing_source = None
        self.is_processing = False
        if self._running_remote_task_matches(task_id):
            self.task_manager.fail_running(task_id, error.message)
            self._persist_queued_tasks()
            self._start_next_processing_task()
        self.recording_hint_label.setText("链接解析失败")
        self._show_error(_remote_error_text(error))
        self._set_status(error.message)

    def _cancel_remote_import(self, status: str, task_id: str = "") -> None:
        remote_task = self._active_remote_imports().pop(task_id, None)
        self._stop_remote_import_worker((remote_task or {}).get("worker"))
        record = (remote_task or {}).get("record")
        if record is not None:
            self.history_service.mark_input_error(record, status)
        self.current_processing_task = None
        self.processing_record = None
        self.processing_source = None
        self.is_processing = False
        if self._running_remote_task_matches(task_id):
            self.task_manager.cancel_running(task_id, status)
            self._persist_queued_tasks()
            self._start_next_processing_task()
        self.recording_hint_label.setText("准备捕获系统声音")
        self._set_status(status)

    def _on_remote_import_progress(self, text: str, percent: int | None = None, task_id: str = "", attempt_id: str = "") -> None:
        if attempt_id and not self._is_current_remote_attempt(task_id, attempt_id):
            return
        if task_id and task_id not in self._active_remote_imports():
            return
        stage, message = _remote_progress_stage(text)
        if self._running_remote_task_matches(task_id):
            self.task_manager.mark_running(task_id, stage, message, percent)
        self._set_status(message)
        self._refresh_history_status_indicators()

    def _on_remote_import_completed(self, result: object, task_id: str = "", attempt_id: str = "") -> None:
        if attempt_id and not self._is_current_remote_attempt(task_id, attempt_id):
            return
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
            self._bind_remote_task_record(task_id, record)
            self._select_record_by_key(record.record_key)
        if mode == "audio" and record:
            self.current_record = record
            if self.config["audio"].get("auto_transcribe", True):
                self.start_transcription(record.audio_path, record, source="remote_import")
            else:
                self._finish_processing(record, "已导入链接音频")
                self._finish_queue_task_success("已导入链接音频")
            return
        if record and self.config["audio"].get("auto_summarize", True) and getattr(result, "transcript_text", "").strip():
            self.processing_record = record
            self.processing_source = "remote_import"
            self.start_summarization(getattr(result, "transcript_text", ""), record)
            return
        self.current_processing_task = None
        self.processing_record = None
        self.processing_source = None
        self.is_processing = False
        if self._running_remote_task_matches(task_id):
            self.task_manager.complete_running(task_id, "已导入链接字幕" if mode == "subtitle" else "链接导入完成")
            self._persist_queued_tasks()
            self._start_next_processing_task()
        self._set_status("已导入链接字幕" if mode == "subtitle" else "链接导入完成")

    def _on_remote_import_failed(self, error: object, task_id: str = "", attempt_id: str = "") -> None:
        if attempt_id and not self._is_current_remote_attempt(task_id, attempt_id):
            return
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
        self.current_processing_task = None
        self.processing_record = None
        self.processing_source = None
        self.is_processing = False
        if self._running_remote_task_matches(task_id):
            self.task_manager.fail_running(task_id, error.message)
            self._persist_queued_tasks()
            self._start_next_processing_task()
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

    def _is_current_remote_attempt(self, task_id: str, attempt_id: str) -> bool:
        remote_task = self._remote_task(task_id)
        return bool(remote_task and remote_task.get("attempt_id") == attempt_id)

    def _bind_remote_task_record(self, task_id: str, record: object | None) -> None:
        if not task_id or record is None:
            return
        running = self.task_manager.running_process_task()
        if running is None or running.task_id != task_id:
            return
        running.record_key = record.record_key
        running.notebook_id = record.notebook_id
        running.record_id = record.record_id
        running.title = record.display_name

    def _running_remote_task_matches(self, task_id: str) -> bool:
        if not task_id:
            return False
        running = self.task_manager.running_process_task()
        return running is not None and running.task_id == task_id

    def prepare_remote_imports_for_close(self) -> None:
        interrupted_records = []
        for task_id, remote_task in list(self._active_remote_imports().items()):
            self._stop_remote_import_worker(remote_task.get("worker"))
            record = remote_task.get("record")
            if record is not None:
                updated = self.history_service.mark_input_error(record, "应用退出，远程导入已中断")
                interrupted_records.append(updated)
                self._add_history_notice_if_unselected(updated, "出现异常，点击查看详情")
            self._active_remote_imports().pop(task_id, None)
        if interrupted_records:
            self.load_recordings()

    def _stop_remote_import_worker(self, worker: object | None) -> None:
        if worker is None:
            return
        if hasattr(worker, "requestInterruption"):
            worker.requestInterruption()
        if hasattr(worker, "quit"):
            worker.quit()
        waited = False
        if hasattr(worker, "wait"):
            try:
                waited = bool(worker.wait(200))
            except TypeError:
                waited = bool(worker.wait())
        if not waited and hasattr(worker, "terminate"):
            worker.terminate()
            if hasattr(worker, "wait"):
                try:
                    worker.wait(200)
                except TypeError:
                    worker.wait()

    def _cancel_running_remote_import(self, task_id: str, message: str = "已取消链接导入") -> None:
        self._cancel_remote_import(message, task_id)

    def _stop_running_remote_import(self, task_id: str) -> None:
        remote_task = self._remote_task(task_id)
        self._stop_remote_import_worker((remote_task or {}).get("worker"))


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _remote_error_text(error: RemoteImportError) -> str:
    detail = _strip_ansi_escape_codes(error.detail or "").strip()
    if detail and detail != error.message:
        return f"{error.message}\n\n{detail}"
    return error.message


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi_escape_codes(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text)


def _remote_progress_stage(text: str) -> tuple[TaskStage, str]:
    value = (text or "").strip()
    if "解析" in value and "链接" in value:
        return TaskStage.PARSING_LINK, "解析链接中"
    if "字幕" in value and "失败" not in value:
        return TaskStage.EXTRACTING_SUBTITLE, "提取字幕中"
    if "音频" in value or "转换" in value or "下载" in value:
        return TaskStage.DOWNLOADING_AUDIO, "下载音频中"
    return TaskStage.PARSING_LINK, "解析链接中"
