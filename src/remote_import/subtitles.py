"""外部字幕选择、转换和解析。"""
from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any

from .types import DEFAULT_PREFERRED_SUBTITLE_LANGUAGES, RemoteMediaInfo, RemoteSubtitle

_SRT_TIME_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
)


def select_preferred_subtitle(
    info: RemoteMediaInfo,
    languages: tuple[str, ...] = DEFAULT_PREFERRED_SUBTITLE_LANGUAGES,
) -> RemoteSubtitle | None:
    """按语言优先级选择字幕，人工字幕优先于自动字幕。"""
    manual_by_lang = _first_by_language(info.subtitles)
    auto_by_lang = _first_by_language(info.automatic_captions)
    for language in languages:
        if language in manual_by_lang:
            return manual_by_lang[language]
    for language in languages:
        if language in auto_by_lang:
            return auto_by_lang[language]
    return info.subtitles[0] if info.subtitles else (info.automatic_captions[0] if info.automatic_captions else None)


def normalize_subtitle_file(source: Path, target: Path) -> Path:
    """把 SRT/VTT/常见 JSON 字幕转换为标准 SRT。"""
    text = source.read_text(encoding="utf-8", errors="replace")
    suffix = source.suffix.lower()
    if suffix == ".srt":
        srt_text = _normalize_srt_text(text)
    elif suffix == ".vtt":
        srt_text = _vtt_to_srt(text)
    elif suffix == ".json":
        srt_text = _json_to_srt(text)
    else:
        srt_text = _vtt_to_srt(text) if "-->" in text else _normalize_srt_text(text)
    target.write_text(srt_text, encoding="utf-8")
    return target


def parse_srt_to_transcript_and_timeline(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """从 SRT 生成纯文本和 NoisNote 时间轴。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    entries = _parse_srt_entries(text)
    transcript_lines = [entry["text"] for entry in entries if entry["text"].strip()]
    transcript = "\n".join(transcript_lines).strip()
    return transcript, entries


def _first_by_language(subtitles: list[RemoteSubtitle]) -> dict[str, RemoteSubtitle]:
    result: dict[str, RemoteSubtitle] = {}
    for subtitle in subtitles:
        result.setdefault(subtitle.language, subtitle)
    return result


def _normalize_srt_text(text: str) -> str:
    entries = _parse_srt_entries(text)
    return _entries_to_srt(entries)


def _vtt_to_srt(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in text.replace("\ufeff", "").splitlines():
        stripped = line.strip()
        if not stripped or stripped == "WEBVTT" or stripped.startswith(("NOTE", "STYLE", "REGION")):
            cleaned_lines.append("" if not stripped else stripped)
            continue
        if "-->" in stripped:
            stripped = re.sub(r"\s+(align|line|position|size|vertical):\S+", "", stripped)
        cleaned_lines.append(stripped)
    entries = _parse_srt_entries("\n".join(cleaned_lines))
    return _entries_to_srt(entries)


def _json_to_srt(text: str) -> str:
    data = json.loads(text)
    if isinstance(data, dict):
        items = data.get("body") or data.get("items") or data.get("subtitles") or []
    else:
        items = data
    entries: list[dict[str, Any]] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            start = _float_or_none(item.get("from") or item.get("start") or item.get("start_time"))
            end = _float_or_none(item.get("to") or item.get("end") or item.get("end_time"))
            content = str(item.get("content") or item.get("text") or "").strip()
            if start is None or end is None or not content:
                continue
            entries.append({"start": start, "end": end, "text": _clean_caption_text(content), "tokens": []})
    return _entries_to_srt(entries)


def _parse_srt_entries(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    lines = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.isdigit() and index + 1 < len(lines):
            index += 1
            line = lines[index].strip()
        match = _SRT_TIME_RE.search(line)
        if not match:
            index += 1
            continue
        start = _parse_timestamp(match.group("start"))
        end = _parse_timestamp(match.group("end"))
        index += 1
        text_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].strip())
            index += 1
        caption_text = _clean_caption_text(" ".join(text_lines))
        if caption_text:
            entries.append({"start": start, "end": end, "text": caption_text, "tokens": []})
    return entries


def _entries_to_srt(entries: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, entry in enumerate(entries, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_format_srt_time(entry['start'])} --> {_format_srt_time(entry['end'])}",
                    str(entry["text"]).strip(),
                ]
            )
        )
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def _parse_timestamp(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _format_srt_time(seconds: object) -> str:
    total = max(0.0, float(seconds))
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = int(total % 60)
    millis = int(round((total - int(total)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _clean_caption_text(text: str) -> str:
    value = re.sub(r"<[^>]+>", "", text)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
