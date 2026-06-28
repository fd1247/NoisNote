"""历史记录数据模型。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class HistoryStatus(str, Enum):
    """历史记录处理状态。"""

    AUDIO_ONLY = "audio_only"
    TRANSCRIBED = "transcribed"
    SUMMARIZED = "summarized"
    EXPORTED = "exported"
    MISSING_AUDIO = "missing_audio"
    ERROR = "error"


@dataclass(frozen=True)
class DeleteResult:
    """历史记录删除结果。"""

    success: bool
    deleted_paths: tuple[Path, ...]
    skipped_paths: tuple[Path, ...]
    message: str


@dataclass(frozen=True)
class HistoryRecord:
    """历史列表中的一条录音记录。"""

    record_id: str
    layout: str
    record_dir: Path
    audio_path: Path
    transcript_path: Path
    summary_path: Path
    markdown_path: Path
    metadata_path: Path
    created_at: datetime
    duration_seconds: float | None
    audio_size_bytes: int
    total_size_bytes: int
    status: HistoryStatus
    error_message: str = ""
    source_kind: str = ""
    original_file_path: Path | None = None
    normalized_audio_path: Path | None = None
    input_error: dict[str, Any] | None = None
    audio_format: dict[str, Any] | None = None
    storage_mode: str = ""

    @property
    def display_name(self) -> str:
        if self._parse_record_id_as_timestamp() is None:
            return self.record_id
        return self.created_at.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def display_subtitle(self) -> str:
        return (
            f"{self.duration_text} · {format_size(self.total_size_bytes)} · "
            f"{self.status_text}"
        )

    @property
    def duration_text(self) -> str:
        if self.duration_seconds is None:
            return "--:--"
        total = max(0, int(round(self.duration_seconds)))
        hours = total // 3600
        minutes = (total % 3600) // 60
        seconds = total % 60
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def status_text(self) -> str:
        labels = {
            HistoryStatus.AUDIO_ONLY: "仅录音",
            HistoryStatus.TRANSCRIBED: "已转录",
            HistoryStatus.SUMMARIZED: "已总结",
            HistoryStatus.EXPORTED: "已导出",
            HistoryStatus.MISSING_AUDIO: "缺少录音",
            HistoryStatus.ERROR: "记录异常",
        }
        return labels.get(self.status, "未知状态")

    @property
    def size_mb(self) -> float:
        return self.total_size_bytes / (1024 * 1024)

    @property
    def has_transcript(self) -> bool:
        return self.transcript_path.exists()

    @property
    def has_summary(self) -> bool:
        return self.summary_path.exists()

    def _parse_record_id_as_timestamp(self) -> datetime | None:
        for fmt in ("%Y%m%d_%H%M%S", "%Y%m%d-%H%M%S"):
            try:
                return datetime.strptime(self.record_id, fmt)
            except ValueError:
                continue
        return None

def format_size(size_bytes: int) -> str:
    """格式化文件大小。"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


