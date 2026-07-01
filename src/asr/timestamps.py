"""时间戳时间轴转换与导出工具。"""
from __future__ import annotations

import re
from typing import Any

from .types import TimelineSegment

_SENTENCE_SPLIT_PATTERN = re.compile(r"[，。？！；：\n]|[,.?!;:]\s*")
_DEFAULT_MAX_SEGMENT_CHARS = 40


def alignment_items_to_timeline(items: list[Any] | tuple[Any, ...] | None) -> list[TimelineSegment]:
    """把 vendor 字级 alignment items 聚合成应用内部逐句时间轴片段。"""
    word_segments = _alignment_items_to_word_segments(items)
    return _word_segments_to_sentence_timeline(word_segments)


def _alignment_items_to_word_segments(items: list[Any] | tuple[Any, ...] | None) -> list[TimelineSegment]:
    timeline: list[TimelineSegment] = []
    for item in items or []:
        text = str(_first_attr(item, "text", "word", default="") or "")
        if text == "":
            continue
        start = _seconds(_first_attr(item, "start", "start_time", "begin", default=0.0))
        end = _seconds(_first_attr(item, "end", "end_time", "finish", default=start))
        if end < start:
            end = start
        timeline.append(TimelineSegment(start=start, end=end, text=text))
    return sorted(timeline, key=lambda segment: (segment.start, segment.end))


def _word_segments_to_sentence_timeline(
    word_segments: list[TimelineSegment],
    max_chars: int = _DEFAULT_MAX_SEGMENT_CHARS,
) -> list[TimelineSegment]:
    timeline: list[TimelineSegment] = []
    current_texts: list[str] = []
    start: float | None = None
    end = 0.0

    for segment in word_segments:
        if start is None and segment.text.strip():
            start = segment.start
        current_texts.append(segment.text)
        end = max(end, segment.end)
        content = _normalize_timeline_text("".join(current_texts))
        if _SENTENCE_SPLIT_PATTERN.search(segment.text) or len(content) >= max_chars:
            if content:
                timeline.append(TimelineSegment(start=start if start is not None else segment.start, end=end, text=content))
            current_texts = []
            start = None
            end = 0.0

    content = _normalize_timeline_text("".join(current_texts))
    if content:
        fallback_start = start if start is not None else (word_segments[-1].start if word_segments else 0.0)
        timeline.append(TimelineSegment(start=fallback_start, end=end, text=content))

    return timeline


def timeline_to_dicts(timeline: list[TimelineSegment]) -> list[dict[str, float | str]]:
    """把时间轴片段序列化为稳定 JSON 结构。"""
    return [
        {
            "start": round(max(0.0, segment.start), 3),
            "end": round(max(0.0, segment.end), 3),
            "text": segment.text,
        }
        for segment in timeline
        if segment.text.strip()
    ]


def timeline_from_dicts(items: list[dict[str, Any]] | None) -> list[TimelineSegment]:
    """从历史 JSON 结构恢复时间轴片段。"""
    timeline: list[TimelineSegment] = []
    for item in items or []:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start = _seconds(item.get("start", 0.0))
        end = _seconds(item.get("end", start))
        if end < start:
            end = start
        timeline.append(TimelineSegment(start=start, end=end, text=text))
    timeline = sorted(timeline, key=lambda segment: (segment.start, segment.end))
    if _looks_like_word_level_timeline(timeline):
        return _word_segments_to_sentence_timeline(timeline)
    return timeline


def timeline_to_srt(timeline: list[TimelineSegment]) -> str:
    """生成 SRT 字幕内容。"""
    blocks: list[str] = []
    for index, segment in enumerate([item for item in timeline if item.text.strip()], start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_time(segment.start)} --> {format_srt_time(segment.end)}",
                    segment.text.strip(),
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def format_srt_time(seconds: float) -> str:
    """把秒数格式化为 SRT 时间戳。"""
    milliseconds_total = int(round(max(0.0, seconds) * 1000))
    hours = milliseconds_total // 3_600_000
    milliseconds_total %= 3_600_000
    minutes = milliseconds_total // 60_000
    milliseconds_total %= 60_000
    secs = milliseconds_total // 1000
    millis = milliseconds_total % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def is_timeline_monotonic(timeline: list[TimelineSegment]) -> bool:
    """检查时间轴是否单调递增。"""
    last_end = 0.0
    for segment in timeline:
        if segment.start < 0 or segment.end < segment.start or segment.start < last_end:
            return False
        last_end = segment.end
    return True


def _first_attr(item: Any, *names: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        for name in names:
            if name in item:
                return item[name]
        return default
    for name in names:
        if hasattr(item, name):
            return getattr(item, name)
    return default


def _seconds(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_timeline_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_word_level_timeline(timeline: list[TimelineSegment]) -> bool:
    if len(timeline) < 3:
        return False
    short_count = sum(1 for segment in timeline if len(segment.text.strip()) <= 1)
    return short_count / len(timeline) >= 0.6
