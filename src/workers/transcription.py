"""ASR 转录后台线程。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from ..asr.types import TranscriptionProgress


class TranscriptionWorker(QThread):
    """在独立子进程中执行 ASR 转录，避免 native crash 带走主界面。"""

    progress = Signal(object)
    completed = Signal(str, object)
    failed = Signal(str, object)
    cancelled = Signal(str, object)

    def __init__(self, audio_file: str, parent=None):
        super().__init__(parent)
        self.audio_file = audio_file
        self.process: subprocess.Popen[str] | None = None
        self._completed = False
        self._failed = False
        self.cancel_requested = False
        self._output_tail: deque[str] = deque(maxlen=30)

    def request_cancel(self) -> None:
        self.cancel_requested = True
        process = self.process
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def run(self) -> None:
        command = _asr_worker_command(self.audio_file)
        try:
            popen_kwargs: dict[str, Any] = {
                "cwd": str(_project_root()),
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "env": _worker_environment(),
                "startupinfo": _hidden_startupinfo(),
            }
            creationflags = _hidden_creationflags()
            if creationflags:
                popen_kwargs["creationflags"] = creationflags
            self.process = subprocess.Popen(
                command,
                **popen_kwargs,
            )
            # 记录启动信息用于诊断
            self._output_tail.append(f"[cmd] {' '.join(command)}")
            self._read_worker_output()
            exit_code = self.process.wait()
            if self.cancel_requested:
                self.cancelled.emit("已取消转录", {"cancelled": True})
            elif not self._completed and not self._failed:
                self.failed.emit(_crash_message(exit_code), _crash_diagnostics(exit_code, self._output_tail))
        except Exception as exc:
            if self.cancel_requested:
                self.cancelled.emit("已取消转录", {"cancelled": True})
            else:
                self.failed.emit(str(exc), {})
        finally:
            self.process = None

    def _read_worker_output(self) -> None:
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            text = line.strip()
            if not text:
                continue
            self._output_tail.append(text)
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            self._handle_worker_payload(payload)

    def _handle_worker_payload(self, payload: dict[str, Any]) -> None:
        kind = payload.get("kind")
        if kind == "transcription_progress":
            self.progress.emit(
                TranscriptionProgress(
                    stage=str(payload.get("stage") or ""),
                    percent=int(payload.get("percent") or 0),
                    processed_seconds=payload.get("processed_seconds"),
                    total_seconds=payload.get("total_seconds"),
                    message=str(payload.get("message") or ""),
                )
            )
            return
        if kind == "text_progress":
            self.progress.emit(str(payload.get("message") or ""))
            return
        if kind == "completed":
            self._completed = True
            self.completed.emit(str(payload.get("text") or ""), payload.get("diagnostics") or {})
            return
        if kind == "failed":
            self._failed = True
            self.failed.emit(str(payload.get("error") or "转录失败"), payload.get("diagnostics") or {})


def _asr_worker_command(audio_file: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--asr-worker", audio_file]
    return [sys.executable, str(_project_root() / "main.py"), "--asr-worker", audio_file]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _worker_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _hidden_startupinfo() -> subprocess.STARTUPINFO | None:
    if sys.platform != "win32":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo


def _hidden_creationflags(existing_flags: int = 0) -> int:
    if sys.platform != "win32":
        return existing_flags
    return existing_flags | int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _crash_message(exit_code: int) -> str:
    return f"转录进程异常退出（退出码 {exit_code}）"


def _crash_diagnostics(exit_code: int, output_tail: deque[str]) -> dict[str, Any]:
    return {
        "error": {
            "user_message": _crash_message(exit_code),
            "diagnostic_message": "\n".join(output_tail),
            "error_type": "AsrWorkerProcessExited",
            "exit_code": exit_code,
        }
    }
