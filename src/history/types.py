"""历史记录数据模型。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def format_duration_seconds(seconds: float | int | None) -> str:
    """按历史记录音频时长格式展示秒数。"""
    if seconds is None:
        return "--:--"
    total = max(0, int(round(seconds)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds_part = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"
    return f"{minutes:02d}:{seconds_part:02d}"


@dataclass(frozen=True)
class NotebookConfig:
    """历史笔记本配置。"""

    notebook_id: str
    name: str
    path: Path
    is_default: bool = False


@dataclass(frozen=True)
class MoveRecordResult:
    """跨笔记本移动记录的结果。"""

    success: bool
    source_dir: Path
    target_dir: Path
    message: str


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
    notebook_id: str = "default"
    notebook_name: str = "默认笔记本"
    notebook_path: Path | None = None
    last_error: dict[str, Any] | None = None
    source_kind: str = ""
    original_file_path: Path | None = None
    normalized_audio_path: Path | None = None
    input_error: dict[str, Any] | None = None
    audio_format: dict[str, Any] | None = None
    storage_mode: str = ""
    external_subtitle_file: str = "external_subtitle.srt"

    @property
    def record_key(self) -> str:
        return f"{self.notebook_id}:{self.record_id}"

    @property
    def display_name(self) -> str:
        if self._parse_record_id_as_timestamp() is None:
            return self.record_id
        return self.created_at.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def display_subtitle(self) -> str:
        return f"{self.duration_text} · {format_size(self.total_size_bytes)}"

    @property
    def duration_text(self) -> str:
        return format_duration_seconds(self.duration_seconds)

    @property
    def size_mb(self) -> float:
        return self.total_size_bytes / (1024 * 1024)

    @property
    def has_transcript(self) -> bool:
        return self.transcript_path.exists()

    @property
    def has_summary(self) -> bool:
        return self.summary_path.exists()

    @property
    def external_subtitle_path(self) -> Path:
        return self.record_dir / self.external_subtitle_file

    @property
    def timeline_path(self) -> Path:
        return self.record_dir / "timeline.json"

    @property
    def has_timeline(self) -> bool:
        return self.timeline_path.exists()

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
