"""详情 WebView 的纯数据模型与消息协议。"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from src.app.config import DEFAULT_MODEL_CATALOG
from src.asr.timestamps import format_display_time
from src.history.types import format_duration_seconds, format_size
from src.llm.errors import summary_failure_message


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

    rows: list[dict[str, Any]] = []
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
            "id": 0,
            "start": start,
            "end": end,
            "text": text,
        }
        tokens = item.get("tokens")
        if isinstance(tokens, list):
            clean_tokens = [
                normalized_token
                for token in tokens
                if isinstance(token, dict)
                for normalized_token in [_normalize_token(token)]
                if normalized_token is not None
            ]
            if clean_tokens:
                row["tokens"] = clean_tokens
        rows.append(row)

    rows.sort(key=lambda row: (row["start"], row["end"]))
    for index, row in enumerate(rows):
        row["id"] = index
    return rows


def build_metadata_fields(record: Any) -> list[dict[str, str]]:
    """构建详情弹窗中展示的元数据字段。"""

    metadata = _read_metadata(record)
    source_label = _source_label(str(getattr(record, "source_kind", "") or ""))
    fields = [
        {"label": "音频时长", "value": str(getattr(record, "duration_text", _MISSING) or _MISSING)},
        {"label": "文件大小", "value": format_size(int(getattr(record, "total_size_bytes", 0) or 0))},
        {"label": "创建日期", "value": _format_created_at(getattr(record, "created_at", None))},
        {"label": "来源", "value": source_label},
    ]
    if source_label == "视频链接":
        remote_url = _remote_url(record, metadata)
        if remote_url != _MISSING:
            fields.append({"label": "网址", "value": remote_url})
    if source_label == "本地文件":
        fields.append({"label": "文件路径", "value": _local_media_path(record)})
    fields.extend(
        [
            {"label": "转录耗时", "value": _transcription_elapsed_text(metadata)},
            {
                "label": "ASR模型",
                "value": _model_display_name(
                    _metadata_first(metadata, ("processing", "transcription", "model"), ("asr", "model"))
                ),
            },
            {
                "label": "总结模型",
                "value": _summary_model(metadata),
            },
            {"label": "last_error", "value": _last_error_text(metadata)},
        ]
    )
    return fields


def timeline_display_text(items: list[dict[str, Any]] | None) -> str:
    """把时间轴格式化为可复制的纯文本。"""

    return "\n".join(
        f"{format_display_time(item['start'])} - {format_display_time(item['end'])}  {item['text']}"
        for item in normalize_timeline_items(items)
    )


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
        mode = str(value.get("mode") or "transcript")
        if mode not in _VALID_MODES:
            return None
        return DetailCommand(
            command="copy",
            payload={
                "mode": mode,
                "text": str(value.get("text") or ""),
            },
        )

    if command == "contentChanged":
        if not _is_current_message(value, current_record_key, current_revision):
            return None
        mode = str(value.get("mode") or "transcript")
        if mode not in _VALID_MODES:
            return None
        payload: dict[str, Any] = {
            "mode": mode,
            "text": str(value.get("text") or ""),
        }
        if mode == "timeline" and isinstance(value.get("timeline"), list):
            payload["timeline"] = value.get("timeline")
        return DetailCommand(
            command="contentChanged",
            payload=payload,
        )

    if command == "openExternalUrl":
        if not _is_current_message(value, current_record_key, current_revision):
            return None
        url = value.get("url")
        safe_url = _safe_external_url(url)
        if safe_url is None:
            return None
        return DetailCommand(command="openExternalUrl", payload={"url": safe_url})

    if command == "renderError":
        message = value.get("message")
        return DetailCommand(command="renderError", payload={"message": str(message or "")})

    if command == "scrollState":
        if not _is_current_message(value, current_record_key, current_revision):
            return None
        return DetailCommand(command="scrollState", payload={"atTop": bool(value.get("atTop"))})

    if command == "searchChanged":
        if not _is_current_message(value, current_record_key, current_revision):
            return None
        match_count = _maybe_int(value.get("matchCount"))
        index = _maybe_int(value.get("index"))
        return DetailCommand(
            command="searchChanged",
            payload={
                "matchCount": max(0, match_count or 0),
                "index": max(0, index or 0),
            },
        )

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


def _normalize_token(token: dict[str, Any]) -> dict[str, Any] | None:
    text = str(token.get("text") or "")
    if text == "":
        return None
    if not text.strip():
        text = " "
    row = dict(token)
    start = _non_negative_float(row.get("start"))
    end = _coerce_float(row.get("end"), start)
    if end < start:
        end = start
    row["start"] = start
    row["end"] = end
    row["text"] = text
    return row


def _local_media_path(record: Any) -> str:
    source_kind = str(getattr(record, "source_kind", "") or "")
    if source_kind in {"remote_url", "remote_subtitle"}:
        return _MISSING
    if source_kind == "remote_audio":
        for name in ("normalized_audio_path", "audio_path"):
            value = getattr(record, name, None)
            if value and _path_exists(value):
                return str(value)
        return _MISSING

    for name in ("original_file_path", "source_path", "normalized_audio_path", "audio_path"):
        value = getattr(record, name, None)
        if value and not _is_url_like_path(value):
            return str(value)
    return _MISSING


def _path_exists(value: Any) -> bool:
    try:
        return Path(value).exists()
    except (OSError, TypeError, ValueError):
        return False


def _is_url_like_path(value: Any) -> bool:
    text = str(value).strip().lower().replace("\\", "/")
    return text.startswith(("http:/", "https:/"))


def _remote_url(record: Any, metadata: dict[str, Any]) -> str:
    source_kind = str(getattr(record, "source_kind", "") or "")
    if source_kind not in {"remote_url", "remote_audio", "remote_subtitle"}:
        return _MISSING

    for value in (
        _metadata_value(metadata, ("remote", "canonical_url")),
        _metadata_value(metadata, ("remote", "webpage_url")),
        _metadata_value(metadata, ("remote", "url")),
        _metadata_value(metadata, ("source_path",)),
        getattr(record, "source_path", None),
    ):
        url = _safe_external_url(value)
        if url is not None:
            return url
    return _MISSING


def _metadata_first(metadata: dict[str, Any], *paths: tuple[str, ...]) -> str:
    for path in paths:
        value = _metadata_value(metadata, path)
        if value:
            return str(value)
    return _MISSING


def _metadata_value(metadata: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = metadata
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _summary_model(metadata: dict[str, Any]) -> str:
    if _metadata_value(metadata, ("processing", "summary", "status")) != "completed":
        return _MISSING
    return _metadata_first(metadata, ("processing", "summary", "model"), ("llm", "model"))


def _last_error_text(metadata: dict[str, Any]) -> str:
    value = metadata.get("last_error")
    if not isinstance(value, dict):
        legacy = str(metadata.get("error_message") or "").strip()
        return legacy or "None"
    message = str(value.get("message") or "").strip()
    if not message:
        return "None"
    raw_stage = str(value.get("stage") or "").strip()
    if raw_stage == "summary" and not message.startswith("总结失败："):
        friendly_message = summary_failure_message(message)
        if friendly_message != f"总结失败：{message}":
            return friendly_message
    stage = _last_error_stage_label(raw_stage)
    details = str(value.get("details") or "").strip()
    if details:
        message = f"{message}（{details}）"
    if message.startswith(f"{stage}失败："):
        return message
    if stage:
        return f"{stage}：{message}"
    return message


def _last_error_stage_label(stage: str) -> str:
    return {
        "input": "导入",
        "transcription": "转录",
        "summary": "总结",
        "general": "通用",
    }.get(stage, stage)


def _model_display_name(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or raw == _MISSING:
        return _MISSING
    normalized = raw.casefold()
    for item in DEFAULT_MODEL_CATALOG:
        candidates = {
            str(item.get("name") or "").casefold(),
            str(item.get("alias") or "").casefold(),
            str(item.get("display_name") or "").casefold(),
        }
        if normalized in candidates:
            return str(item.get("display_name") or raw)
    for item in DEFAULT_MODEL_CATALOG:
        display_name = str(item.get("display_name") or "")
        if display_name and normalized.startswith(display_name.casefold().removesuffix(" gguf")):
            return display_name
    return raw


def _format_elapsed_seconds(value: Any) -> str:
    parsed = _maybe_float(value)
    if parsed is None:
        return _MISSING
    return format_duration_seconds(parsed)


def _transcription_elapsed_text(metadata: dict[str, Any]) -> str:
    for path in (("processing", "transcription", "elapsed_seconds"), ("asr", "timings", "transcribe_seconds")):
        text = _format_elapsed_seconds(_metadata_value(metadata, path))
        if text != _MISSING:
            return text
    return _MISSING


def _format_created_at(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value) if value else _MISSING


def _is_current_message(value: Mapping[str, Any], current_record_key: str, current_revision: int) -> bool:
    revision = _maybe_int(value.get("revision"))
    return value.get("recordKey") == current_record_key and revision == current_revision


def _safe_external_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if any(char.isspace() or ord(char) < 32 or char == "\\" for char in value):
        return None
    url = value.strip()
    if not url:
        return None
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return None
    return url


def _maybe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _maybe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except (OverflowError, TypeError, ValueError):
        return None


def _coerce_float(value: Any, default: float) -> float:
    parsed = _maybe_float(value)
    return default if parsed is None else parsed


def _non_negative_float(value: Any) -> float:
    parsed = _maybe_float(value)
    return max(0.0, parsed if parsed is not None else 0.0)
