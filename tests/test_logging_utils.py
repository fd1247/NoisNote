from __future__ import annotations

import os
import json
from pathlib import Path

from src.utils.logging import (
    LOG_DIR_ENV,
    file_context,
    init_logging,
    log_event,
    sanitize_context,
)


def _read_json_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_pytest_log_dir_is_isolated_from_user_documents(tmp_path: Path) -> None:
    assert os.environ.get(LOG_DIR_ENV) == str(tmp_path / "logs")


def test_log_event_writes_jsonl_and_error_file(tmp_path: Path) -> None:
    log_dir = init_logging(tmp_path)

    log_event(
        "asr.transcribe.failed",
        level="ERROR",
        module="asr",
        message="音频转录失败",
        record_id="20260624_120000",
        task_id="asr-test",
        error_code="ASR-002",
        error_type="RuntimeError",
        context={"model": "Qwen3-ASR-0.6B-GGUF", "text": "不应写入日志正文"},
    )

    app_entries = _read_json_lines(log_dir / "app.log")
    error_entries = _read_json_lines(log_dir / "error.log")

    assert app_entries[-1]["event"] == "asr.transcribe.failed"
    assert app_entries[-1]["module"] == "asr"
    assert app_entries[-1]["record_id"] == "20260624_120000"
    assert app_entries[-1]["task_id"] == "asr-test"
    assert app_entries[-1]["error_code"] == "ASR-002"
    assert app_entries[-1]["context"]["text"] == "[REDACTED]"
    assert error_entries[-1]["event"] == "asr.transcribe.failed"


def test_sanitize_context_redacts_sensitive_values_and_paths(tmp_path: Path) -> None:
    source = tmp_path / "secret meeting.mp3"
    source.write_bytes(b"audio")

    sanitized = sanitize_context(
        {
            "api_key": "sk-test",
            "source_path": str(source),
            "base_url": "https://api.example.test/v1/chat?token=secret",
            "audio_file": file_context(source),
            "text_length": 128,
            "summary_length": 64,
            "summary": "不应写入总结正文",
        }
    )

    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["source_path"]["path_hash"].startswith("sha256:")
    assert "secret meeting" not in json.dumps(sanitized, ensure_ascii=False)
    assert sanitized["base_url"] == {"scheme": "https", "host": "api.example.test"}
    assert sanitized["audio_file"]["ext"] == ".mp3"
    assert sanitized["audio_file"]["size_bytes"] == 5
    assert sanitized["text_length"] == 128
    assert sanitized["summary_length"] == 64
    assert sanitized["summary"] == "[REDACTED]"


def test_log_message_redacts_windows_paths_with_spaces(tmp_path: Path) -> None:
    log_dir = init_logging(tmp_path)

    log_event(
        "record.import.failed",
        level="ERROR",
        module="history",
        message="导入失败 C:/Users/xin/Desktop/secret meeting.mp3",
    )

    data = (log_dir / "app.log").read_text(encoding="utf-8")
    assert "secret meeting" not in data
    assert "C:/Users" not in data
    assert "[PATH:sha256:" in data


def test_log_message_keeps_url_readable_when_redacting_paths(tmp_path: Path) -> None:
    log_dir = init_logging(tmp_path)

    log_event(
        "summary.failed",
        level="ERROR",
        module="summary",
        message="Client error for url https://api.example.test/v1/chat",
    )

    data = (log_dir / "app.log").read_text(encoding="utf-8")
    assert "https://api.example.test/v1/chat" in data
    assert "http[PATH:" not in data
