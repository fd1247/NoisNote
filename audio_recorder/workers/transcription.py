"""ASR 转录后台线程。"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..asr.engine import TranscriptionEngine


class TranscriptionWorker(QThread):
    """在后台线程中执行 ASR 转录。"""

    progress = Signal(object)
    completed = Signal(str, object)
    failed = Signal(str, object)

    def __init__(self, audio_file: str, parent=None):
        super().__init__(parent)
        self.audio_file = audio_file

    def run(self) -> None:
        engine = TranscriptionEngine()
        try:
            text = engine.transcribe(self.audio_file, on_progress=self.progress.emit)
            self.completed.emit(text, engine.last_diagnostics)
        except Exception as exc:
            self.failed.emit(str(exc), engine.last_diagnostics)
        finally:
            engine.close()
