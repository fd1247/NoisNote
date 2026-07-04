"""远程媒体导入数据结构。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..history.service import HistoryRecord


DEFAULT_PREFERRED_SUBTITLE_LANGUAGES = (
    "zh-Hans",
    "zh-CN",
    "zh",
    "zh-Hant",
    "zh-TW",
    "en",
    "en-US",
    "en-GB",
)


@dataclass(frozen=True)
class RemoteSubtitle:
    """远程字幕候选。"""

    language: str
    name: str
    url: str
    extension: str
    is_auto: bool = False


@dataclass(frozen=True)
class RemoteMediaInfo:
    """远程媒体探测结果。"""

    url: str
    extractor: str
    webpage_url: str
    title: str
    duration_seconds: float | None
    video_id: str = ""
    subtitles: list[RemoteSubtitle] = field(default_factory=list)
    automatic_captions: list[RemoteSubtitle] = field(default_factory=list)


@dataclass(frozen=True)
class RemoteImportOptions:
    """一次远程导入的配置。"""

    url: str
    max_duration_seconds: int = 7200
    preferred_languages: tuple[str, ...] = DEFAULT_PREFERRED_SUBTITLE_LANGUAGES


@dataclass(frozen=True)
class RemoteImportResult:
    """远程导入完成结果。"""

    mode: Literal["subtitle", "audio"]
    record: HistoryRecord
    transcript_text: str = ""
    timeline_items: list[dict[str, Any]] = field(default_factory=list)
    subtitle_path: Path | None = None
    audio_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
