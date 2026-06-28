"""应用结构化日志工具。"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import traceback
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SESSION_ID = uuid.uuid4().hex[:12]
LOGGER_NAME = "audio_recorder"
DEFAULT_LOG_DIR = Path.home() / "Documents" / "AudioRecorder" / "logs"
LOG_DIR_ENV = "AUDIO_RECORDER_LOG_DIR"

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "token",
    "secret",
    "password",
    "prompt",
    "content",
    "transcript",
    "summary",
    "text",
}
_PATH_KEY_MARKERS = ("path", "file")
_URL_KEY_MARKERS = ("url", "endpoint")
_WINDOWS_PATH_RE = re.compile(r"(?i)(?<![a-z])([a-z]:[\\/][^\"'<>|\r\n]+)")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[a-z0-9._\-]+")


class JsonLineFormatter(logging.Formatter):
    """把日志记录格式化为 JSON Lines。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
            "module": getattr(record, "event_module", record.module),
            "session_id": getattr(record, "session_id", SESSION_ID),
            "message": _sanitize_text(record.getMessage()),
        }
        for attr in ("record_id", "task_id", "error_code", "error_type"):
            value = getattr(record, attr, None)
            if value:
                payload[attr] = value

        context = getattr(record, "context", None)
        if context:
            payload["context"] = sanitize_context(context)

        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["exception"] = {
                "type": exc_type.__name__ if exc_type else "",
                "message": _sanitize_text(str(exc_value or "")),
                "traceback": [
                    _sanitize_text(line.rstrip())
                    for line in traceback.format_exception(*record.exc_info)
                ],
            }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def init_logging(log_dir: str | Path | None = None, debug: bool = False) -> Path:
    """初始化应用日志文件，返回实际日志目录。"""
    target_dir = Path(log_dir or os.environ.get(LOG_DIR_ENV) or DEFAULT_LOG_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False

    app_handler = _rotating_handler(target_dir / "app.log", logging.DEBUG if debug else logging.INFO)
    error_handler = _rotating_handler(target_dir / "error.log", logging.WARNING)
    crash_handler = _rotating_handler(target_dir / "crash.log", logging.CRITICAL)
    logger.addHandler(app_handler)
    logger.addHandler(error_handler)
    logger.addHandler(crash_handler)
    return target_dir


def install_exception_hooks() -> None:
    """安装未捕获异常兜底日志。"""

    def excepthook(exc_type, exc_value, exc_traceback) -> None:
        log_event(
            "app.unhandled_exception",
            level="CRITICAL",
            module="app",
            message="应用发生未捕获异常",
            error_type=exc_type.__name__ if exc_type else "",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    def threading_excepthook(args: threading.ExceptHookArgs) -> None:
        log_event(
            "app.thread_unhandled_exception",
            level="CRITICAL",
            module="app",
            message="后台线程发生未捕获异常",
            error_type=args.exc_type.__name__ if args.exc_type else "",
            context={"thread_name": args.thread.name if args.thread else ""},
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = excepthook
    threading.excepthook = threading_excepthook


def log_event(
    event: str,
    *,
    level: str | int = "INFO",
    module: str = "app",
    message: str = "",
    context: dict[str, Any] | None = None,
    record_id: str | None = None,
    task_id: str | None = None,
    error_code: str | None = None,
    error_type: str | None = None,
    exc_info=None,
) -> None:
    """写入一条结构化日志事件。"""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        init_logging()
    level_value = logging.getLevelName(level) if isinstance(level, str) else level
    if not isinstance(level_value, int):
        level_value = logging.INFO
    logger.log(
        level_value,
        message or event,
        extra={
            "event": event,
            "event_module": module,
            "session_id": SESSION_ID,
            "context": sanitize_context(context or {}),
            "record_id": record_id or "",
            "task_id": task_id or "",
            "error_code": error_code or "",
            "error_type": error_type or "",
        },
        exc_info=exc_info,
    )


def sanitize_context(value: Any, *, key: str = "") -> Any:
    """递归脱敏日志上下文。"""
    normalized_key = key.lower()
    if normalized_key.endswith("path_hash"):
        return value
    if _is_sensitive_key(normalized_key):
        return "[REDACTED]"
    if isinstance(value, Path):
        return file_context(value)
    if isinstance(value, dict):
        return {str(item_key): sanitize_context(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_context(item, key=key) for item in value]
    if isinstance(value, str):
        if any(marker in normalized_key for marker in _URL_KEY_MARKERS):
            return url_context(value)
        if any(marker in normalized_key for marker in _PATH_KEY_MARKERS):
            return _path_string_context(value)
        return _sanitize_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _sanitize_text(str(value))


def file_context(path: str | Path) -> dict[str, Any]:
    """返回不含真实路径和文件名的文件摘要。"""
    file_path = Path(path)
    context: dict[str, Any] = {
        "path_hash": hash_text(str(file_path)),
        "ext": file_path.suffix.lower(),
        "exists": file_path.exists(),
    }
    try:
        if file_path.exists() and file_path.is_file():
            context["size_bytes"] = file_path.stat().st_size
    except OSError:
        context["stat_error"] = True
    return context


def record_context(record) -> dict[str, Any]:
    """返回历史记录的安全摘要。"""
    if not record:
        return {}
    return {
        "record_id": getattr(record, "record_id", ""),
        "source_kind": getattr(record, "source_kind", ""),
        "audio_ext": getattr(record, "audio_path", Path("")).suffix.lower(),
        "audio_size_bytes": getattr(record, "audio_size_bytes", 0),
        "duration_seconds": getattr(record, "duration_seconds", None),
        "status": getattr(getattr(record, "status", ""), "value", str(getattr(record, "status", ""))),
        "storage_mode": getattr(record, "storage_mode", ""),
    }


def url_context(url: str) -> dict[str, str]:
    """返回 URL 的安全摘要，只保留协议和域名。"""
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.netloc,
    }


def hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _is_sensitive_key(key: str) -> bool:
    if key in _SENSITIVE_KEYS:
        return True
    return key.endswith(("_api_key", "_token", "_secret", "_password"))


def _rotating_handler(path: Path, level: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(JsonLineFormatter())
    return handler


def _path_string_context(value: str) -> dict[str, str]:
    path = Path(value)
    return {
        "path_hash": hash_text(value),
        "ext": path.suffix.lower(),
    }


def _sanitize_text(value: str) -> str:
    text = _BEARER_RE.sub(r"\1[REDACTED]", value)
    return _WINDOWS_PATH_RE.sub(lambda match: f"[PATH:{hash_text(match.group(1))}]", text)
