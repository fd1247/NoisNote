"""时间戳时间轴转换与导出工具。"""
from __future__ import annotations

import re
from html import escape
from typing import Any

from .types import TimelineSegment, TimelineToken

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
    current_tokens: list[TimelineToken] = []
    start: float | None = None
    end = 0.0

    for segment in word_segments:
        if start is None and segment.text.strip():
            start = segment.start
        current_texts.append(segment.text)
        current_tokens.append(TimelineToken(start=segment.start, end=segment.end, text=segment.text))
        end = max(end, segment.end)
        content = _normalize_timeline_text("".join(current_texts))
        if _SENTENCE_SPLIT_PATTERN.search(segment.text) or len(content) >= max_chars:
            if content:
                timeline.append(
                    TimelineSegment(
                        start=start if start is not None else segment.start,
                        end=end,
                        text=content,
                        tokens=_clean_tokens(current_tokens),
                    )
                )
            current_texts = []
            current_tokens = []
            start = None
            end = 0.0

    content = _normalize_timeline_text("".join(current_texts))
    if content:
        fallback_start = start if start is not None else (word_segments[-1].start if word_segments else 0.0)
        timeline.append(
            TimelineSegment(
                start=fallback_start,
                end=end,
                text=content,
                tokens=_clean_tokens(current_tokens),
            )
        )

    return timeline


def timeline_to_dicts(timeline: list[TimelineSegment]) -> list[dict[str, Any]]:
    """把时间轴片段序列化为稳定 JSON 结构。"""
    items: list[dict[str, Any]] = []
    for segment in timeline:
        if not segment.text.strip():
            continue
        item = {
            "start": round(max(0.0, segment.start), 3),
            "end": round(max(0.0, segment.end), 3),
            "text": segment.text,
        }
        tokens = _clean_tokens(segment.tokens)
        if tokens:
            item["tokens"] = [
                {
                    "start": round(max(0.0, token.start), 3),
                    "end": round(max(0.0, token.end), 3),
                    "text": token.text,
                }
                for token in tokens
            ]
        items.append(item)
    return items


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
        tokens = _tokens_from_dicts(item.get("tokens"))
        timeline.append(TimelineSegment(start=start, end=end, text=text, tokens=tokens))
    return sorted(timeline, key=lambda segment: (segment.start, segment.end))


def timeline_to_html(timeline: list[TimelineSegment], position_seconds: float | None = None) -> str:
    """把时间轴渲染为详情页可高亮的 HTML。"""
    active_sentence = _active_sentence_index(timeline, position_seconds)
    active_token = _active_token_index(timeline[active_sentence], position_seconds) if active_sentence is not None else None
    blocks = []
    for index, segment in enumerate(timeline):
        anchor = '<a name="timeline-current"></a>' if index == active_sentence else ""
        sentence_class = "timeline-sentence active" if index == active_sentence else "timeline-sentence"
        text_html = _segment_text_html(segment, active_token if index == active_sentence else None)
        blocks.append(
            (
                f"<tr class=\"{sentence_class}\">"
                f"<td class=\"timeline-time\">{anchor}{escape(format_display_time(segment.start))} - "
                f"{escape(format_display_time(segment.end))}</td>"
                f"<td class=\"timeline-content\">{text_html}</td>"
                "</tr>"
            )
        )
    return (
        "<html><head><style>"
        "body{font-family:'Microsoft YaHei UI','Segoe UI',sans-serif;font-size:14px;color:#111827;margin:0;}"
        ".timeline-table{border-collapse:separate;border-spacing:0 3px;width:100%;}"
        ".timeline-sentence td{padding:8px 10px;line-height:1.65;vertical-align:top;}"
        ".timeline-sentence.active td{background:#eef4ff;}"
        ".timeline-time{color:#6b7280;width:138px;padding-right:28px;white-space:nowrap;}"
        ".timeline-content{color:#111827;}"
        ".timeline-token{border-radius:4px;padding:1px 2px;background:#bfdbfe;color:#0f172a;}"
        "</style></head><body><table class=\"timeline-table\">"
        + "".join(blocks)
        + "</table></body></html>"
    )


def format_display_time(seconds: float) -> str:
    """把秒数格式化为界面展示用时间戳。"""
    milliseconds_total = _total_milliseconds(seconds)
    minutes = milliseconds_total // 60_000
    milliseconds_total %= 60_000
    secs = milliseconds_total // 1000
    millis = milliseconds_total % 1000
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


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
    milliseconds_total = _total_milliseconds(seconds)
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


def _total_milliseconds(seconds: Any) -> int:
    return int(round(max(0.0, _seconds(seconds)) * 1000))


def _normalize_timeline_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_tokens(tokens: list[TimelineToken]) -> list[TimelineToken]:
    clean: list[TimelineToken] = []
    for token in tokens:
        text = str(token.text or "")
        if not text.strip() and text != " ":
            continue
        end = max(token.start, token.end)
        clean.append(TimelineToken(start=max(0.0, token.start), end=end, text=text))
    return clean


def _tokens_from_dicts(items: Any) -> list[TimelineToken]:
    if not isinstance(items, list):
        return []
    tokens: list[TimelineToken] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        if text == "":
            continue
        start = _seconds(item.get("start", 0.0))
        end = _seconds(item.get("end", start))
        if end < start:
            end = start
        tokens.append(TimelineToken(start=start, end=end, text=text))
    return tokens


def _active_sentence_index(timeline: list[TimelineSegment], position_seconds: float | None) -> int | None:
    if position_seconds is None:
        return None
    position = max(0.0, float(position_seconds))
    for index, segment in enumerate(timeline):
        if segment.start <= position <= max(segment.start, segment.end):
            return index
    for index, segment in enumerate(timeline):
        if position < segment.start:
            return max(0, index - 1)
    return len(timeline) - 1 if timeline else None


def _active_token_index(segment: TimelineSegment, position_seconds: float | None) -> int | None:
    if position_seconds is None:
        return None
    position = max(0.0, float(position_seconds))
    tokens = _clean_tokens(segment.tokens)
    for index, token in enumerate(tokens):
        if token.start <= position <= max(token.start, token.end):
            return index
    return None


def _segment_text_html(segment: TimelineSegment, active_token: int | None) -> str:
    tokens = _clean_tokens(segment.tokens)
    if not tokens:
        return escape(segment.text)
    parts: list[str] = []
    for index, token in enumerate(tokens):
        text = escape(token.text)
        if index == active_token:
            parts.append(f"<span class=\"timeline-token\">{text}</span>")
        else:
            parts.append(text)
    return "".join(parts)
