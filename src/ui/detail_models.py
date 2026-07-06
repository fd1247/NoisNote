"""详情 WebView 的纯数据模型与消息协议。"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.asr.timestamps import format_display_time
from src.history.types import format_size


_VALID_MODES = {"transcript", "timeline", "summary"}
_MISSING = "--"


@dataclass(frozen=True)
class DetailCommand:
    """详情页前端发回主进程的命令。"""

    command: str
    payload: dict[str, Any]


def build_detail_payload(
    record: Any,
    mode: str,
    revision: int,
    content: str,
    timeline: list[dict[str, Any]] | None,
    position_seconds: float | None,
    is_playing: bool,
) -> dict[str, Any]:
    """构建发送给详情 WebView 的渲染载荷。"""

    selected_mode = mode if mode in _VALID_MODES else "transcript"
    return {
        "revision": revision,
        "recordKey": record.record_key,
        "mode": selected_mode,
        "title": record.display_name,
        "content": content,
        "timeline": normalize_timeline_items(timeline),
        "playback": {
            "positionSeconds": _non_negative_float(position_seconds),
            "isPlaying": bool(is_playing),
        },
    }


def normalize_timeline_items(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """把历史时间轴条目归一化为 WebView 可直接消费的字典。"""

    if not isinstance(items, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start = _non_negative_float(item.get("start"))
        end = _coerce_float(item.get("end"), start)
        if end < start:
            end = start

        row: dict[str, Any] = {
            "id": len(normalized),
            "start": start,
            "end": end,
            "text": text,
        }
        tokens = item.get("tokens")
        if isinstance(tokens, list) and all(isinstance(token, dict) for token in tokens):
            row["tokens"] = [dict(token) for token in tokens]
        normalized.append(row)
    return normalized


def build_metadata_fields(record: Any) -> list[dict[str, str]]:
    """构建详情弹窗中展示的元数据字段。"""

    metadata = _read_metadata(record)
    return [
        {"label": "音频时长", "value": str(getattr(record, "duration_text", _MISSING) or _MISSING)},
        {"label": "文件大小", "value": format_size(int(getattr(record, "total_size_bytes", 0) or 0))},
        {"label": "创建日期", "value": _format_created_at(getattr(record, "created_at", None))},
        {"label": "状态", "value": str(getattr(record, "status_text", _MISSING) or _MISSING)},
        {"label": "来源", "value": _source_label(str(getattr(record, "source_kind", "") or ""))},
        {"label": "本地音视频所在路径", "value": _local_media_path(record)},
        {"label": "视频链接", "value": _remote_url(record, metadata)},
        {"label": "转录模型", "value": _metadata_first(metadata, ("processing", "transcription", "model"), ("asr", "model"))},
        {"label": "总结模型", "value": _metadata_first(metadata, ("processing", "summary", "model"), ("llm", "model"))},
    ]


def timeline_display_text(items: list[dict[str, Any]] | None) -> str:
    """把时间轴格式化为可复制的纯文本。"""

    return "\n".join(
        f"{format_display_time(item['start'])} - {format_display_time(item['end'])}  {item['text']}"
        for item in normalize_timeline_items(items)
    )


def find_active_timeline_segment(items: list[dict[str, Any]] | None, position_seconds: float | None) -> int | None:
    """根据播放位置查找当前时间轴片段索引。"""

    timeline = normalize_timeline_items(items)
    if not timeline or position_seconds is None:
        return None

    position = _non_negative_float(position_seconds)
    for index, item in enumerate(timeline):
        if item["start"] <= position <= item["end"]:
            return index
    for index, item in enumerate(timeline):
        if position < item["start"]:
            return max(0, index - 1)
    return len(timeline) - 1


def parse_detail_command(value: Any, current_record_key: str, current_revision: int) -> DetailCommand | None:
    """解析 WebView 发回的命令，非法或过期消息返回 None。"""

    if not isinstance(value, Mapping):
        return None

    command = value.get("command")
    if not isinstance(command, str):
        return None

    if command == "seek":
        if not _is_current_message(value, current_record_key, current_revision):
            return None
        seconds = _maybe_float(value.get("seconds"))
        if seconds is None:
            return None
        payload: dict[str, Any] = {"seconds": max(0.0, seconds), "segmentId": value.get("segmentId")}
        return DetailCommand(command="seek", payload=payload)

    if command == "copy":
        if not _is_current_message(value, current_record_key, current_revision):
            return None
        return DetailCommand(
            command="copy",
            payload={
                "mode": str(value.get("mode") or "transcript"),
                "text": str(value.get("text") or ""),
            },
        )

    if command == "openExternalUrl":
        if not _is_current_message(value, current_record_key, current_revision):
            return None
        url = value.get("url")
        if not isinstance(url, str) or not url:
            return None
        return DetailCommand(command="openExternalUrl", payload={"url": url})

    if command == "renderError":
        message = value.get("message")
        return DetailCommand(command="renderError", payload={"message": str(message or "")})

    if command == "ready":
        return DetailCommand(command="ready", payload={})

    return None


def _read_metadata(record: Any) -> dict[str, Any]:
    path = getattr(record, "metadata_path", None)
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _source_label(source_kind: str) -> str:
    labels = {
        "recording": "录音",
        "recorded": "录音",
        "local_audio": "本地文件",
        "local_video": "本地文件",
        "imported_file": "本地文件",
        "remote_url": "视频链接",
        "remote_audio": "视频链接",
        "remote_subtitle": "视频链接",
    }
    return labels.get(source_kind, _MISSING)


def _local_media_path(record: Any) -> str:
    for name in ("normalized_audio_path", "original_file_path", "audio_path"):
        value = getattr(record, name, None)
        if value:
            return str(value)
    return _MISSING


def _remote_url(record: Any, metadata: dict[str, Any]) -> str:
    value = _metadata_first(metadata, ("remote", "webpage_url"), ("remote", "url"), ("source_path",))
    if value != _MISSING:
        return value
    source_path = getattr(record, "source_path", None)
    return str(source_path) if source_path else _MISSING


def _metadata_first(metadata: dict[str, Any], *paths: tuple[str, ...]) -> str:
    for path in paths:
        value: Any = metadata
        for key in path:
            if not isinstance(value, dict) or key not in value:
                value = None
                break
            value = value[key]
        if value:
            return str(value)
    return _MISSING


def _format_created_at(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value) if value else _MISSING


def _is_current_message(value: Mapping[str, Any], current_record_key: str, current_revision: int) -> bool:
    revision = _maybe_int(value.get("revision"))
    return value.get("recordKey") == current_record_key and revision == current_revision


def _maybe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _maybe_int(value: Any) -> int | None:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        return int(value)
    except (OverflowError, TypeError, ValueError):
        return None


def _coerce_float(value: Any, default: float) -> float:
    parsed = _maybe_float(value)
    return default if parsed is None else parsed


def _non_negative_float(value: Any) -> float:
    parsed = _maybe_float(value)
    return max(0.0, parsed if parsed is not None else 0.0)
