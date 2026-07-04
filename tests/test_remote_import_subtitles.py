from __future__ import annotations

from pathlib import Path

from src.remote_import.subtitles import parse_srt_to_transcript_and_timeline, select_preferred_subtitle
from src.remote_import.types import RemoteMediaInfo, RemoteSubtitle


def test_select_subtitle_prefers_chinese_manual_before_english() -> None:
    info = RemoteMediaInfo(
        url="https://example.com/video",
        extractor="example",
        webpage_url="https://example.com/video",
        title="demo",
        duration_seconds=60,
        subtitles=[
            RemoteSubtitle("en", "English", "https://example.com/en.vtt", "vtt"),
            RemoteSubtitle("zh-CN", "中文", "https://example.com/zh.vtt", "vtt"),
        ],
    )

    selected = select_preferred_subtitle(info)

    assert selected is not None
    assert selected.language == "zh-CN"
    assert selected.is_auto is False


def test_select_subtitle_uses_auto_when_manual_missing() -> None:
    info = RemoteMediaInfo(
        url="https://example.com/video",
        extractor="example",
        webpage_url="https://example.com/video",
        title="demo",
        duration_seconds=60,
        automatic_captions=[
            RemoteSubtitle("en", "English auto", "https://example.com/en.vtt", "vtt", is_auto=True),
        ],
    )

    selected = select_preferred_subtitle(info)

    assert selected is not None
    assert selected.language == "en"
    assert selected.is_auto is True


def test_parse_srt_to_transcript_and_timeline(tmp_path: Path) -> None:
    subtitle = tmp_path / "external_subtitle.srt"
    subtitle.write_text(
        "1\n"
        "00:00:01,000 --> 00:00:02,500\n"
        "第一句\n\n"
        "2\n"
        "00:00:03,000 --> 00:00:04,000\n"
        "Second line\n",
        encoding="utf-8",
    )

    transcript, timeline = parse_srt_to_transcript_and_timeline(subtitle)

    assert transcript == "第一句\nSecond line"
    assert timeline == [
        {"start": 1.0, "end": 2.5, "text": "第一句", "tokens": []},
        {"start": 3.0, "end": 4.0, "text": "Second line", "tokens": []},
    ]
