from __future__ import annotations

import os
from collections import deque

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.asr.types import TranscriptionProgress
from src.workers import transcription as transcription_worker
from src.workers.transcription import (
    TranscriptionWorker,
    _crash_diagnostics,
    _crash_message,
    _hidden_creationflags,
)


def test_transcription_worker_maps_json_progress_payload() -> None:
    app = QApplication.instance() or QApplication([])
    worker = TranscriptionWorker("audio.wav")
    events: list[object] = []
    worker.progress.connect(events.append)

    worker._handle_worker_payload(
        {
            "kind": "transcription_progress",
            "stage": "transcribing",
            "percent": 37,
            "processed_seconds": 12.5,
            "total_seconds": 100.0,
            "message": "正在转录音频 1/3",
        }
    )
    app.processEvents()

    assert isinstance(events[0], TranscriptionProgress)
    assert events[0].percent == 37
    assert events[0].message == "正在转录音频 1/3"


def test_transcription_worker_crash_diagnostics_include_output_tail() -> None:
    output = deque(["native assert failed", "ggml stack"], maxlen=30)

    assert _crash_message(3221226505) == "转录进程异常退出（退出码 3221226505）"
    diagnostics = _crash_diagnostics(3221226505, output)

    assert diagnostics["error"]["error_type"] == "AsrWorkerProcessExited"
    assert diagnostics["error"]["exit_code"] == 3221226505
    assert "native assert failed" in diagnostics["error"]["diagnostic_message"]


def test_hidden_creationflags_adds_create_no_window(monkeypatch) -> None:
    monkeypatch.setattr(transcription_worker.sys, "platform", "win32")
    monkeypatch.setattr(transcription_worker.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    assert _hidden_creationflags(0x00000004) == 0x08000004


def test_transcription_worker_request_cancel_terminates_process() -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.terminated = False
            self.killed = False
            self.stdout = iter(())

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout=None) -> int:
            if timeout is not None:
                raise TimeoutError()
            return -15

    worker = TranscriptionWorker("audio.wav")
    process = FakeProcess()
    worker.process = process

    worker.request_cancel()

    assert worker.cancel_requested is True
    assert process.terminated is True
    assert process.killed is True
