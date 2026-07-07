"""时间轴转换、分句和导出工具。"""
from __future__ import annotations

import re
from typing import Any

from .types import TimelineSegment, TimelineToken

_STRONG_END_PATTERN = re.compile(r"[。！？!?\.]")
_WEAK_SPLIT_PATTERN = re.compile(r"[，、；：,;:]")
_BLANK_LINE_PATTERN = re.compile(r"\n\s*\n")
_ENGLISH_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
_CJK_CHAR_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_CLOSING_SENTENCE_MARKS = set("”’」』】）》〉)")
_DEFAULT_MAX_SEGMENT_WORDS = 120
_DEFAULT_MIN_SEGMENT_WORDS = 3


def alignment_items_to_timeline(
    items: list[Any] | tuple[Any, ...] | None,
    *,
    max_words: int = _DEFAULT_MAX_SEGMENT_WORDS,
    min_words: int = _DEFAULT_MIN_SEGMENT_WORDS,
) -> list[TimelineSegment]:
    """将 vendor 字级 alignment items 聚合成句级时间轴。"""
    word_segments = _alignment_items_to_word_segments(items)
    return _word_segments_to_sentence_timeline(word_segments, max_words=max_words, min_words=min_words)


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
    max_words: int = _DEFAULT_MAX_SEGMENT_WORDS,
    min_words: int = _DEFAULT_MIN_SEGMENT_WORDS,
) -> list[TimelineSegment]:
    max_words = max(1, int(max_words or _DEFAULT_MAX_SEGMENT_WORDS))
    min_words = max(1, int(min_words or _DEFAULT_MIN_SEGMENT_WORDS))
    rough_sentences: list[list[TimelineToken]] = []
    current_tokens: list[TimelineToken] = []

    for segment in word_segments:
        if _BLANK_LINE_PATTERN.search(segment.text):
            if _tokens_text(current_tokens):
                rough_sentences.append(current_tokens)
            current_tokens = []
            continue
        token = TimelineToken(start=segment.start, end=segment.end, text=segment.text)
        for piece in _split_token_at_sentence_boundaries(token):
            current_tokens.append(piece)
            if _ends_sentence(piece.text):
                if _tokens_text(current_tokens):
                    rough_sentences.append(current_tokens)
                current_tokens = []

    if _tokens_text(current_tokens):
        rough_sentences.append(current_tokens)

    split_sentences: list[list[TimelineToken]] = []
    for sentence in rough_sentences:
        split_sentences.extend(_split_tokens_by_word_limit(sentence, max_words))

    return [_tokens_to_segment(tokens) for tokens in _merge_short_sentences(split_sentences, min_words)]


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
    """从 timeline.json 结构恢复时间轴片段。"""
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


def _tokens_text(tokens: list[TimelineToken]) -> str:
    return _normalize_timeline_text("".join(token.text for token in tokens))


def _token_word_count(token: TimelineToken) -> int:
    text = token.text or ""
    english_spans = list(_ENGLISH_WORD_PATTERN.finditer(text))
    count = len(english_spans) + len(_CJK_CHAR_PATTERN.findall(text))
    stripped = text.strip()
    if count == 0 and stripped and not _STRONG_END_PATTERN.fullmatch(stripped) and not _WEAK_SPLIT_PATTERN.fullmatch(stripped):
        return 1
    return count


def _tokens_word_count(tokens: list[TimelineToken]) -> int:
    return sum(_token_word_count(token) for token in tokens)


def _ends_sentence(text: str) -> bool:
    stripped = (text or "").rstrip()
    while stripped and stripped[-1] in _CLOSING_SENTENCE_MARKS:
        stripped = stripped[:-1].rstrip()
    return bool(stripped and _STRONG_END_PATTERN.search(stripped[-1]))


