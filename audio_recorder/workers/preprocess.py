"""音频预处理后台线程。"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..audio.preprocess import AudioInputError, AudioPreprocessRequest, normalize_audio


class AudioPreprocessWorker(QThread):
    """在后台线程中执行音视频标准化。"""

    progress = Signal(str, object)
    completed = Signal(object)
    failed = Signal(object)

    def __init__(self, request: AudioPreprocessRequest, parent=None, normalizer=normalize_audio, config: dict | None = None):
        super().__init__(parent)
        self.request = request
        self.normalizer = normalizer
        self.config = config

    def run(self) -> None:
        try:
            result = self.normalizer(self.request, progress_callback=self.progress.emit, config=self.config)
            self.completed.emit(result)
        except AudioInputError as exc:
            self.failed.emit(exc)
        except Exception as exc:
            self.failed.emit(AudioInputError("transcode_failed", "转码失败。", str(exc)))
