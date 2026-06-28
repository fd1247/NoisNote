"""LLM 总结后台线程。"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..llm.summarizer import Summarizer


class SummaryWorker(QThread):
    """在后台线程中执行 LLM 总结。"""

    progress = Signal(str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, text: str, config: dict, parent=None):
        super().__init__(parent)
        self.text = text
        self.config = config

    def run(self) -> None:
        try:
            summarizer = Summarizer()
            summary = summarizer.summarize(
                self.text,
                self.config,
                on_progress=self.progress.emit,
            )
            summarizer.cleanup()
            self.completed.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))
