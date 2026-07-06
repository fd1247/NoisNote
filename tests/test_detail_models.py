from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from src.history.types import HistoryRecord, HistoryStatus
from src.ui.detail_models import (
    build_detail_payload,
    build_metadata_fields,
    find_active_timeline_segment,
    normalize_timeline_items,
    parse_detail_command,
    timeline_display_text,
)


def _record(tmp_path: Path, **overrides) -> HistoryRecord:
    record_dir = tmp_path / "record"
    values = {
        "record_id": "20260706_120000",
        "layout": "v1",
        "record_dir": record_dir,
        "audio_path": record_dir / "audio.wav",
        "transcript_path": record_dir / "transcript.txt",
        "summary_path": record_dir / "summary.md",
        "markdown_path": record_dir / "summary.md",
        "metadata_path": record_dir / "metadata.json",
        "created_at": datetime(2026, 7, 6, 12, 0, 0),
        "duration_seconds": 61.2,
        "audio_size_bytes": 1024,
        "total_size_bytes": 2 * 1024 * 1024,
        "status": HistoryStatus.TRANSCRIBED,
        "source_kind": "remote_url",
    }
    values.update(overrides)
    return HistoryRecord(**values)


def test_build_detail_payload_transcript_mode_and_playback_shape(tmp_path: Path) -> None:
    record = _record(tmp_path)

    payload = build_detail_payload(
        record=record,
        mode="transcript",
        revision=3,
        content="hello",
        timeline=[{"start": "1", "end": "0.5", "text": "first"}],
        position_seconds=None,
        is_playing=True,
    )

    assert payload["revision"] == 3
    assert payload["recordKey"] == record.record_key
    assert payload["mode"] == "transcript"
    assert payload["title"] == record.display_name
    assert payload["content"] == "hello"
    assert payload["playback"] == {"positionSeconds": 0.0, "isPlaying": True}
    assert payload["timeline"][0]["text"] == "first"
    assert payload["timeline"][0]["end"] == payload["timeline"][0]["start"]
    assert "id" in payload["timeline"][0]


def test_build_detail_payload_falls_back_to_transcript_mode(tmp_path: Path) -> None:
    payload = build_detail_payload(
        record=_record(tmp_path),
        mode="unknown",
        revision=1,
        content="text",
        timeline=[],
        position_seconds=-2,
        is_playing=False,
    )

    assert payload["mode"] == "transcript"
    assert payload["playback"]["positionSeconds"] == 0.0


def test_build_detail_payload_normalizes_non_finite_playback_position(tmp_path: Path) -> None:
    payload = build_detail_payload(
        record=_record(tmp_path),
        mode="transcript",
        revision=1,
        content="text",
        timeline=[],
        position_seconds=float("inf"),
        is_playing=False,
    )

    assert payload["playback"]["positionSeconds"] == 0.0


def test_metadata_fields_include_remote_url_and_model_names(tmp_path: Path) -> None:
    record = _record(tmp_path)
    record.record_dir.mkdir(parents=True)
    record.metadata_path.write_text(
        json.dumps(
            {
                "remote": {"webpage_url": "https://example.com/watch"},
                "processing": {
                    "transcription": {"model": "Qwen3-ASR-1.7B-GGUF"},
                    "summary": {"model": "gpt-4.1"},
                },
            }
        ),
        encoding="utf-8",
    )

    fields = build_metadata_fields(record)
    labels = [field["label"] for field in fields]
    by_label = {field["label"]: field["value"] for field in fields}

    assert labels == [
        "音频时长",
        "文件大小",
        "创建日期",
        "状态",
        "来源",
        "本地音视频所在路径",
        "视频链接",
        "转录模型",
        "总结模型",
    ]
    assert by_label["来源"] == "视频链接"
    assert by_label["视频链接"] == "https://example.com/watch"
    assert by_label["转录模型"] == "Qwen3-ASR-1.7B-GGUF"
    assert by_label["总结模型"] == "gpt-4.1"


def test_metadata_fields_maps_remote_audio_to_video_link(tmp_path: Path) -> None:
    fields = {field["label"]: field["value"] for field in build_metadata_fields(_record(tmp_path, source_kind="remote_audio"))}

    assert fields["来源"] == "视频链接"


def test_metadata_fields_use_local_and_recording_labels_and_local_path_fallback(tmp_path: Path) -> None:
    local_record = _record(
        tmp_path,
        source_kind="local_video",
        normalized_audio_path=None,
        original_file_path=Path("D:/media/source.mp4"),
    )
    recording_record = _record(tmp_path, source_kind="recording", original_file_path=None)

    local_fields = {field["label"]: field["value"] for field in build_metadata_fields(local_record)}
    recording_fields = {field["label"]: field["value"] for field in build_metadata_fields(recording_record)}

    assert local_fields["来源"] == "本地文件"
    assert local_fields["本地音视频所在路径"] == "D:\\media\\source.mp4"
    assert recording_fields["来源"] == "录音"
    assert recording_fields["本地音视频所在路径"].endswith("audio.wav")