def _split_token_at_sentence_boundaries(token: TimelineToken) -> list[TimelineToken]:
    text = str(token.text or "")
    if not text or not _STRONG_END_PATTERN.search(text):
        return [token]

    boundaries: list[int] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if not _STRONG_END_PATTERN.fullmatch(char):
            index += 1
            continue
        split_at = index + 1
        while split_at < length and text[split_at] in _CLOSING_SENTENCE_MARKS:
            split_at += 1
        if split_at < length:
            boundaries.append(split_at)
        index = split_at

    if not boundaries:
        return [token]

    parts: list[str] = []
    start_index = 0
    for boundary in boundaries:
        part = text[start_index:boundary]
        if part:
            parts.append(part)
        start_index = boundary
    tail = text[start_index:]
    if tail:
        parts.append(tail)

    if len(parts) <= 1:
        return [token]

    duration = max(0.0, token.end - token.start)
    total_units = max(1, sum(len(part) for part in parts))
    pieces: list[TimelineToken] = []
    elapsed_units = 0
    for part in parts:
        piece_start = token.start + duration * (elapsed_units / total_units)
        elapsed_units += len(part)
        piece_end = token.start + duration * (elapsed_units / total_units)
        pieces.append(TimelineToken(start=piece_start, end=piece_end, text=part))
    return pieces


def _split_tokens_by_word_limit(tokens: list[TimelineToken], max_words: int) -> list[list[TimelineToken]]:
    if _tokens_word_count(tokens) <= max_words:
        return [tokens]

    split_index = _weak_split_index_near_middle(tokens, max_words)
    if split_index is None:
        split_index = _hard_split_index(tokens, max_words)
    if split_index <= 0 or split_index >= len(tokens):
        return [tokens]

    return (
        _split_tokens_by_word_limit(tokens[:split_index], max_words)
        + _split_tokens_by_word_limit(tokens[split_index:], max_words)
    )


def _weak_split_index_near_middle(tokens: list[TimelineToken], max_words: int) -> int | None:
    total = _tokens_word_count(tokens)
    if total <= max_words:
        return None
    target = total / 2
    best: tuple[float, int] | None = None
    running = 0
    for index, token in enumerate(tokens):
        running += _token_word_count(token)
        if not _WEAK_SPLIT_PATTERN.search(token.text or ""):
            continue
        left_count = running
        right_count = total - running
        if left_count <= 0 or right_count <= 0:
            continue
        score = abs(left_count - target)
        if left_count <= max_words or right_count <= max_words:
            score -= 0.25
        candidate = (score, index + 1)
        if best is None or candidate < best:
            best = candidate
    return best[1] if best else None


def _hard_split_index(tokens: list[TimelineToken], max_words: int) -> int:
    running = 0
    for index, token in enumerate(tokens):
        running += _token_word_count(token)
        if running >= max_words:
            return max(1, index + 1)
    return max(1, len(tokens) // 2)


def _merge_short_sentences(sentences: list[list[TimelineToken]], min_words: int) -> list[list[TimelineToken]]:
    merged: list[list[TimelineToken]] = []
    index = 0
    while index < len(sentences):
        current = list(sentences[index])
        if _tokens_word_count(current) < min_words and index + 1 < len(sentences):
            current = _join_token_groups(current, sentences[index + 1])
            index += 2
        else:
            index += 1
        if _tokens_word_count(current) < min_words and merged:
            merged[-1] = _join_token_groups(merged[-1], current)
        else:
            merged.append(current)
    return [tokens for tokens in merged if _tokens_text(tokens)]


def _join_token_groups(left: list[TimelineToken], right: list[TimelineToken]) -> list[TimelineToken]:
    if not left:
        return list(right)
    if not right:
        return list(left)
    joined = list(left)
    previous = joined[-1].text or ""
    next_text = right[0].text or ""
    if previous and next_text and not previous[-1].isspace() and not next_text[0].isspace():
        boundary = max(joined[-1].end, right[0].start)
        joined.append(TimelineToken(start=boundary, end=boundary, text=" "))
    joined.extend(right)
    return joined


def _tokens_to_segment(tokens: list[TimelineToken]) -> TimelineSegment:
    clean_tokens = _clean_tokens(tokens)
    visible = [token for token in clean_tokens if token.text.strip()]
    start = visible[0].start if visible else (clean_tokens[0].start if clean_tokens else 0.0)
    end = max((token.end for token in clean_tokens), default=start)
    return TimelineSegment(start=start, end=end, text=_tokens_text(clean_tokens), tokens=clean_tokens)


def _clean_tokens(tokens: list[TimelineToken]) -> list[TimelineToken]:
    clean: list[TimelineToken] = []
    for token in tokens:
        text = str(token.text or "")
        if not text.strip():
            if text:
                text = " "
            else:
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
