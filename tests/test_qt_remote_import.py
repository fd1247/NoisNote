from __future__ import annotations

import copy
import os
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.app.config import DEFAULT_MODEL_CATALOG, QWEN3_ASR_GGUF_06B_ID
from src.app.main_window import MainWindow
from src.history.service import HistoryService
from src.handlers.remote_import import _remote_error_text
from src.remote_import.errors import RemoteImportErrorKind, message_for_kind
from src.remote_import.service import RemoteImportError
from src.remote_import import RemoteImportOptions
from src.remote_import.types import RemoteMediaInfo
from src.tasks import TaskKind, TaskStage, TaskStatus


def make_config(root: Path) -> dict:
    return {
        "demo_audio_imported": True,
        "data_root": str(root),
        "selected_asr": {"model": QWEN3_ASR_GGUF_06B_ID, "model_path": "", "device": "auto"},
        "qwen3_asr_gguf": {
            "tool_dir": str(root / "vendor" / "qwen3-asr-gguf"),
            "chunk_size": 40.0,
            "memory_num": 1,
            "n_ctx": 2048,
            "context": "",
        },
        "llm": {"api_key": "", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
        "audio": {
            "output_dir": str(root / "recordings"),
            "auto_transcribe": False,
            "auto_summarize": False,
        },
        "models": {
            "root_dir": str(root / "models"),
            "catalog": copy.deepcopy(DEFAULT_MODEL_CATALOG),
            "downloaded": {},
        },
    }


def make_window(monkeypatch, tmp_path: Path) -> MainWindow:
    config = make_config(tmp_path)
    monkeypatch.setattr("src.app.main_window.get_config", lambda: config)
    monkeypatch.setattr("src.app.main_window.save_config", lambda _config: None)
    monkeypatch.setattr("src.handlers.settings.save_config", lambda _config: None)
    monkeypatch.setattr("src.app.main_window.ensure_dirs", lambda _config=None: None)
    monkeypatch.setattr("src.app.main_window.AudioRecorder", lambda output_dir: None)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    app.processEvents()
    return window


def _write_wav(path: Path, frames: int = 16000, rate: int = 16000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\0\0" * frames)
    return path


def wait_for_workers(window: MainWindow, timeout_ms: int = 1000) -> None:
    app = QApplication.instance() or QApplication([])
    elapsed = 0
    while window.active_workers and elapsed < timeout_ms:
        app.processEvents()
        QTest.qWait(10)
        elapsed += 10
    app.processEvents()


def test_remote_import_button_is_in_quick_toolbar(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)
    try:
        assert not hasattr(window, "remote_import_sidebar_button")
        assert window.remote_import_toolbar_button.toolTip() == "从链接导入"
    finally:
        window.close()


def test_remote_import_runs_admission_probe_before_creating_task(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)

    class FakeSignal:
        def __init__(self) -> None:
            self.callbacks = []

        def connect(self, callback) -> None:
            self.callbacks.append(callback)

    class FakeRemoteProbeWorker:
        def __init__(self, *_args, **_kwargs) -> None:
            self.progress = FakeSignal()
            self.completed = FakeSignal()
            self.failed = FakeSignal()
            self.finished = FakeSignal()
            self.started = False

        def start(self) -> None:
            self.started = True

    try:
        monkeypatch.setattr("src.handlers.remote_import.RemoteProbeWorker", FakeRemoteProbeWorker)

        window._start_remote_import("https://example.com/video")

        snapshot = window.task_manager.snapshot()
        assert snapshot.running == ()
        assert snapshot.queued == ()
        assert window.history_service.scan() == []
        assert len(window.active_remote_imports) == 1
        assert next(iter(window.active_remote_imports.values()))["phase"] == "admission_probe"
    finally:
        running = window.task_manager.running_process_task()
        if running is not None:
            window.task_manager.cancel_running(running.task_id, "cleanup")
        window.current_processing_task = None
        window.processing_source = None
        window.active_workers.clear()
        window.active_remote_imports = {}
        window.close()


def test_remote_import_rejects_full_queue_without_probe_or_record(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("src.tasks.manager.MAX_QUEUE_SIZE", 0)
    window = make_window(monkeypatch, tmp_path)
    try:
        errors: list[str] = []
        monkeypatch.setattr(window, "_show_error", lambda message: errors.append(message))
        monkeypatch.setattr(
            "src.handlers.remote_import.RemoteProbeWorker",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应启动预检")),
        )

        window._start_remote_import("https://example.com/video")

        assert errors == ["队列已满，请先移除任务或等待任务完成"]
        assert window.history_service.scan() == []
        assert window.task_manager.snapshot().queued == ()
        assert window.task_manager.snapshot().running == ()
    finally:
        window.close()


def test_remote_admission_probe_creates_record_before_enqueuing(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)
    try:
        info = RemoteMediaInfo(
            url="https://www.youtube.com/watch?v=demo",
            extractor="youtube",
            webpage_url="https://www.youtube.com/watch?v=demo",
            title="Remote Video",
            duration_seconds=30,
        )
        options = RemoteImportOptions(url=info.url)
        window.active_remote_imports = {"admission": {"url": info.url, "phase": "admission_probe"}}
        enqueued = []
        monkeypatch.setattr(
            window,
            "enqueue_record_processing",
            lambda record, **kwargs: enqueued.append((record, kwargs)) or object(),
        )

        window._on_remote_admission_probe_completed(info, options, "admission")

        assert len(enqueued) == 1
        record, kwargs = enqueued[0]
        assert record.record_key in {item.record_key for item in window.history_service.scan()}
        assert kwargs == {"source": "remote_import", "input_url": info.url}
    finally:
        window.active_remote_imports = {}
        window.close()


def test_remote_import_over_two_hours_cancel_does_not_create_record(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)

    class FakeRemoteImportService:
        def __init__(self, history_service, config=None):
            self.history_service = history_service

        def probe(self, url: str) -> RemoteMediaInfo:
            return RemoteMediaInfo(
                url=url,
                extractor="youtube",
                webpage_url=url,
                title="Long Video",
                duration_seconds=7201,
            )

    monkeypatch.setattr("src.handlers.remote_import.RemoteImportService", FakeRemoteImportService)
    monkeypatch.setattr("src.handlers.remote_import.confirm_without_icon", lambda *args, **kwargs: False)

    try:
        before = len(window.history_service.scan())
        window._start_remote_import("https://www.youtube.com/watch?v=demo")
        wait_for_workers(window)
        after = len(window.history_service.scan())

        assert after == before
        assert window.status_label.text() == "已取消链接导入"
    finally:
        window.close()


def test_remote_import_create_record_failure_is_handled(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)

    class FakeRemoteImportService:
        def __init__(self, history_service, config=None):
            self.history_service = history_service

        def probe(self, url: str) -> RemoteMediaInfo:
            return RemoteMediaInfo(
                url=url,
                extractor="youtube",
                webpage_url=url,
                title="Remote Video",
                duration_seconds=30,
            )

    errors: list[str] = []
    monkeypatch.setattr("src.handlers.remote_import.RemoteImportService", FakeRemoteImportService)
    monkeypatch.setattr(window.history_service, "create_remote_record", lambda _info: (_ for _ in ()).throw(OSError("bad record name")))
    monkeypatch.setattr(window, "_show_error", lambda message: errors.append(message))

    try:
        window._start_remote_import("https://www.youtube.com/shorts/qWFo8GKXHq8")
        wait_for_workers(window)

        assert not window.is_processing
        assert window.processing_record is None
        assert "remote_import" not in window.active_task_ids
        assert errors and "bad record name" in errors[-1]
    finally:
        window.close()


def test_remote_error_text_strips_ansi_escape_codes() -> None:
    error = RemoteImportError(
        RemoteImportErrorKind.DOWNLOAD_FAILED,
        "下载失败",
        "\x1b[0;31mERROR:\x1b[0m [BiliBili] Unable to download webpage",
    )

    text = _remote_error_text(error)

    assert "\x1b" not in text
    assert "[0;31m" not in text
    assert "ERROR:" in text


def test_remote_audio_completion_starts_transcription_in_same_task(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)
    try:
        record = window.history_service.adopt_audio_file(_write_wav(tmp_path / "remote.wav"))
        window.config["audio"]["auto_transcribe"] = True
        task = window.task_manager.enqueue_remote_import("https://example.com/video")
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: None)
        window.task_manager.start_next_if_idle()
        window.current_processing_task = task
        window.active_remote_imports = {task.task_id: {"record": record}}
        started: list[tuple[Path, str, str]] = []
        monkeypatch.setattr(window, "start_transcription", lambda audio, record=None, source="manual": started.append((audio, record.record_key, source)))
        result = type("Result", (), {"record": record, "mode": "audio"})()

        window._on_remote_import_completed(result, task.task_id)

        assert started == [(record.audio_path, record.record_key, "remote_import")]
        assert window.task_manager.snapshot().running[0].task_id == task.task_id
    finally:
        running = window.task_manager.running_process_task()
        if running is not None:
            window.task_manager.cancel_running(running.task_id, "cleanup")
        window.close()


def test_remote_audio_transcription_completion_uses_auto_summarize_option(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)
    try:
        record = window.history_service.adopt_audio_file(_write_wav(tmp_path / "remote-auto-summary.wav"))
        window.config["audio"]["auto_summarize"] = True
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: None)
        task = window.enqueue_remote_import_task("https://example.com/video")
        assert task is not None
        window.current_processing_task = task
        window.processing_record = record
        window.processing_source = "remote_import"
        summaries: list[tuple[str, str]] = []
        monkeypatch.setattr(
            window,
            "start_summarization",
            lambda text, record=None: summaries.append((text, record.record_key if record else "")),
        )

        window._on_transcription_completed("remote transcript")

        assert summaries == [("remote transcript", record.record_key)]
    finally:
        running = window.task_manager.running_process_task()
        if running is not None:
            window.task_manager.cancel_running(running.task_id, "cleanup")
        window.current_processing_task = None
        window.processing_record = None
        window.processing_source = None
        window.close()


def test_remote_subtitle_completion_does_not_enqueue_processing(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)
    try:
        record = window.history_service.adopt_audio_file(_write_wav(tmp_path / "subtitle.wav"))
        window.config["audio"]["auto_transcribe"] = True
        window.config["audio"]["auto_summarize"] = False
        enqueued: list[str] = []
        monkeypatch.setattr(
            window,
            "enqueue_record_processing",
            lambda record, source, **kwargs: enqueued.append(record.record_key),
        )
        result = type("Result", (), {"record": record, "mode": "subtitle", "transcript_text": "subtitle text"})()

        window._on_remote_import_completed(result)

        assert enqueued == []
    finally:
        window.close()


def test_remote_subtitle_completion_starts_summary_in_same_task(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)
    try:
        subtitle_record = window.history_service.adopt_audio_file(_write_wav(tmp_path / "subtitle-summary.wav"))
        window.config["audio"]["auto_summarize"] = True
        task = window.task_manager.enqueue_remote_import("https://example.com/video")
        monkeypatch.setattr(window, "_execute_processing_task", lambda task: None)
        window.task_manager.start_next_if_idle()
        window.current_processing_task = task
        window.active_remote_imports = {task.task_id: {"record": subtitle_record}}
        assert window.current_processing_task is not None

        started: list[str] = []
        monkeypatch.setattr(window, "start_summarization", lambda text, record=None: started.append(text))
        result = type(
            "Result",
            (),
            {"record": subtitle_record, "mode": "subtitle", "transcript_text": "subtitle text"},
        )()

        window._on_remote_import_completed(result, task.task_id)

        assert started == ["subtitle text"]
        running = window.task_manager.snapshot().running[0]
        assert running.task_id == task.task_id
        assert running.record_key == subtitle_record.record_key
    finally:
        running = window.task_manager.running_process_task()
        if running is not None:
            window.task_manager.cancel_running(running.task_id, "cleanup")
        window.current_processing_task = None
        window.processing_record = None
        window.processing_source = None
        window.is_processing = False
        window.close()


def test_two_remote_imports_complete_and_fail_with_separate_records(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)
    try:
        first = window.history_service.adopt_audio_file(_write_wav(tmp_path / "first.wav"))
        second = window.history_service.adopt_audio_file(_write_wav(tmp_path / "second.wav"))
        window.active_remote_imports = {
            "remote-first": {"record": first, "url": "https://example.com/first"},
            "remote-second": {"record": second, "url": "https://example.com/second"},
        }
        monkeypatch.setattr(window, "_show_error", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(window, "_handle_audio_record_ready", lambda *_args, **_kwargs: None)

        window._on_remote_import_completed(
            type("Result", (), {"record": first, "mode": "audio"})(),
            "remote-first",
        )
        window._on_remote_import_failed(
            RemoteImportError(
                RemoteImportErrorKind.DOWNLOAD_FAILED,
                message_for_kind(RemoteImportErrorKind.DOWNLOAD_FAILED),
                "second failed",
            ),
            "remote-second",
        )

        refreshed = {record.record_id: record for record in window.history_service.scan()}
        assert not refreshed[first.record_id].input_error
        assert refreshed[second.record_id].input_error
        assert window.active_remote_imports == {}
    finally:
        window.close()


def test_remote_import_ignores_stale_remote_import_limit(monkeypatch, tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config["tasks"] = {"max_remote_imports": 1}
    monkeypatch.setattr("src.app.main_window.get_config", lambda: config)
    monkeypatch.setattr("src.app.main_window.save_config", lambda _config: None)
    monkeypatch.setattr("src.app.main_window.confirm_without_icon", lambda *args, **kwargs: True)
    monkeypatch.setattr("src.handlers.settings.save_config", lambda _config: None)
    monkeypatch.setattr("src.app.main_window.ensure_dirs", lambda _config=None: None)
    monkeypatch.setattr("src.app.main_window.AudioRecorder", lambda output_dir: None)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    app.processEvents()

    class FakeSignal:
        def connect(self, _callback) -> None:
            return None

    class FakeRemoteProbeWorker:
        def __init__(self, *_args, **_kwargs) -> None:
            self.progress = FakeSignal()
            self.completed = FakeSignal()
            self.failed = FakeSignal()
            self.finished = FakeSignal()

        def start(self) -> None:
            return None

    try:
        monkeypatch.setattr("src.handlers.remote_import.RemoteProbeWorker", FakeRemoteProbeWorker)
        window.active_remote_imports = {"remote-existing": {"url": "https://example.com/old"}}
        errors: list[str] = []
        monkeypatch.setattr(window, "_show_error", lambda message: errors.append(message))

        window._start_remote_import("https://example.com/new")

        assert errors == []
        assert len(window.active_remote_imports) == 2
        assert any(task.get("url") == "https://example.com/new" for task in window.active_remote_imports.values())
    finally:
        window.active_workers.clear()
        window.close()


def test_remote_subtitle_record_disables_playback(monkeypatch, tmp_path: Path) -> None:
    window = make_window(monkeypatch, tmp_path)
    try:
        service = HistoryService(tmp_path / "recordings")
        info = RemoteMediaInfo(
            url="https://www.youtube.com/watch?v=demo",
            extractor="youtube",
            webpage_url="https://www.youtube.com/watch?v=demo",
            title="Subtitle Only",
            duration_seconds=60,
        )
        record = service.create_remote_record(info)
        service.save_transcript(record, "字幕文本")
        record = service.save_remote_metadata(record, {"source_kind": "remote_subtitle", "transcript_source": "external_subtitle"})
        window.history_service = service
        window.load_recordings()
        window.select_history_index(0)

        assert window.current_record is not None
        assert not window.current_record.audio_path.exists()
        assert window.current_record.has_transcript
        assert window.playback_play_button.isEnabled()
        assert window.transcript_text.toPlainText() == "字幕文本"
    finally:
        window.close()