def test_timeline_active_segment_and_display_text() -> None:
    items = [
        {"start": 0, "end": 1, "text": "hello"},
        {"start": 2, "end": 3, "text": "world"},
    ]

    assert find_active_timeline_segment(items, None) is None
    assert find_active_timeline_segment(items, 0.5) == 0
    assert find_active_timeline_segment(items, 1.5) == 0
    assert find_active_timeline_segment(items, 2.5) == 1
    assert find_active_timeline_segment(items, 9) == 1
    assert timeline_display_text(items) == "00:00.000 - 00:01.000  hello\n00:02.000 - 00:03.000  world"


def test_timeline_non_finite_values_normalize_to_displayable_text() -> None:
    items = [
        {"start": float("inf"), "end": float("nan"), "text": "bad start"},
        {"start": 2, "end": float("-inf"), "text": "bad end"},
    ]

    normalized = normalize_timeline_items(items)

    assert all(math.isfinite(item["start"]) and math.isfinite(item["end"]) for item in normalized)
    assert normalized[0]["start"] == 0.0
    assert normalized[0]["end"] == 0.0
    assert normalized[1]["start"] == 2.0
    assert normalized[1]["end"] == 2.0
    assert timeline_display_text(items) == "00:00.000 - 00:00.000  bad start\n00:02.000 - 00:02.000  bad end"


def test_timeline_token_times_normalize_to_finite_values() -> None:
    normalized = normalize_timeline_items(
        [
            {
                "start": 1,
                "end": 2,
                "text": "with tokens",
                "tokens": [
                    {"start": float("inf"), "end": float("nan"), "text": "bad"},
                    {"start": 1.5, "end": 1.0, "text": "reversed", "confidence": 0.8},
                ],
            }
        ]
    )

    tokens = normalized[0]["tokens"]

    assert all(math.isfinite(token["start"]) and math.isfinite(token["end"]) for token in tokens)
    assert tokens[0] == {"start": 0.0, "end": 0.0, "text": "bad"}
    assert tokens[1] == {"start": 1.5, "end": 1.5, "text": "reversed", "confidence": 0.8}


def test_parse_detail_command_rejects_stale_and_malformed_input() -> None:
    assert parse_detail_command(None, "record:1", 2) is None
    assert parse_detail_command({"command": "unknown"}, "record:1", 2) is None
    assert (
        parse_detail_command(
            {"command": "seek", "recordKey": "record:0", "revision": 2, "seconds": 1},
            "record:1",
            2,
        )
        is None
    )
    assert (
        parse_detail_command(
            {"command": "copy", "recordKey": "record:1", "revision": 1, "mode": "summary", "text": "x"},
            "record:1",
            2,
        )
        is None
    )
    assert parse_detail_command({"command": "seek", "recordKey": "record:1", "revision": "bad"}, "record:1", 2) is None
    assert parse_detail_command({"command": "seek", "recordKey": "record:1", "revision": 2.9, "seconds": 1}, "record:1", 2) is None
    assert (
        parse_detail_command(
            {"command": "seek", "recordKey": "record:1", "revision": float("inf"), "seconds": 1},
            "record:1",
            2,
        )
        is None
    )


def test_parse_detail_command_rejects_non_finite_seek() -> None:
    assert (
        parse_detail_command(
            {"command": "seek", "recordKey": "record:1", "revision": 2, "seconds": float("inf")},
            "record:1",
            2,
        )
        is None
    )
    assert (
        parse_detail_command(
            {"command": "seek", "recordKey": "record:1", "revision": 2, "seconds": float("nan")},
            "record:1",
            2,
        )
        is None
    )


def test_parse_detail_command_accepts_current_seek() -> None:
    command = parse_detail_command(
        {"command": "seek", "recordKey": "record:1", "revision": 2, "seconds": "3.5", "segmentId": 7},
        "record:1",
        2,
    )

    assert command is not None
    assert command.command == "seek"
    assert command.payload == {"seconds": 3.5, "segmentId": 7}


def test_parse_detail_command_rejects_unknown_copy_mode_and_accepts_known_mode() -> None:
    assert (
        parse_detail_command(
            {"command": "copy", "recordKey": "record:1", "revision": 2, "mode": "unknown", "text": "x"},
            "record:1",
            2,
        )
        is None
    )

    command = parse_detail_command(
        {"command": "copy", "recordKey": "record:1", "revision": 2, "mode": "summary", "text": "x"},
        "record:1",
        2,
    )

    assert command is not None
    assert command.command == "copy"
    assert command.payload == {"mode": "summary", "text": "x"}


def test_parse_detail_command_checks_open_external_url_freshness() -> None:
    assert (
        parse_detail_command(
            {"command": "openExternalUrl", "recordKey": "record:0", "revision": 2, "url": "https://example.com"},
            "record:1",
            2,
        )
        is None
    )
    assert (
        parse_detail_command(
            {"command": "openExternalUrl", "recordKey": "record:1", "revision": 1, "url": "https://example.com"},
            "record:1",
            2,
        )
        is None
    )
    for url in ("file:///C:/temp/a.txt", "javascript:alert(1)", "", "   ", "https:///missing-host", "not a url"):
        assert (
            parse_detail_command(
                {"command": "openExternalUrl", "recordKey": "record:1", "revision": 2, "url": url},
                "record:1",
                2,
            )
            is None
        )

    command = parse_detail_command(
        {"command": "openExternalUrl", "recordKey": "record:1", "revision": 2, "url": "https://example.com"},
        "record:1",
        2,
    )

    assert command is not None
    assert command.command == "openExternalUrl"
    assert command.payload == {"url": "https://example.com"}
