"""MainWindow 业务逻辑 Mixin。"""
from .media_import import ImportHandlers
from .processing import ProcessingHandlers
from .recording import RecordingHandlers
from .settings import SettingsHandlers
from .summary import SummaryHandlers
from .transcription import TranscriptionHandlers

__all__ = [
    "ImportHandlers",
    "ProcessingHandlers",
    "RecordingHandlers",
    "SettingsHandlers",
    "SummaryHandlers",
    "TranscriptionHandlers",
]
